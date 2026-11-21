#!/usr/bin/env python3
"""Cheap scheduled preflight: skip daily production while any hard gate is closed.

Uses only the Python standard library and never decrypts voice data, invokes
AI providers, installs rendering dependencies, or uploads/publishes anything.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


TIMEZONE = "Asia/Kolkata"


def _read_json(path: Path, label: str, blockers: list[str]) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        blockers.append(f"{label} is missing or invalid JSON.")
        return {}
    if not isinstance(value, dict):
        blockers.append(f"{label} must be a JSON object.")
        return {}
    return value


def _first_statement_is_raise(path: Path, function_name: str) -> bool | None:
    """Return True for a fail-closed function, False for an open function."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None

    function = next(
        (
            node for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == function_name
        ),
        None,
    )
    if function is None:
        return None

    body = list(function.body)
    if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
        if isinstance(body[0].value.value, str):
            body.pop(0)
    if not body:
        return None
    return isinstance(body[0], ast.Raise)


def evaluate_daily_readiness(
    root: str | Path,
    *,
    today: str | None = None,
    upload_post_api_key: str | None = None,
) -> dict:
    root = Path(root)
    today = today or datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()
    blockers: list[str] = []

    request = _read_json(root / ".autopilot/prepare-request.json", "Daily production request", blockers)
    if request.get("mode") != "chatgpt_daily_production":
        blockers.append("Daily request mode is not chatgpt_daily_production.")

    plan_path_text = str(request.get("plan_path") or ".autopilot/daily-production-plan.json")
    plan_path = Path(plan_path_text)
    if (
        not plan_path_text.startswith(".autopilot/")
        or ".." in plan_path.parts
        or plan_path.is_absolute()
    ):
        blockers.append("Daily plan path must stay inside .autopilot/.")
        plan = {}
    else:
        plan = _read_json(root / plan_path, "Daily production plan", blockers)

    if str(plan.get("production_date") or "") != today:
        blockers.append(
            f"Daily plan production_date must be {today}; refresh the ChatGPT-authored plan before the scheduled run."
        )

    engine_dir = root / "autopilot/engine"
    voice_locked = _first_statement_is_raise(
        engine_dir / "voiceover.py", "require_approved_own_voice"
    )
    visuals_locked = _first_statement_is_raise(
        engine_dir / "run.py", "require_approved_illustration_provider"
    )

    if voice_locked is None:
        blockers.append("Could not verify the own-voice production gate.")
    elif voice_locked:
        blockers.append("Own-voice approval/provider gate is still locked.")
    else:
        if str(engine_dir) not in sys.path:
            sys.path.insert(0, str(engine_dir))
        try:
            from voiceover import require_approved_own_voice
            require_approved_own_voice(engine_dir / "voice-approval.json")
        except Exception as exc:
            blockers.append(
                "Private Qwen3 own-voice approval record is missing or invalid: "
                + str(exc)[:240]
            )

    if visuals_locked is None:
        blockers.append("Could not verify the illustration provider gate.")
    elif visuals_locked:
        blockers.append("Illustration provider is not configured and approved.")
    else:
        illustration = _read_json(
            engine_dir / "illustration-approval.json",
            "Local vector illustration approval record",
            blockers,
        )
        evidence = illustration.get("test_evidence")
        required_modes = [
            "comparison",
            "cover_performance",
            "macro_illustration",
            "mechanism_illustration",
            "melody_map",
            "waveform",
        ]
        if (
            illustration.get("schema_version") != 1
            or illustration.get("status") != "approved_for_preview"
            or illustration.get("provider") != "local_vector"
            or illustration.get("scope") != "preview_video_only"
            or illustration.get("renderer_version") != "violin-prince-vector-illustrator-v1"
            or illustration.get("publishing_enabled") is not False
            or not isinstance(evidence, dict)
            or not isinstance(evidence.get("workflow_run_id"), int)
            or evidence.get("workflow_run_id", 0) <= 0
            or evidence.get("workflow_status") != "success"
            or evidence.get("all_six_modes_passed") is not True
            or evidence.get("story_profile_scenes_passed") is not True
            or evidence.get("network_calls") is not False
            or evidence.get("output_width") != 1024
            or evidence.get("output_height") != 1792
            or evidence.get("output_format") != "JPEG"
            or evidence.get("modes") != required_modes
        ):
            blockers.append(
                "Local vector illustration approval record is missing required preview evidence or enables publishing."
            )

    # This workflow is preview-only; publishing credentials are not required.

    return {
        "ready": not blockers,
        "today": today,
        "timezone": TIMEZONE,
        "plan_path": plan_path_text,
        "blockers": blockers,
    }


def evaluate_daily_batch_readiness(
    root: str | Path,
    *,
    batch_path: str = ".autopilot/daily-batches/daily-production-batch.json",
    today: str | None = None,
) -> dict:
    """Check the four-plan batch and existing preview-only provider approvals."""
    root = Path(root)
    today = today or datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()
    blockers: list[str] = []
    relative = Path(batch_path)
    if not batch_path.startswith(".autopilot/") or ".." in relative.parts or relative.is_absolute():
        blockers.append("Daily batch path must stay inside .autopilot/.")
        plans = []
    else:
        try:
            from slot_registry import load_daily_batch, SlotContractError
            plans = load_daily_batch(root / relative, expected_date=today)
        except Exception as exc:
            blockers.append("Four-slot daily batch is missing or invalid: " + str(exc)[:300])
            plans = []

    engine_dir = root / "autopilot/engine"
    voice_locked = _first_statement_is_raise(engine_dir / "voiceover.py", "require_approved_own_voice")
    visuals_locked = _first_statement_is_raise(engine_dir / "run.py", "require_approved_illustration_provider")

    if voice_locked is None:
        blockers.append("Could not verify the own-voice production gate.")
    elif voice_locked:
        blockers.append("Own-voice approval/provider gate is still locked.")
    else:
        if str(engine_dir) not in sys.path:
            sys.path.insert(0, str(engine_dir))
        try:
            from voiceover import require_approved_own_voice
            require_approved_own_voice(engine_dir / "voice-approval.json")
        except Exception as exc:
            blockers.append("Private Qwen3 own-voice approval record is missing or invalid: " + str(exc)[:240])

    if visuals_locked is None:
        blockers.append("Could not verify the illustration provider gate.")
    elif visuals_locked:
        blockers.append("Illustration provider is not configured and approved.")
    else:
        illustration = _read_json(
            engine_dir / "illustration-approval.json",
            "Local vector illustration approval record",
            blockers,
        )
        evidence = illustration.get("test_evidence")
        required_modes = [
            "comparison", "cover_performance", "macro_illustration",
            "mechanism_illustration", "melody_map", "waveform",
        ]
        if (
            illustration.get("schema_version") != 1
            or illustration.get("status") != "approved_for_preview"
            or illustration.get("provider") != "local_vector"
            or illustration.get("scope") != "preview_video_only"
            or illustration.get("renderer_version") != "violin-prince-vector-illustrator-v1"
            or illustration.get("publishing_enabled") is not False
            or not isinstance(evidence, dict)
            or not isinstance(evidence.get("workflow_run_id"), int)
            or evidence.get("workflow_run_id", 0) <= 0
            or evidence.get("workflow_status") != "success"
            or evidence.get("all_six_modes_passed") is not True
            or evidence.get("story_profile_scenes_passed") is not True
            or evidence.get("network_calls") is not False
            or evidence.get("output_width") != 1024
            or evidence.get("output_height") != 1792
            or evidence.get("output_format") != "JPEG"
            or evidence.get("modes") != required_modes
        ):
            blockers.append("Local vector illustration approval record is missing required preview evidence or enables publishing.")

    return {
        "ready": not blockers,
        "today": today,
        "timezone": TIMEZONE,
        "batch_path": batch_path,
        "slot_ids": [str(item.get("slot_id") or "") for item in plans],
        "slot_count": len(plans),
        "blockers": blockers,
    }


def _write_github_outputs(result: dict) -> None:
    output_path = os.environ.get("GITHUB_OUTPUT", "").strip()
    if output_path:
        with open(output_path, "a", encoding="utf-8") as handle:
            handle.write(f"ready={'true' if result['ready'] else 'false'}\n")
            handle.write("blockers_json=" + json.dumps(result["blockers"], ensure_ascii=False) + "\n")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if summary_path:
        lines = [
            "## Daily Violin Prince production readiness",
            "",
            f"**Status:** {'READY' if result['ready'] else 'BLOCKED'}",
            f"**Date:** {result['today']} ({result['timezone']})",
        ]
        if result["blockers"]:
            lines.extend(["", "### Blockers"])
            lines.extend(f"- {item}" for item in result["blockers"])
        else:
            lines.extend(["", "All production and publishing preflight checks passed."])
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check whether today's scheduled Short can run.")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[2]))
    parser.add_argument("--today", default=None, help="Override local date for offline tests.")
    args = parser.parse_args(argv)

    result = evaluate_daily_readiness(args.root, today=args.today)
    _write_github_outputs(result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
