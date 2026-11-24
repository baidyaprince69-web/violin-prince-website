"""Scheduled daily orchestration for the procedural Master Director renderer.

The scheduled path renders native Motion/HyperFrames scenes. It deliberately
refuses still-image fallbacks and requires a hash-pinned, creator-approved
presenter rig before production. Real Performance remains blocked until the
full-body violin/bow rig and its recording synchronisation are approved.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Callable

from copilot_director_provider import generate_director_plan
from master_creative_director import (
    DIRECTOR_CONTRACT_VERSION,
    DirectorPlanError,
    require_valid_director_plan,
)
from hyperframes_pipeline import render_master_director_video


class ProceduralDailyRenderError(RuntimeError):
    """Raised when a daily story cannot be safely rendered procedurally."""


SLOT_CREATIVE_DIRECTION: dict[str, dict[str, str]] = {
    "music-secrets": {
        "category": "music science and listening",
        "direction": "Explain one verified musical or auditory-science idea through clear animated mechanisms and visual reveals.",
        "presenter_role": "curious science host who speaks, explains, listens and demonstrates",
    },
    "production-tech": {
        "category": "music production technology",
        "direction": "Demonstrate the verified studio tool or production technique with animated signal paths, controls and cause/effect.",
        "presenter_role": "studio presenter who explains and demonstrates the technical process",
    },
    "melody-stories": {
        "category": "cinematic music storytelling",
        "direction": "Tell the verified musical story with emotional pacing, cinematic environments and original visual metaphors.",
        "presenter_role": "storytelling host who listens, reacts and guides the viewer through the musical story",
    },
    "real-performance": {
        "category": "creator violin performance",
        "direction": "Use the creator's actual violin recording and the approved full-body violin/bow performance rig.",
        "presenter_role": "full-body violin performer synchronized to the creator's actual performance",
    },
}


def rig_bundle_sha256(rig_bundle_dir: str | Path) -> str:
    """Hash every production rig file except the approval record itself."""
    root = Path(rig_bundle_dir).expanduser().resolve(strict=True)
    digest = hashlib.sha256()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    included = [path for path in files if path.name != "production-approval.json"]
    if not included:
        raise ProceduralDailyRenderError("The presenter rig bundle contains no source assets.")
    for path in included:
        if path.is_symlink():
            raise ProceduralDailyRenderError("Symlinks are not permitted inside the production presenter bundle.")
        relative = path.relative_to(root).as_posix()
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def require_approved_presenter_rig(
    rig_bundle_dir: str | Path,
    *,
    slot_id: str,
) -> dict[str, Any]:
    """Require creator review and an approval pinned to the exact rig bytes."""
    if slot_id == "real-performance":
        raise ProceduralDailyRenderError(
            "Real Performance is not production-ready: it requires PR #130's completed "
            "full-body rig, independently approved violin/bow props and note-synchronised "
            "performance animation. The current daily procedural renderer only supports "
            "the upper-body presenter rig."
        )
    if slot_id not in {"music-secrets", "production-tech", "melody-stories"}:
        raise ProceduralDailyRenderError(f"Unsupported daily content slot: {slot_id!r}.")

    root = Path(rig_bundle_dir).expanduser().resolve()
    spec_path = root / "character.json"
    separation_path = root / "separation-report.json"
    approval_path = root / "production-approval.json"
    for path, label in (
        (spec_path, "character specification"),
        (separation_path, "character separation report"),
        (approval_path, "creator production approval"),
    ):
        if not path.is_file():
            raise ProceduralDailyRenderError(
                f"Production presenter gate is closed: missing {label} ({path.name})."
            )

    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        separation = json.loads(separation_path.read_text(encoding="utf-8"))
        approval = json.loads(approval_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProceduralDailyRenderError("The presenter rig or its approval record is unreadable JSON.") from exc

    if not isinstance(spec, dict) or spec.get("id") != "violin-prince":
        raise ProceduralDailyRenderError("The approved presenter bundle must preserve the canonical Violin Prince character.")
    if not isinstance(separation, dict) or separation.get("character_id") != "violin-prince":
        raise ProceduralDailyRenderError("The presenter separation report does not match the canonical character.")
    if not isinstance(approval, dict) or approval.get("schema_version") != 1:
        raise ProceduralDailyRenderError("Presenter production approval must use schema_version 1.")
    if approval.get("status") != "approved" or approval.get("creator_approved") is not True:
        raise ProceduralDailyRenderError("The presenter has not received creator production approval.")

    try:
        actual_digest = rig_bundle_sha256(root)
    except (OSError, RuntimeError) as exc:
        raise ProceduralDailyRenderError("The presenter bundle could not be securely fingerprinted.") from exc
    if approval.get("bundle_sha256") != actual_digest:
        raise ProceduralDailyRenderError(
            "Presenter approval does not match the current source assets; visual approval must be renewed."
        )

    slots = approval.get("approved_slots")
    if not isinstance(slots, list) or slot_id not in slots:
        raise ProceduralDailyRenderError(f"The presenter approval does not include the {slot_id!r} content slot.")

    review = approval.get("review")
    required_review = (
        "source_artwork_preserved",
        "face_and_head_alignment_reviewed",
        "arm_joint_alignment_reviewed",
        "hand_articulation_reviewed",
        "occlusion_reviewed",
        "motion_preview_reviewed",
    )
    if not isinstance(review, dict) or any(review.get(field) is not True for field in required_review):
        raise ProceduralDailyRenderError(
            "Presenter visual approval is incomplete: source alignment, joints, hands, occlusion "
            "and the moving preview must all be reviewed."
        )

    return {
        "status": "approved",
        "character_id": "violin-prince",
        "bundle_sha256": actual_digest,
        "approval_sha256": hashlib.sha256(approval_path.read_bytes()).hexdigest(),
        "approved_slots": list(slots),
    }


def creator_preferences_for_slot(slot_id: str) -> dict[str, Any]:
    """Keep the same presenter identity while changing the direction by category."""
    direction = SLOT_CREATIVE_DIRECTION.get(slot_id)
    if direction is None:
        raise ProceduralDailyRenderError(f"Unsupported daily content slot: {slot_id!r}.")
    return {
        "canonical_character": "Violin Prince",
        "character_identity_must_remain_consistent": True,
        "visual_medium": "real-time procedural 2D animation with independently moving scene objects and an articulated presenter",
        "static_image_slideshows_allowed": False,
        "category": direction["category"],
        "category_direction": direction["direction"],
        "presenter_role": direction["presenter_role"],
        "style": "cinematic, story-specific, layered depth, deliberate camera movement, polished kinetic typography",
        "format": "vertical 720x1280 YouTube Short",
    }


def _director_story_context(
    plan: dict[str, Any],
    verified_sources: list[dict[str, Any]],
    beat_analysis: dict[str, Any] | None,
) -> dict[str, Any]:
    slot_id = str(plan.get("slot_id") or "")
    direction = SLOT_CREATIVE_DIRECTION.get(slot_id)
    if direction is None:
        raise ProceduralDailyRenderError(f"Unknown canonical content slot: {slot_id!r}.")
    return {
        "topic": str(plan.get("topic") or plan.get("core_claim") or ""),
        "title": str(plan.get("title") or ""),
        "hook": str(plan.get("hook") or ""),
        "core_claim": str(plan.get("core_claim") or ""),
        "narration_script": str(plan.get("narration_script") or ""),
        "verified_sources": verified_sources,
        "target_duration_seconds": plan.get("target_duration_seconds") or 32,
        "slot_id": slot_id,
        "content_category": direction["category"],
        "audio_timing": beat_analysis or {},
    }


def render_procedural_daily_video(
    engine: Any,
    plan: dict[str, Any],
    verified_sources: list[dict[str, Any]],
    audio_path: str | Path,
    narration_path: str | Path,
    narration_info: dict[str, Any],
    *,
    beat_analysis: dict[str, Any] | None = None,
    rig_bundle_dir: str | Path | None = None,
    director_output_dir: str | Path | None = None,
    director_generator: Callable[..., dict[str, Any]] | None = None,
    render_function: Callable[..., dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Direct and render a daily Short with no generated scene-image fallback."""
    slot_id = str(plan.get("slot_id") or "")
    preferences = creator_preferences_for_slot(slot_id)
    bundle = Path(rig_bundle_dir or (
        Path(__file__).resolve().parent / "assets" / "characters" / "violin-prince-rig"
    )).expanduser().resolve()
    rig_approval = require_approved_presenter_rig(bundle, slot_id=slot_id)

    if not str(plan.get("narration_script") or "").strip():
        raise ProceduralDailyRenderError("Procedural production requires the validated narration script.")
    if not isinstance(verified_sources, list) or len(verified_sources) < 2:
        raise ProceduralDailyRenderError("Procedural production requires at least two verified publisher sources.")

    generator = director_generator or generate_director_plan
    renderer = render_function or render_master_director_video
    story_context = _director_story_context(plan, verified_sources, beat_analysis)
    try:
        director_plan = generator(story_context, creator_preferences=preferences)
        require_valid_director_plan(director_plan)
    except (DirectorPlanError, ValueError, RuntimeError) as exc:
        raise ProceduralDailyRenderError("Master Creative Director did not produce a valid plan: " + str(exc)) from exc

    if director_plan.get("render_mode") != "procedural_2d":
        raise ProceduralDailyRenderError("Daily production accepts procedural_2d plans only; image/slideshow plans are rejected.")
    provider = director_plan.get("_director_provider")
    if not isinstance(provider, dict) or provider.get("contract_version") != DIRECTOR_CONTRACT_VERSION:
        raise ProceduralDailyRenderError("Master Creative Director provider metadata does not match the active contract.")

    production_date = str(plan.get("production_date") or "")
    director_plan["production_context"] = {
        "production_date": production_date,
        "slot_id": slot_id,
        "production_identity": production_date + ":" + slot_id,
        "original_title": str(plan.get("title") or ""),
        "topic": str(plan.get("topic") or ""),
        "narration_script": str(plan.get("narration_script") or ""),
        "source_ids": [str(item.get("source_id") or "") for item in verified_sources if isinstance(item, dict)],
        "source_publishers": sorted({
            str(item.get("publisher_domain") or "")
            for item in verified_sources
            if isinstance(item, dict) and item.get("publisher_domain")
        }),
        "audio_timing": beat_analysis or {},
        "presenter_rig": rig_approval,
        "research_gate": "passed_existing_two_publisher_quote_narration_and_story_coherence_checks",
    }

    artifact_dir = Path(director_output_dir or (Path(engine.PACKAGE) / "master-director")).expanduser().resolve()
    artifact_dir.mkdir(parents=True, exist_ok=True)
    director_path = artifact_dir / "master-director-plan.json"
    temporary = director_path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(director_plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(director_path)

    output_video = Path(engine.OUT).resolve() / "violin-prince-short.mp4"
    project_dir = Path(engine.WORK).resolve() / "master-director-composition"
    try:
        report = renderer(
            engine,
            director_plan,
            [],
            Path(audio_path),
            Path(narration_path),
            narration_info,
            project_dir=project_dir,
            output_video=output_video,
            rig_bundle_dir=bundle,
            production_mode=True,
        )
    except Exception as exc:
        raise ProceduralDailyRenderError("Procedural Master Director rendering failed: " + str(exc)) from exc

    if not isinstance(report, dict) or report.get("status") != "passed":
        raise ProceduralDailyRenderError("The procedural Master Director render did not pass its final QA report.")
    if report.get("render_mode") != "procedural_2d":
        raise ProceduralDailyRenderError("The final render did not use the required procedural_2d renderer.")
    motion = report.get("motion_report")
    shots = director_plan["storyboard"]["shots"]
    shot_count = len(shots)
    if not isinstance(motion, dict) or motion.get("status") != "passed":
        raise ProceduralDailyRenderError("The final render has no successful Motion animation report.")
    if int(report.get("shot_count") or 0) != shot_count:
        raise ProceduralDailyRenderError("The rendered shot count does not match the approved Director storyboard.")
    if int(motion.get("animated_stagecraft_scene_count") or 0) != shot_count:
        raise ProceduralDailyRenderError("Every Director shot must contain its own independently animated environment.")
    if int(motion.get("animated_stagecraft_object_count") or 0) < shot_count * 2:
        raise ProceduralDailyRenderError("Every Director shot must contain at least two moving authored objects.")
    if int(motion.get("animated_presenter_count") or 0) < 3:
        raise ProceduralDailyRenderError("At least three shots must contain an articulated Violin Prince presenter.")
    if int(motion.get("rendered_layer_count") or 0) != 0:
        raise ProceduralDailyRenderError("Procedural daily production must not contain generated still-image layers.")

    final_qa = report.get("final_video_qa")
    if not isinstance(final_qa, dict) or final_qa.get("status") != "passed":
        raise ProceduralDailyRenderError("The final assembled MP4 did not pass independent media verification.")
    if not output_video.is_file() or output_video.stat().st_size < 150000:
        raise ProceduralDailyRenderError("The final procedural MP4 is missing or unexpectedly small.")

    manifest_shots = []
    for shot in shots:
        environment = shot.get("procedural_scene") or {}
        manifest_shots.append({
            "shot_id": str(shot.get("id") or ""),
            "start_seconds": shot.get("start_seconds"),
            "end_seconds": shot.get("end_seconds"),
            "environment": str(environment.get("environment") or ""),
            "animated_object_count": len(environment.get("objects") or []),
            "character_visible": bool((shot.get("character_action") or {}).get("visible")),
        })
    plan["procedural_director_manifest"] = {
        "render_mode": "procedural_2d",
        "shot_count": shot_count,
        "rendered_layer_count": 0,
        "shots": manifest_shots,
        "motion_report": motion,
        "presenter_rig": rig_approval,
        "master_director_plan": str(director_path),
    }

    enriched_report = {
        **report,
        "render_mode": "procedural_2d",
        "status": "passed",
        "width": final_qa["width"],
        "height": final_qa["height"],
        "video_codec": final_qa["video_codec"],
        "audio_sample_rate": final_qa["audio_sample_rate"],
        "fps": final_qa["fps"],
        "duration_seconds": final_qa["duration_seconds"],
        "character_count": 1,
        "character_rigging": "creator-approved, hash-pinned Violin Prince articulated presenter rig",
        "presenter_rig_approval": rig_approval,
        "publish_ready": True,
        "output": str(output_video),
    }
    report_path = output_video.parent / "master-director-render-report.json"
    report_path.write_text(json.dumps(enriched_report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (artifact_dir / "procedural-stagecraft-brief.json").write_text(
        json.dumps(plan["procedural_director_manifest"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return enriched_report
