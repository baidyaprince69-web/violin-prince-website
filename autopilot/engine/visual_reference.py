"""Reference-informed visual direction for the Violin Prince short renderer.

This module adapts high-level visual craft from an analysed reference into the
existing Pillow/FFmpeg pipeline. It does not download reference media, copy
assets, or claim to generate AI video clips. All accepted controls are bounded
and deterministic so an optional reference cannot silently change the renderer.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse


VISUAL_LANGUAGES = {
    "cinematic_cgi": (
        "Sculptural photorealistic 3D-CGI depth, tactile instrument materials, "
        "directional volumetric light and a clear foreground-to-background hierarchy."
    ),
    "macro_documentary": (
        "Naturalistic macro cinematography, believable optical perspective, "
        "shallow depth of field and carefully observed physical details."
    ),
    "kinetic_graphics": (
        "A dimensional explainer composition with clear geometric hierarchy, "
        "purposeful graphic rhythm and negative space around the main subject."
    ),
    "hybrid": (
        "Combine photorealistic instrument imagery with crisp dimensional "
        "explanatory elements while keeping one coherent cinematic composition."
    ),
}

SHOT_TYPES = {
    "extreme_macro": "Extreme macro framing that reveals one tactile physical detail.",
    "macro": "Tight macro framing with the main musical object filling the composition.",
    "mechanism_cutaway": "A close scientific cutaway that makes the real mechanism legible.",
    "close_detail": "A close detail shot with a single unmistakable focal subject.",
    "overhead": "A clean overhead composition with a readable arrangement of components.",
    "split_wide": "A balanced wide comparison with matching scale and lighting on both sides.",
    "performance_close": "A cinematic close performance composition around the violin, bow and hands.",
    "wide_hero": "A spacious hero composition with strong depth and one clear focal subject.",
}

CAMERA_MOVES = {"locked", "pan_left", "pan_right", "pan_up", "pan_down"}
TRANSITIONS = {
    "crossfade": "fade",
    "wipe_left": "wipeleft",
    "wipe_right": "wiperight",
    "smooth_left": "smoothleft",
    "fade_through_black": "fadeblack",
}

PACE_TRANSITION_SECONDS = {
    "rapid": 0.20,
    "dynamic": 0.27,
    "steady": 0.35,
    "slow": 0.48,
}

_DEFAULT_SHOT_BY_MODE = {
    "macro_3d": "extreme_macro",
    "mechanism_3d": "mechanism_cutaway",
    "waveform": "close_detail",
    "melody_map": "overhead",
    "comparison": "split_wide",
    "cover_performance": "performance_close",
}


def _enum(value: Any, allowed: set[str], field: str, default: str) -> str:
    result = str(value or default).strip().casefold()
    if result not in allowed:
        raise ValueError(
            f"visual_reference.{field} must be one of: {', '.join(sorted(allowed))}."
        )
    return result


def _short_text(value: Any, field: str, limit: int) -> str:
    text = " ".join(str(value or "").split()).strip()
    if len(text) > limit:
        raise ValueError(f"visual_reference.{field} must be {limit} characters or fewer.")
    return text


def normalize_visual_reference(
    value: Any,
    scenes: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    """Validate and normalize the optional ChatGPT-authored reference analysis.

    The model analyses a supplied reference and passes only bounded production
    controls. The engine never downloads or reproduces the reference itself.
    """
    if value is None or value == {}:
        return None
    if not isinstance(value, dict):
        raise ValueError("visual_reference must be a JSON object.")

    source_url = _short_text(value.get("source_url"), "source_url", 400)
    if source_url:
        parsed = urlparse(source_url)
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
            raise ValueError("visual_reference.source_url must be a safe HTTPS URL.")

    motion_profile = _enum(
        value.get("motion_profile"),
        {"video_clips", "animated_stills", "mixed", "static"},
        "motion_profile",
        "animated_stills",
    )
    visual_language = _enum(
        value.get("visual_language"),
        set(VISUAL_LANGUAGES),
        "visual_language",
        "cinematic_cgi",
    )
    pacing = _enum(
        value.get("pacing"),
        set(PACE_TRANSITION_SECONDS),
        "pacing",
        "steady",
    )
    summary = _short_text(value.get("reference_summary"), "reference_summary", 320)

    supplied_guidance = value.get("scene_guidance")
    if supplied_guidance is not None:
        if not isinstance(supplied_guidance, list) or len(supplied_guidance) != 3:
            raise ValueError("visual_reference.scene_guidance must contain exactly three scene objects.")
    else:
        supplied_guidance = [{}, {}, {}]

    scene_list = scenes if isinstance(scenes, list) else []
    normalized_guidance: list[dict[str, str]] = []
    for index in range(3):
        supplied = supplied_guidance[index]
        if not isinstance(supplied, dict):
            raise ValueError(f"visual_reference.scene_guidance[{index}] must be an object.")
        scene_mode = ""
        if index < len(scene_list) and isinstance(scene_list[index], dict):
            scene_mode = str(scene_list[index].get("visual_mode") or "").strip().casefold()
        default_shot = _DEFAULT_SHOT_BY_MODE.get(scene_mode, "close_detail")
        normalized_guidance.append({
            "shot_type": _enum(
                supplied.get("shot_type"), set(SHOT_TYPES),
                f"scene_guidance[{index}].shot_type", default_shot,
            ),
            "camera_move": _enum(
                supplied.get("camera_move"), CAMERA_MOVES,
                f"scene_guidance[{index}].camera_move", "locked",
            ),
            "transition_out": _enum(
                supplied.get("transition_out"), set(TRANSITIONS),
                f"scene_guidance[{index}].transition_out", "crossfade",
            ),
        })

    adaptation_note = ""
    if motion_profile in {"video_clips", "mixed"}:
        adaptation_note = (
            "The reference contains real moving video clips. This production path "
            "currently uses generated still scene plates plus deterministic animated "
            "overlays; it does not generate new AI video clips. The reference's broad "
            "visual rhythm is adapted without claiming equivalent clip motion."
        )
    elif motion_profile == "static":
        adaptation_note = (
            "The reference is primarily static imagery. The production uses still "
            "scene plates with the existing word-synchronised graphic animation."
        )
    else:
        adaptation_note = (
            "The reference is primarily animated stills. The production uses still "
            "scene plates with the existing word-synchronised graphic animation."
        )

    return {
        "schema_version": 1,
        "source_url": source_url,
        "reference_summary": summary,
        "motion_profile": motion_profile,
        "visual_language": visual_language,
        "pacing": pacing,
        "scene_guidance": normalized_guidance,
        "transition_seconds": PACE_TRANSITION_SECONDS[pacing],
        "adaptation_note": adaptation_note,
        "originality_rule": (
            "Use abstract craft principles only. Create original Violin Prince "
            "compositions; do not reproduce exact frames, layouts, text, logos, "
            "music, assets, or another creator's identity."
        ),
    }


def validate_visual_reference(
    value: Any,
    scenes: list[dict[str, Any]] | None = None,
) -> list[str]:
    """Return validation issues without throwing."""
    try:
        normalize_visual_reference(value, scenes)
    except (TypeError, ValueError) as exc:
        return [str(exc)]
    return []


def scene_visual_prompt_suffix(plan: dict[str, Any] | None, index: int) -> str:
    """Return a compact, safe prompt addition for one scene."""
    profile = (plan or {}).get("visual_reference")
    if not isinstance(profile, dict):
        return ""
    guidance = profile.get("scene_guidance", [])
    if not isinstance(guidance, list) or index < 0 or index >= len(guidance):
        return ""
    scene = guidance[index]
    if not isinstance(scene, dict):
        return ""
    visual_language = VISUAL_LANGUAGES.get(str(profile.get("visual_language") or ""), "")
    shot = SHOT_TYPES.get(str(scene.get("shot_type") or ""), "")
    if not visual_language and not shot:
        return ""
    return (
        " Reference-informed treatment: " + visual_language + " " + shot + " "
        + str(profile.get("originality_rule") or "")
    )


def scene_camera_move(plan: dict[str, Any] | None, index: int) -> str:
    profile = (plan or {}).get("visual_reference")
    guidance = profile.get("scene_guidance", []) if isinstance(profile, dict) else []
    if isinstance(guidance, list) and 0 <= index < len(guidance):
        scene = guidance[index]
        if isinstance(scene, dict):
            move = str(scene.get("camera_move") or "locked")
            if move in CAMERA_MOVES:
                return move
    return "locked"


def scene_transition(plan: dict[str, Any] | None, index: int) -> str:
    profile = (plan or {}).get("visual_reference")
    guidance = profile.get("scene_guidance", []) if isinstance(profile, dict) else []
    if isinstance(guidance, list) and 0 <= index < len(guidance):
        scene = guidance[index]
        if isinstance(scene, dict):
            transition = str(scene.get("transition_out") or "crossfade")
            return TRANSITIONS.get(transition, "fade")
    return "fade"


def transition_duration(plan: dict[str, Any] | None) -> float:
    profile = (plan or {}).get("visual_reference")
    if isinstance(profile, dict):
        try:
            value = float(profile.get("transition_seconds", 0.35))
            return min(0.50, max(0.18, value))
        except (TypeError, ValueError):
            pass
    return 0.35
