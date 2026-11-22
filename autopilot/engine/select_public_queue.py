#!/usr/bin/env python3
"""Select the next unclaimed, public-ready Violin Prince story from the rolling backlog.

The queue is ordered by batch date, then by the canonical four-slot order.
Successful uploads and any started/uncertain upload attempts are terminal queue
records and are never selected automatically again.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from slot_registry import SLOT_CATALOG, SlotContractError, load_daily_batch, slot_workspace

TIMEZONE = "Asia/Kolkata"


def _identity(production_date: str, slot_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", f"{production_date}-{slot_id}").strip("-")


def _normalise_title(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip().casefold()


def _scan_youtube_history(api_key: str) -> tuple[set[str], dict[str, Any]]:
    """Read the connected channel's complete Upload-Post media history before choosing a story."""
    if not api_key:
        raise RuntimeError("UPLOAD_POST_API_KEY is required for the pre-selection YouTube history audit.")
    import requests
    from upload_private_preview_uploadpost import (
        DEFAULT_UPLOAD_POST_USER,
        _scan_existing_titles,
    )

    with requests.Session() as session:
        audit = _scan_existing_titles(
            session,
            {"Authorization": "Apikey " + api_key},
            DEFAULT_UPLOAD_POST_USER,
        )
    titles = audit.pop("_normalised_titles", None)
    if not isinstance(titles, set):
        raise RuntimeError("The YouTube history audit returned no usable title index.")
    return titles, audit


def _write_outputs(values: dict[str, str]) -> None:
    output = os.environ.get("GITHUB_OUTPUT", "").strip()
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            for key, value in values.items():
                handle.write(f"{key}={str(value).replace(chr(10), ' ').replace(chr(13), ' ')}\n")


def _write_summary(message: str) -> None:
    summary = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if summary:
        with open(summary, "a", encoding="utf-8") as handle:
            handle.write(message.rstrip() + "\n")


def select_next_public_plan(
    root: str | Path,
    *,
    after_date: str | None = None,
    production_date: str | None = None,
    batches_dir: str = ".autopilot/daily-batches",
    attempts_dir: str = ".autopilot/public-youtube-attempts",
    receipts_dir: str = ".autopilot/public-youtube-receipts",
    existing_titles: set[str] | None = None,
) -> dict[str, Any]:
    """Return the earliest ready, public, unused plan for an exact date or lower bound."""
    root = Path(root).resolve()
    if after_date and production_date:
        raise ValueError("Use either production_date for an exact batch or after_date for a rolling lower bound, not both.")
    if production_date:
        try:
            if date.fromisoformat(production_date).isoformat() != production_date:
                raise ValueError("not canonical")
        except ValueError as exc:
            raise ValueError("production_date must use canonical YYYY-MM-DD.") from exc
    else:
        after_date = after_date or date.today().isoformat()
        try:
            if date.fromisoformat(after_date).isoformat() != after_date:
                raise ValueError("not canonical")
        except ValueError as exc:
            raise ValueError("after_date must use canonical YYYY-MM-DD.") from exc

    batch_root = (root / batches_dir).resolve()
    attempt_root = (root / attempts_dir).resolve()
    receipt_root = (root / receipts_dir).resolve()
    if root not in batch_root.parents or root not in attempt_root.parents or root not in receipt_root.parents:
        raise ValueError("Queue state directories must remain inside the repository root.")

    candidates: list[dict[str, Any]] = []
    ignored_batches: list[str] = []
    duplicate_channel_matches: list[str] = []
    existing_titles = {
        _normalise_title(value) for value in (existing_titles or set())
        if _normalise_title(value)
    }
    checked_batches = 0

    for batch_path in sorted(batch_root.glob("????-??-??.json")) if batch_root.is_dir() else []:
        batch_date = batch_path.stem
        try:
            date.fromisoformat(batch_date)
        except ValueError:
            continue
        if production_date is not None:
            # Scheduled runs must be pinned to the date implied by their cron slot.
            # Never fall forward into a later day when that batch is exhausted or absent.
            if batch_date != production_date:
                continue
        elif batch_date < after_date:
            continue
        checked_batches += 1
        try:
            plans = load_daily_batch(batch_path, expected_date=batch_date)
        except (SlotContractError, OSError, ValueError) as exc:
            ignored_batches.append(f"{batch_path.name}: {str(exc)[:180]}")
            continue

        batch_sha256 = hashlib.sha256(batch_path.read_bytes()).hexdigest()
        for plan in plans:
            slot_id = str(plan.get("slot_id") or "")
            if str(plan.get("slot_status") or "ready").strip().lower() != "ready":
                continue
            metadata = plan.get("publish_metadata")
            if not isinstance(metadata, dict) or str(metadata.get("privacy_status") or "").lower() != "public":
                continue

            title = str(metadata.get("title") or plan.get("title") or "").strip()
            topic = str(plan.get("topic") or "").strip()
            core_claim = str(plan.get("core_claim") or "").strip()
            if any(
                _normalise_title(candidate) in existing_titles
                for candidate in (title, topic, core_claim)
                if candidate
            ):
                duplicate_channel_matches.append(f"{batch_date}/{slot_id}: {title}")
                continue

            identity = _identity(batch_date, slot_id)
            attempt_path = attempt_root / f"{identity}.json"
            receipt_path = receipt_root / f"{identity}.json"
            # Any durable attempt marker is terminal for automatic queueing.
            # This includes uncertain outcomes, which must be reconciled manually.
            if attempt_path.exists() or receipt_path.exists():
                continue

            candidates.append({
                "production_date": batch_date,
                "slot_id": slot_id,
                "title": str(metadata.get("title") or plan.get("title") or "").strip(),
                "batch_path": str(batch_path.relative_to(root)),
                "batch_sha256": batch_sha256,
                "workspace_root": str(slot_workspace(Path("work/slots"), batch_date, slot_id)),
                "identity": identity,
            })

    if not candidates:
        blocked_reason = (
            f"No unused, public-ready story exists in the exact {production_date} batch. "
            "The scheduled run will not fall forward into another production date."
            if production_date else
            "No unused, public-ready story exists in today's or any later prepared batch. "
            "Prepare another source-checked batch to refill the rolling queue."
        )
        if duplicate_channel_matches:
            blocked_reason += (
                f" {len(duplicate_channel_matches)} candidate title/topic match(es) "
                "were already present in the connected YouTube channel and were skipped."
            )
        return {
            "ready": False,
            "slot_status": "blocked",
            "production_date": production_date or "",
            "blocked_reason": blocked_reason,
            "checked_batches": checked_batches,
            "remaining_ready_count": 0,
            "ignored_batches": ignored_batches,
            "duplicate_channel_matches": duplicate_channel_matches,
        }

    chosen = candidates[0]
    return {
        "ready": True,
        "slot_status": "ready",
        "blocked_reason": "",
        **chosen,
        "checked_batches": checked_batches,
        "remaining_ready_count": len(candidates),
        "ignored_batches": ignored_batches,
        "duplicate_channel_matches": duplicate_channel_matches,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=".")
    date_group = parser.add_mutually_exclusive_group()
    date_group.add_argument("--after-date", default=None, help="Earliest eligible batch date, inclusive (rolling queue mode).")
    date_group.add_argument("--production-date", default=None, help="Select only this exact Asia/Kolkata production batch; never fall forward.")
    args = parser.parse_args(argv)

    after_date = args.after_date
    if not after_date and not args.production_date:
        from datetime import datetime
        after_date = datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()

    try:
        existing_titles, youtube_history = _scan_youtube_history(
            os.environ.get("UPLOAD_POST_API_KEY", "").strip()
        )
    except Exception as exc:
        message = "YouTube history audit failed; no story was selected: " + str(exc)[:500]
        _write_summary("## YouTube history audit blocked\n\n" + message)
        print(message, file=sys.stderr)
        return 2

    result = select_next_public_plan(
        args.root,
        after_date=after_date,
        production_date=args.production_date,
        existing_titles=existing_titles,
    )
    result["youtube_history"] = youtube_history
    outputs = {
        "slot_status": str(result.get("slot_status") or "blocked"),
        "slot_id": str(result.get("slot_id") or ""),
        "production_date": str(result.get("production_date") or ""),
        "batch_path": str(result.get("batch_path") or ""),
        "batch_sha256": str(result.get("batch_sha256") or ""),
        "workspace_root": str(result.get("workspace_root") or ""),
        "blocked_reason": str(result.get("blocked_reason") or ""),
        "queue_remaining": str(result.get("remaining_ready_count") or 0),
        "selected_title": str(result.get("title") or ""),
        "youtube_history_status": str(youtube_history.get("status") or ""),
        "youtube_uploads_examined": str(youtube_history.get("uploads_examined") or 0),
        "youtube_titles_indexed": str(youtube_history.get("title_count") or 0),
    }
    _write_outputs(outputs)

    if result["ready"]:
        summary = [
            "## Rolling YouTube queue selection",
            "",
            f"- **Selected:** {result['title']}",
            f"- **Batch date:** {result['production_date']}",
            f"- **Content slot:** {result['slot_id']}",
            f"- **Unused ready stories in queue, including this one:** {result['remaining_ready_count']}",
            f"- **YouTube uploads checked before selection:** {youtube_history['uploads_examined']} across {youtube_history['pages_checked']} page(s)",
            f"- **Already-uploaded title/topic matches skipped:** {len(result.get('duplicate_channel_matches', []))}",
            "- The publisher repeats the duplicate audit immediately before upload.",
        ]
    else:
        summary = [
            "## Rolling YouTube queue is empty",
            "",
            f"- {result['blocked_reason']}",
            f"- YouTube history audit passed: {youtube_history['uploads_examined']} uploads examined.",
            f"- Already-uploaded title/topic matches skipped: {len(result.get('duplicate_channel_matches', []))}.",
        ]
    if result.get("ignored_batches"):
        summary.extend(["", "### Invalid batches ignored"])
        summary.extend(f"- {item}" for item in result["ignored_batches"])
    _write_summary("\n".join(summary))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
