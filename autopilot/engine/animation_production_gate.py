"""Fail-closed gate for genuine animation-only video production.

A successful still-image render is not sufficient evidence for animation
production. This approval is created only after the real video-generation
route, shot-level video assets, motion verification and creator review pass.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class AnimationProductionGateError(RuntimeError):
    """Raised when the genuine-animation production path is not approved."""


def animation_production_blockers(
    approval_file: str | Path | None = None,
) -> list[str]:
    """Return specific blockers until real moving footage is verified."""
    path = Path(approval_file) if approval_file is not None else (
        Path(__file__).resolve().parent / "animation-production-approval.json"
    )
    try:
        approval = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return [
            "Animation-only production is locked: animation-production-approval.json "
            "is missing or invalid. Still-illustration videos cannot be used as a fallback."
        ]

    if not isinstance(approval, dict):
        return ["Animation production approval must be a JSON object."]

    blockers: list[str] = []
    if approval.get("schema_version") != 1:
        blockers.append("Animation production approval schema_version must be 1.")
    if approval.get("status") != "approved":
        blockers.append("A creator-approved genuine-animation production provider is required.")
    if approval.get("mode") != "animation_only":
        blockers.append("Animation production mode must be animation_only.")
    if not str(approval.get("provider") or "").strip():
        blockers.append("An actual video-generation provider must be named.")
    if approval.get("renderer") != "master_director_video":
        blockers.append("The approved renderer must be the shot-led Master Director video renderer.")
    if approval.get("static_image_fallback_allowed") is not False:
        blockers.append("Static-image fallback must be explicitly disabled.")

    evidence = approval.get("test_evidence")
    if not isinstance(evidence, dict):
        blockers.append("A successful genuine-animation test-evidence record is required.")
        evidence = {}
    if not isinstance(evidence.get("workflow_run_id"), int) or evidence.get("workflow_run_id", 0) <= 0:
        blockers.append("Animation test evidence must include a successful workflow_run_id.")
    if evidence.get("workflow_status") != "success":
        blockers.append("The animation-generation workflow test must have succeeded.")

    shot_count = evidence.get("director_shot_count")
    if not isinstance(shot_count, int) or not 8 <= shot_count <= 18:
        blockers.append("Animation evidence must cover the Master Director's 8–18 shot storyboard.")
        shot_count = 0
    for field in ("generated_video_asset_count", "downloaded_video_asset_count"):
        value = evidence.get(field)
        if not isinstance(value, int) or value != shot_count:
            blockers.append(f"Animation evidence {field} must match every storyboard shot.")
    if evidence.get("all_shots_have_video_assets") is not True:
        blockers.append("Every storyboard shot must have a downloaded video asset.")
    if evidence.get("actual_motion_verified") is not True:
        blockers.append("Frame analysis must verify actual subject/scene motion, not only camera zooms.")
    if evidence.get("static_image_only_shot_count") != 0:
        blockers.append("Static-image-only shots are not permitted in animation-only production.")
    coverage = evidence.get("motion_coverage")
    if not isinstance(coverage, (int, float)) or isinstance(coverage, bool) or coverage < 0.75:
        blockers.append("Verified moving-footage coverage must be at least 75 percent.")
    if evidence.get("final_video_verified") is not True:
        blockers.append("The final assembled animated MP4 must pass media verification.")

    review = approval.get("creator_review")
    if not isinstance(review, dict) or review.get("approved") is not True:
        blockers.append("The first genuine-animation sample must receive creator visual approval.")

    return blockers


def require_approved_animation_production(
    approval_file: str | Path | None = None,
) -> dict[str, Any]:
    """Raise before production or publication if the animation gate is closed."""
    path = Path(approval_file) if approval_file is not None else (
        Path(__file__).resolve().parent / "animation-production-approval.json"
    )
    blockers = animation_production_blockers(path)
    if blockers:
        raise AnimationProductionGateError("Genuine-animation production blocked: " + " ".join(blockers))
    return json.loads(path.read_text(encoding="utf-8"))
