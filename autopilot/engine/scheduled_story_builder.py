#!/usr/bin/env python3
"""Research and commission exactly one public-ready story for the triggering IST slot.

This script does not render or upload. It writes the date's four-slot batch and a
research ledger to the checked-out repository, then commits those records before
the selector and production gates run.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

from scheduled_slot_date import resolve_scheduled_production_date
from slot_registry import SLOT_CATALOG, SlotContractError, load_daily_batch

ENGINE_DIR = Path(__file__).resolve().parent
SLOT_STORY_TYPES = {
    "music-secrets": ("violin_physics", "instrument_design", "sound_and_perception"),
    "production-tech": ("music_production", "music_technology"),
    "melody-stories": ("melody_and_composition", "song_anatomy", "violin_cover_breakdown"),
    "real-performance": ("violin_cover_breakdown",),
}


def _blocked_plan(production_date: str, slot_id: str, reason: str) -> dict[str, Any]:
    return {
        "production_date": production_date,
        "slot_id": slot_id,
        "slot_status": "blocked",
        "blocked_reason": str(reason).strip()[:1200] or "Research or production preflight did not pass.",
    }


def _empty_batch(production_date: str) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "production_date": production_date,
        "plans": [
            _blocked_plan(
                production_date,
                slot_id,
                "This category's assigned scheduled research cycle has not run yet.",
            )
            for slot_id in SLOT_CATALOG
        ],
    }


def _read_batch(path: Path, production_date: str) -> dict[str, Any]:
    if not path.is_file():
        return _empty_batch(production_date)
    plans = load_daily_batch(path, expected_date=production_date)
    return {
        "schema_version": 1,
        "production_date": production_date,
        "plans": [dict(plan) for plan in plans],
    }


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _performance_recording_path() -> Path:
    configured = os.environ.get("VIOLIN_RECORDING_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return ENGINE_DIR / "assets" / "violin-performance.wav"


def _build_ready_plan(
    slot_id: str,
    production_date: str,
    research_items: list[dict[str, Any]],
    story_groups: list[dict[str, Any]],
    recent_topics: list[str],
    now: datetime,
) -> dict[str, Any]:
    import run as engine

    allowed_types = SLOT_STORY_TYPES[slot_id]
    plan, _story_items, verified_sources = engine.prepare_story_with_source_recovery(
        research_items,
        recent=recent_topics,
        seo_context=None,
        max_candidates=6,
        as_of=now,
        allowed_story_types=allowed_types,
        story_groups=story_groups,
    )
    if str(plan.get("story_type") or "").strip() not in set(allowed_types):
        raise engine.PipelineError(
            "Selected story does not belong to the scheduled category; no fallback category is allowed."
        )
    plan["sources"] = verified_sources
    plan["production_date"] = production_date
    plan["slot_id"] = slot_id
    plan["slot_status"] = "ready"
    plan.pop("blocked_reason", None)

    date_check = engine.validate_story_dates(
        plan,
        as_of=now.astimezone(timezone.utc).date(),
    )
    if date_check.get("status") != "passed":
        raise engine.PipelineError(
            "Story date check failed: " + " ".join(date_check.get("issues", []))
        )
    quality = engine.build_story_quality_report(
        plan,
        verified_sources,
        date_check,
        as_of=now,
    )
    if quality.get("status") != "passed":
        raise engine.PipelineError("The source, freshness or narration evidence report did not pass.")
    plan["date_check"] = date_check
    plan["quality_control"] = quality

    source_lines = [
        f"{source.get('title', 'Publisher article')}: {source.get('url', '')}"
        for source in verified_sources
    ]
    description = str(plan.get("description") or "").strip()
    if source_lines:
        description = (description + "\n\nSources:\n" + "\n".join(source_lines)).strip()
    topic_tags = re.findall(r"[A-Za-z0-9][A-Za-z0-9+'._:-]{2,}", str(plan.get("topic") or ""))
    tags = list(dict.fromkeys(
        [*topic_tags[:8], str(plan.get("story_type") or ""), "Violin Prince", "Violin", "Music"]
    ))
    plan["publish_metadata"] = {
        "title": str(plan.get("title") or "").strip(),
        "description": description[:4800],
        "tags": [tag for tag in tags if tag][:20],
        "category_id": "10",
        "default_language": "en",
        "privacy_status": "public",
        "made_for_kids": False,
    }
    return plan


def _persist_records(
    repository_root: Path,
    batch_path: Path,
    history_path: Path,
    batch: dict[str, Any],
    history: dict[str, Any],
    *,
    dry_run: bool = False,
) -> None:
    _write_json(batch_path, batch)
    _write_json(history_path, history)
    if dry_run:
        return

    relative_paths = [
        str(batch_path.relative_to(repository_root)),
        str(history_path.relative_to(repository_root)),
    ]
    subprocess.run(["git", "add", "--", *relative_paths], cwd=repository_root, check=True)
    staged = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=repository_root,
        check=False,
    )
    if staged.returncode == 0:
        return
    if staged.returncode != 1:
        raise RuntimeError("Could not inspect staged research records.")
    subprocess.run(
        [
            "git", "-c", "user.name=github-actions[bot]",
            "-c", "user.email=41898282+github-actions[bot]@users.noreply.github.com",
            "commit", "-m", f"Record researched public Short slot {batch['production_date']}",
        ],
        cwd=repository_root,
        check=True,
    )

    # Commit before fetch/rebase: the named batch and research ledger are already
    # staged and durable, matching the safe ordering in the public uploader helper.
    last_error = None
    for _attempt in range(3):
        subprocess.run(["git", "fetch", "origin", "main"], cwd=repository_root, check=True)
        rebased = subprocess.run(
            ["git", "rebase", "origin/main"],
            cwd=repository_root,
            text=True,
            capture_output=True,
            check=False,
        )
        if rebased.returncode != 0:
            subprocess.run(["git", "rebase", "--abort"], cwd=repository_root, check=False)
            raise RuntimeError("Could not rebase researched slot records: " + (rebased.stderr or "")[-1200:])
        pushed = subprocess.run(
            ["git", "push", "origin", "HEAD:main"],
            cwd=repository_root,
            text=True,
            capture_output=True,
            check=False,
        )
        if pushed.returncode == 0:
            return
        last_error = pushed.stderr or pushed.stdout
    raise RuntimeError("Could not push the researched slot batch after three attempts: " + str(last_error)[-1200:])


def build_scheduled_batch(
    root: str | Path,
    *,
    production_date: str,
    slot_id: str,
    now: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    import run as engine

    root = Path(root).resolve()
    if slot_id not in SLOT_CATALOG:
        raise ValueError("A canonical production slot is required.")
    try:
        if date.fromisoformat(production_date).isoformat() != production_date:
            raise ValueError("not canonical")
    except ValueError as exc:
        raise ValueError("production_date must be canonical YYYY-MM-DD.") from exc

    identity = f"{production_date}-{slot_id}"
    attempt_path = root / ".autopilot" / "public-youtube-attempts" / f"{identity}.json"
    receipt_path = root / ".autopilot" / "public-youtube-receipts" / f"{identity}.json"
    batch_path = root / ".autopilot" / "daily-batches" / f"{production_date}.json"
    history_path = root / ".autopilot" / "research-history" / f"{identity}.json"

    if attempt_path.exists() or receipt_path.exists():
        return {
            "status": "terminal",
            "slot_id": slot_id,
            "production_date": production_date,
            "reason": "A durable public-upload attempt or receipt already exists; no research or retry was started.",
        }

    batch = _read_batch(batch_path, production_date)
    current = next(plan for plan in batch["plans"] if plan["slot_id"] == slot_id)
    if current.get("slot_status") == "ready":
        return {
            "status": "reused_existing_ready_plan",
            "slot_id": slot_id,
            "production_date": production_date,
            "title": current.get("title", ""),
            "reason": "An eligible plan is already recorded for this identity; research was not repeated.",
        }

    if history_path.exists():
        return {
            "status": "reconciliation_required",
            "slot_id": slot_id,
            "production_date": production_date,
            "reason": "A research ledger already exists for this slot but no ready or blocked batch record is present. Refusing to research the same cycle again.",
        }

    now = now or datetime.now(timezone.utc)

    # Durable research claim: commit this identity before making any network
    # calls. If a runner disappears mid-search, the next cron sees the ledger
    # and refuses to repeat the same research cycle.
    research_claim = {
        "schema_version": 1,
        "production_date": production_date,
        "slot_id": slot_id,
        "research_identity": identity,
        "researched_at_utc": now.astimezone(timezone.utc).isoformat(),
        "status": "researching",
        "reason": "Research claim committed before live discovery. Reconcile this identity if the runner stops before completion.",
        "research_record_count": 0,
        "story_groups": [],
        "selected_topic": "",
    }
    _persist_records(root, batch_path, history_path, batch, research_claim, dry_run=dry_run)

    workspace = root / "work" / "scheduled-research" / production_date / slot_id
    engine.WORK = workspace / "work"
    engine.OUT = workspace / "output"
    engine.IMAGES = workspace / "images"
    engine.WORK.mkdir(parents=True, exist_ok=True)

    research_items: list[dict[str, Any]] = []
    raw_research_items: list[dict[str, Any]] = []
    discovered_story_groups: list[dict[str, Any]] = []
    eligible_story_groups: list[dict[str, Any]] = []
    all_topics = engine.all_researched_topics()
    recent_topics = all_topics[-100:]
    skipped_repeated_groups: list[str] = []
    skipped_repeat_research_items: list[str] = []
    research_error = ""
    try:
        engine.log(f"Starting fresh internet research for {production_date}/{slot_id}.")
        raw_research_items = engine.research()
        from select_public_queue import _same_story_topic

        for item in raw_research_items:
            if not isinstance(item, dict):
                continue
            headline = str(item.get("title") or item.get("headline") or "").strip()
            if headline and any(_same_story_topic(headline, old_topic) for old_topic in all_topics):
                skipped_repeat_research_items.append(headline)
                continue
            research_items.append(item)

        discovered_story_groups = engine.discover_source_first_story_groups(
            research_items,
            max_seed_queries=3,
            max_phrases=4,
            as_of=now,
        )
        if not discovered_story_groups:
            raise engine.PipelineError(
                "Research did not find two independent, readable and date-verified publisher sources for an eligible story."
            )

        for group in discovered_story_groups:
            topic_hint = str(group.get("topic_hint") or "").strip()
            if topic_hint and any(_same_story_topic(topic_hint, old_topic) for old_topic in all_topics):
                skipped_repeated_groups.append(topic_hint)
                continue
            eligible_story_groups.append(group)

        if not eligible_story_groups:
            raise engine.PipelineError(
                "All verified story groups matched subjects or publisher headlines already present in research history. "
                "No topic was repeated."
            )

        if slot_id == "real-performance":
            recording = _performance_recording_path()
            if not recording.is_file():
                raise engine.PipelineError(
                    "Real Performance requires an actual creator-recorded violin WAV via VIOLIN_RECORDING_PATH. "
                    "No recording is available; a generated or CC0 phrase must not be presented as the creator's performance."
                )
            engine._validate_creator_violin_recording(recording)

        plan = _build_ready_plan(
            slot_id,
            production_date,
            research_items,
            eligible_story_groups,
            recent_topics,
            now,
        )
        planned_topic = str(plan.get("topic") or plan.get("core_claim") or "").strip()
        if planned_topic and any(_same_story_topic(planned_topic, old_topic) for old_topic in all_topics):
            raise engine.PipelineError(
                "The generated story topic matches the persistent researched-topic archive; refusing duplicate production."
            )
        batch["plans"] = [
            plan if item["slot_id"] == slot_id else item
            for item in batch["plans"]
        ]
        research_status = "story_plan_created"
        research_error = ""
    except Exception as exc:
        reason = str(exc).strip() or exc.__class__.__name__
        research_error = reason[:1100]
        batch["plans"] = [
            _blocked_plan(production_date, slot_id, research_error)
            if item["slot_id"] == slot_id else item
            for item in batch["plans"]
        ]
        research_status = "blocked"

    history = {
        "schema_version": 1,
        "production_date": production_date,
        "slot_id": slot_id,
        "research_identity": identity,
        "researched_at_utc": now.astimezone(timezone.utc).isoformat(),
        "status": research_status,
        "reason": research_error,
        "research_record_count": len(raw_research_items),
        "eligible_research_record_count": len(research_items),
        "skipped_repeat_research_items": skipped_repeat_research_items,
        "research_items": [
            {
                "title": item.get("title") or item.get("headline") or "",
                "url": item.get("url") or item.get("link") or "",
                "publisher_domain": item.get("publisher_domain") or item.get("domain") or item.get("source") or "",
                "published_at": item.get("published_at") or item.get("published") or item.get("date") or "",
            }
            for item in raw_research_items
            if isinstance(item, dict)
        ],
        "story_groups": [
            {
                "group_id": group.get("group_id"),
                "topic_hint": group.get("topic_hint"),
                "source_ids": group.get("source_ids", []),
                "publisher_families": group.get("publisher_families", []),
                "sources": [
                    {
                        "title": source.get("title"),
                        "url": source.get("url"),
                        "publisher_domain": source.get("publisher_domain"),
                    }
                    for source in group.get("sources", [])
                ],
            }
            for group in discovered_story_groups
        ],
        "eligible_group_count": len(eligible_story_groups),
        "skipped_repeated_groups": skipped_repeated_groups,
        "selected_topic": next(
            (
                plan.get("topic")
                for plan in batch["plans"]
                if plan.get("slot_id") == slot_id and plan.get("slot_status") == "ready"
            ),
            "",
        ),
    }
    _persist_records(root, batch_path, history_path, batch, history, dry_run=dry_run)
    return {
        "status": research_status,
        "slot_id": slot_id,
        "production_date": production_date,
        "title": next(
            (
                plan.get("title", "")
                for plan in batch["plans"]
                if plan.get("slot_id") == slot_id and plan.get("slot_status") == "ready"
            ),
            "",
        ),
        "blocked_reason": research_error,
        "research_record_count": len(raw_research_items),
        "eligible_research_record_count": len(research_items),
        "verified_story_groups": len(discovered_story_groups),
        "eligible_story_groups": len(eligible_story_groups),
        "skipped_repeated_groups": len(skipped_repeated_groups),
        "batch_sha256": hashlib.sha256(batch_path.read_bytes()).hexdigest() if batch_path.is_file() else "",
        "history_path": str(history_path.relative_to(root)),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    parser.add_argument("--cron", required=True, help="Exact value of github.event.schedule.")
    parser.add_argument("--production-date", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        scheduled = resolve_scheduled_production_date(
            args.cron,
            now=datetime.now(timezone.utc),
        )
        if scheduled["production_date"] != args.production_date:
            raise ValueError("The supplied batch date does not match the triggering cron's resolved IST date.")
        slot_id = str(scheduled["slot_id"])
        result = build_scheduled_batch(
            args.root,
            production_date=args.production_date,
            slot_id=slot_id,
            dry_run=args.dry_run,
        )
    except Exception as exc:
        print("SCHEDULED_RESEARCH_ERROR=" + str(exc)[:1200], file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result["status"] == "blocked":
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
