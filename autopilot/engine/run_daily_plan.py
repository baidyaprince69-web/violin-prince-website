#!/usr/bin/env python3
"""Produce a ChatGPT-planned Violin Prince explainer with Kokoro and 2D Motion.

This production entry point deliberately has no source-research, publisher-quote,
date-verification, 3D asset discovery, Blender, or Frame By Plane dependency.
The supplied creative plan is rendered directly with the native Motion +
HyperFrames pipeline. Kokoro's native word timings are retained for captions.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))

from motion_hyperframes_renderer import (  # noqa: E402
    MotionHyperFramesError,
    render_full_track,
)
from violin_sampler import create_sampled_violin_bed  # noqa: E402
from voiceover import synthesize_voiceover  # noqa: E402


def normalize_production_plan(value: Any) -> dict[str, Any]:
    """Check only the fields required to create a five-scene 2D explainer."""
    if not isinstance(value, dict):
        raise ValueError("The production plan must be a JSON object.")

    plan = dict(value)
    plan["title"] = str(plan.get("title") or "Violin Prince").strip()[:90]
    plan["topic"] = str(plan.get("topic") or plan["title"]).strip()[:220]
    plan["hook"] = str(plan.get("hook") or plan["title"]).strip()[:220]
    plan["narration_script"] = re.sub(
        r"\s+", " ", str(plan.get("narration_script") or "")
    ).strip()
    if not plan["narration_script"]:
        raise ValueError("The ChatGPT plan must contain narration_script.")

    scenes = plan.get("scenes")
    if not isinstance(scenes, list) or len(scenes) != 5:
        raise ValueError("The Motion explainer requires exactly five 2D scenes.")

    labels = (
        "THE HOOK",
        "THE BIG IDEA",
        "HOW IT WORKS",
        "THE DETAIL",
        "THE MUSICAL PAYOFF",
    )
    normalized_scenes = []
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise ValueError(f"Scene {index + 1} must be a JSON object.")
        item = dict(scene)
        item["caption"] = str(item.get("caption") or labels[index]).strip()[:72]
        item["graphic_label"] = str(
            item.get("graphic_label") or labels[index]
        ).strip()[:42]
        item["graphic_detail"] = str(
            item.get("graphic_detail")
            or item.get("caption")
            or plan["topic"]
        ).strip()[:110]
        normalized_scenes.append(item)
    plan["scenes"] = normalized_scenes

    # Do not carry the old source-audit and 3D asset fields into the new run.
    for key in (
        "sources",
        "source_group",
        "narration_evidence",
        "story_coherence",
        "date_check",
        "quality_control",
        "verified_sources",
        "model_asset",
        "asset_subject",
        "model_query",
        "frame_by_plane_backgrounds",
    ):
        plan.pop(key, None)

    return plan


def run_daily_plan(plan_path: Path) -> int:
    os.environ["MOTION_HYPERFRAMES_RENDER_ENABLED"] = "true"
    os.environ["BLENDER_RENDER_ENABLED"] = "false"
    os.environ["PUBLISH_ENABLED"] = "false"
    os.environ["YOUTUBE_PUBLISH_ENABLED"] = "false"

    plan_path = Path(plan_path)
    if not plan_path.is_file():
        raise FileNotFoundError(f"ChatGPT production plan was not found: {plan_path}")
    try:
        raw_plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError("ChatGPT production plan is not readable JSON.") from exc

    plan = normalize_production_plan(raw_plan)
    root = Path.cwd()
    work = root / "work"
    package = work / "package"
    output = work / "output"
    package.mkdir(parents=True, exist_ok=True)
    output.mkdir(parents=True, exist_ok=True)

    narration_path, narration_info = synthesize_voiceover(
        plan["narration_script"], output / "narration.wav"
    )
    narration_duration = float(narration_info.get("duration_seconds") or 0)
    if narration_duration <= 0:
        raise ValueError("Kokoro did not return a valid narration duration.")

    try:
        outro_hold = float(os.environ.get("MOTION_HYPERFRAMES_OUTRO_HOLD_SECONDS", "3"))
    except (TypeError, ValueError) as exc:
        raise ValueError("MOTION_HYPERFRAMES_OUTRO_HOLD_SECONDS must be numeric.") from exc
    if not 0 <= outro_hold <= 3:
        raise ValueError("The final scene hold must be between 0 and 3 seconds.")

    soundtrack_path, soundtrack_info = create_sampled_violin_bed(
        package / "soundtrack.wav",
        seed_text=plan["topic"] + " " + plan["title"],
        duration_seconds=max(24.0, narration_duration + outro_hold),
    )
    soundtrack_bytes = soundtrack_path.read_bytes()
    narration_bytes = narration_path.read_bytes()

    plan_file = package / "creative_plan.json"
    plan_file.write_text(
        json.dumps(plan, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (package / "narration.json").write_text(
        json.dumps(narration_info, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (package / "soundtrack.json").write_text(
        json.dumps(soundtrack_info, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    final_video = output / "violin-prince-explainer.mp4"
    video_quality = render_full_track(
        audio_bytes=soundtrack_bytes,
        audio_filename=soundtrack_path.name,
        output_path=final_video,
        work_dir=work / "motion-render-work",
        plan=plan,
        narration_bytes=narration_bytes,
        narration_info=narration_info,
    )
    if not final_video.is_file() or final_video.stat().st_size < 4096:
        raise MotionHyperFramesError(
            "Motion + HyperFrames did not preserve a valid explainer MP4."
        )

    digest = hashlib.sha256(final_video.read_bytes()).hexdigest()
    metadata = {
        "schema_version": 1,
        "status": "rendered",
        "render_engine": "motion_hyperframes",
        "production_type": "narrated_explainer",
        "title": plan["title"],
        "topic": plan["topic"],
        "narration": {
            "engine": narration_info.get("engine"),
            "voice": narration_info.get("voice"),
            "duration_seconds": narration_duration,
            "word_sync_status": narration_info.get("word_sync_status"),
            "word_timing_count": narration_info.get("word_timing_count"),
        },
        "video_quality": video_quality,
        "final_video": {
            "filename": final_video.name,
            "size_bytes": final_video.stat().st_size,
            "sha256": digest,
        },
        "publishing_status": "rendered",
        "publishing_enabled": False,
        "source_research": "not part of this production path",
        "three_dimensional_assets": "not used",
    }
    (output / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(
        "DAILY_PRODUCTION_RESULT="
        + json.dumps(
            {
                "status": "rendered",
                "video": str(final_video),
                "renderer": "motion_hyperframes",
                "duration_seconds": video_quality.get("duration_seconds"),
                "narration_engine": narration_info.get("engine"),
                "word_timing_count": narration_info.get("word_timing_count"),
                "sha256": digest,
                "publishing": "disabled",
            },
            ensure_ascii=False,
        ),
        flush=True,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render one ChatGPT-authored Violin Prince 2D explainer."
    )
    parser.add_argument(
        "--plan",
        required=True,
        help="Path to the ChatGPT-authored JSON production plan.",
    )
    args = parser.parse_args()
    try:
        result = run_daily_plan(Path(args.plan))
        final_video = Path("work/output/violin-prince-explainer.mp4")
        if result == 0 and (
            not final_video.is_file() or final_video.stat().st_size < 4096
        ):
            raise MotionHyperFramesError(
                "Final verification could not find the rendered explainer MP4."
            )
        return result
    except Exception as exc:
        print(
            "2D production stopped: " + str(exc)[:900],
            file=sys.stderr,
            flush=True,
        )
        return 1


if __name__ == "__main__":
    sys.exit(main())
