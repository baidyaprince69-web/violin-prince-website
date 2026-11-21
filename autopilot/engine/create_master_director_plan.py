"""Source-verified Master Creative Director job for GitHub Actions.

This command validates one ready queue story with the same publisher and
narration gates used by scheduled production, then asks GitHub Copilot CLI for
the v2 director plan. It writes a director plan and a per-shot layer-generation
brief only; it never renders or publishes.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE_DIR = Path(__file__).resolve().parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from copilot_director_provider import (  # noqa: E402
    CopilotDirectorError,
    generate_director_plan,
    write_director_plan,
)
from run_daily_plan import validate_and_enrich_plan  # noqa: E402
from slot_registry import SLOT_CATALOG, SlotContractError, load_daily_batch  # noqa: E402


class DirectorJobError(RuntimeError):
    """Raised when the verified story cannot receive a production-ready plan."""


def _read_ready_story(batch_path: Path, slot_id: str) -> tuple[dict[str, Any], list[dict[str, Any]], str, str]:
    if slot_id not in SLOT_CATALOG:
        raise DirectorJobError(f"Unknown canonical slot ID: {slot_id!r}.")
    try:
        batch_bytes = batch_path.read_bytes()
        payload = json.loads(batch_bytes.decode("utf-8"))
        batch_date = str(payload.get("production_date") or "")
        plans = load_daily_batch(batch_path, expected_date=batch_date)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, SlotContractError, AttributeError) as exc:
        raise DirectorJobError("Daily batch could not be validated: " + str(exc)) from exc

    selected = next((dict(item) for item in plans if item.get("slot_id") == slot_id), None)
    if selected is None:
        raise DirectorJobError(f"Batch does not contain slot {slot_id!r}.")
    if str(selected.get("slot_status") or "ready").strip().casefold() != "ready":
        reason = str(selected.get("blocked_reason") or "the slot is marked blocked.")
        raise DirectorJobError("Selected story is blocked: " + reason[:500])
    batch_sha256 = hashlib.sha256(batch_bytes).hexdigest()
    return selected, plans, batch_date, batch_sha256


def _build_layer_generation_brief(
    director_plan: dict[str, Any],
    *,
    batch_date: str,
    slot_id: str,
    batch_sha256: str,
) -> dict[str, Any]:
    shots = director_plan["storyboard"]["shots"]
    shot_requests = []
    for shot in shots:
        layers = []
        for layer in shot["visual_layers"]:
            layers.append({
                "layer_id": layer["id"],
                "role": layer["role"],
                "z_index": layer["z_index"],
                "asset_mode": layer["asset_mode"],
                "description": layer["description"],
                "generation_prompt": layer["generation_prompt"],
                "motion": dict(layer["motion"]),
                "technical_output": (
                    "Full-frame opaque RGB image, portrait 9:16."
                    if layer["asset_mode"] == "opaque"
                    else "Portrait 9:16 PNG cutout with real transparency and non-opaque pixels; do not paint a background."
                ),
            })
        shot_requests.append({
            "shot_id": shot["id"],
            "start_seconds": shot["start_seconds"],
            "end_seconds": shot["end_seconds"],
            "visual_subject": shot["visual_subject"],
            "setting": shot["setting"],
            "composition": shot["composition"],
            "camera": dict(shot["camera"]),
            "layers": layers,
        })

    return {
        "schema_version": 1,
        "status": "generation_brief_ready_provider_not_connected",
        "production_date": batch_date,
        "slot_id": slot_id,
        "batch_sha256": batch_sha256,
        "director_contract_version": director_plan.get("_director_provider", {}).get("contract_version"),
        "visual_concept": director_plan["visual_concept"],
        "shot_count": len(shot_requests),
        "shots": shot_requests,
        "provider_requirement": (
            "A permitted cinematic scene-generation provider must generate each listed layer as a distinct asset. "
            "Do not use the legacy local vector illustrator, reuse assets, or fake transparent cutouts."
        ),
    }


def create_master_director_plan(
    batch_path: str | Path,
    slot_id: str,
    output_dir: str | Path,
    *,
    preferences: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Verify one rolling queue story, generate its director plan, and save artifacts."""
    selected, _plans, batch_date, batch_sha256 = _read_ready_story(
        Path(batch_path).expanduser(),
        slot_id,
    )
    try:
        verified_plan, verified_sources = validate_and_enrich_plan(selected)
    except Exception as exc:
        raise DirectorJobError(
            "The selected story did not pass the existing source, exact-quote, narration and coherence checks: "
            + str(exc)[:900]
        ) from exc

    source_context = {
        "topic": str(verified_plan.get("topic") or verified_plan.get("core_claim") or ""),
        "title": str(verified_plan.get("title") or ""),
        "hook": str(verified_plan.get("hook") or ""),
        "core_claim": str(verified_plan.get("core_claim") or ""),
        "narration_script": str(verified_plan.get("narration_script") or ""),
        "verified_sources": verified_sources,
        "target_duration_seconds": verified_plan.get("target_duration_seconds"),
    }
    try:
        director_plan = generate_director_plan(
            source_context,
            creator_preferences=preferences,
        )
    except CopilotDirectorError as exc:
        raise DirectorJobError("GitHub Copilot Master Director failed: " + str(exc)) from exc

    provider_metadata = director_plan.get("_director_provider")
    contract_version = str((provider_metadata or {}).get("contract_version") or "")
    if contract_version != "violin-prince-master-director-v2":
        raise DirectorJobError(
            "Copilot returned a director plan from an unexpected contract version; expected v2."
        )

    director_plan["production_context"] = {
        "production_date": batch_date,
        "slot_id": slot_id,
        "production_identity": batch_date + ":" + slot_id,
        "batch_sha256": batch_sha256,
        "original_title": str(verified_plan.get("title") or ""),
        "topic": str(verified_plan.get("topic") or ""),
        "source_ids": [str(source.get("source_id") or "") for source in verified_sources],
        "source_publishers": sorted({
            str(source.get("publisher_domain") or "")
            for source in verified_sources
            if source.get("publisher_domain")
        }),
        "verified_at_utc": datetime.now(timezone.utc).isoformat(),
        "research_gate": "passed_existing_two_publisher_quote_narration_and_story_coherence_checks",
    }

    destination = Path(output_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    plan_path = write_director_plan(
        director_plan,
        destination / "master-director-plan.json",
    )
    brief = _build_layer_generation_brief(
        director_plan,
        batch_date=batch_date,
        slot_id=slot_id,
        batch_sha256=batch_sha256,
    )
    brief_path = destination / "shot-layer-generation-brief.json"
    temporary = brief_path.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(brief, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(brief_path)

    summary = {
        "status": "director_plan_created",
        "production_date": batch_date,
        "slot_id": slot_id,
        "title": str(verified_plan.get("title") or ""),
        "storyboard_duration_seconds": director_plan["storyboard"]["duration_seconds"],
        "shot_count": len(director_plan["storyboard"]["shots"]),
        "visual_concept": director_plan["visual_concept"]["concept_name"],
        "palette": director_plan["visual_concept"]["palette"],
        "source_count": len(verified_sources),
        "master_director_plan": str(plan_path),
        "layer_generation_brief": str(brief_path),
        "rendered": False,
        "published": False,
        "next_dependency": "eligible cinematic layered image-generation provider",
    }
    print("MASTER_DIRECTOR_RESULT=" + json.dumps(summary, ensure_ascii=False), flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a source-verified Master Creative Director v2 plan with GitHub Copilot."
    )
    parser.add_argument("--batch", required=True, help="Path to the immutable four-slot daily batch JSON.")
    parser.add_argument("--slot-id", required=True, choices=tuple(SLOT_CATALOG))
    parser.add_argument("--output-dir", default="work/master-director")
    args = parser.parse_args()
    try:
        create_master_director_plan(
            args.batch,
            args.slot_id,
            args.output_dir,
        )
        return 0
    except Exception as exc:
        print("Master Creative Director stopped safely: " + str(exc)[:1200], file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
