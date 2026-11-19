"""Approved editorial identity and deterministic fit checks for Violin Prince.

The creator has approved the channel format. Each story must pass its own
automated source, date, freshness, narration and channel-fit gates before
visual production proceeds; there is no repeated workflow approval checkbox.
"""
from __future__ import annotations

import re
from typing import Any

CREATIVE_DIRECTION_VERSION = "music-facts-premium-editorial-2d-v3"

CHANNEL_BRIEF = (
    "Violin Prince is a curiosity-driven music channel: real facts about the "
    "violin, instruments, acoustics, sound, melody, harmony, rhythm, song "
    "structure, music production and original violin covers, explained through "
    "premium illustrated music-documentary direction: tactile high-detail 2D art, "
    "cinematic lighting, controlled depth, precise motion graphics, editorial typography, "
    "narration-led pacing, refined transitions and the creator's own violin performance."
)

STORY_TYPES = {
    "violin_physics",
    "instrument_design",
    "sound_and_perception",
    "melody_and_composition",
    "song_anatomy",
    "music_production",
    "music_technology",
    "violin_cover_breakdown",
}

VISUAL_MODES = {
    "macro_illustration",
    "mechanism_illustration",
    "waveform",
    "melody_map",
    "comparison",
    "cover_performance",
}

BIOGRAPHY_PATTERNS = (
    re.compile(r"\bbiograph(?:y|ical)\b", re.I),
    re.compile(r"\bthe\s+(?:life|career|personal journey)\s+of\b", re.I),
    re.compile(r"\b(?:rise|fall)\s+of\s+(?:the\s+)?(?:violinist|musician|singer|composer|artist)\b", re.I),
    re.compile(r"\b(?:child|young|teenage|teen)\s+prodigy\b", re.I),
    re.compile(
        r"\b(?:wins?|won|winner of|crowned|named)\b.{0,70}\b"
        r"(?:competition|contest|prize|award|young musician)\b",
        re.I,
    ),
    re.compile(
        r"\b(?:violinist|musician|singer|composer|artist)\b.{0,70}\b"
        r"(?:wins?|won|winner|crowned|awarded|named)\b",
        re.I,
    ),
    re.compile(r"\bmeet\s+(?:the\s+)?[A-Z][\w'-]+\s+(?:violinist|musician|composer|singer)\b"),
)

VISUAL_MODE_PROMPTS = {
    "macro_illustration": (
        "Premium documentary macro: one tactile musical detail, painted wood grain, "
        "varnish highlights, crisp silhouette, layered depth and controlled warm light."
    ),
    "mechanism_illustration": (
        "Premium technical cutaway: accurate components, clear separation, fine brass "
        "callout rules, restrained teal signal paths and no invented measurements."
    ),
    "waveform": (
        "Elegant acoustic ribbons, travelling wavefronts, one luminous signal path, "
        "subtle depth and a clean technical grid grounded in the stated explanation."
    ),
    "melody_map": (
        "Original premium score map: clear pitch contours, rhythm markers and synchronized "
        "highlights. Do not reproduce copyrighted notation, lyrics or melodies."
    ),
    "comparison": (
        "Refined editorial comparison: matched scale, aligned baselines, brass and teal "
        "accents, generous spacing and balanced visual weight."
    ),
    "cover_performance": (
        "Premium illustrated payoff: complete violin and bow, expressive playing hands, "
        "dramatic diagonal, warm wood highlights and rich midnight shadows. No identifiable person."
    ),
}


def biography_reasons(plan: dict[str, Any]) -> list[str]:
    """Return biography/profile flags from the story's identity fields only."""
    identity = " ".join(
        str(plan.get(key) or "")
        for key in ("topic", "title", "hook")
    )
    return [
        pattern.pattern
        for pattern in BIOGRAPHY_PATTERNS
        if pattern.search(identity)
    ]


def validate_creative_plan(plan: dict[str, Any]) -> list[str]:
    """Validate that a sourced plan actually belongs to the approved channel."""
    if not isinstance(plan, dict):
        return ["The editorial plan must be a JSON object."]

    issues: list[str] = []
    story_type = str(plan.get("story_type") or "").strip().casefold()
    if story_type not in STORY_TYPES:
        issues.append(
            "story_type must be one of the approved music-fact categories: "
            + ", ".join(sorted(STORY_TYPES))
        )

    if not str(plan.get("topic") or "").strip() or not str(plan.get("title") or "").strip():
        issues.append("The story needs a specific music-centred topic and title.")

    flags = biography_reasons(plan)
    if flags:
        issues.append(
            "Individual-musician biographies, career profiles and competition-result "
            "stories are outside the approved Violin Prince format."
        )

    cover_payoff = str(plan.get("cover_payoff") or "").strip()
    if len(cover_payoff) < 20:
        issues.append(
            "cover_payoff must explain how an original Violin Prince violin phrase "
            "will demonstrate the fact, not merely sit underneath the narration."
        )

    scenes = plan.get("scenes")
    if not isinstance(scenes, list) or not 2 <= len(scenes) <= 4:
        issues.append("The approved format requires between two and four visual story beats.")
        return issues

    modes = []
    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            issues.append(f"Scene {index} must be a JSON object.")
            continue
        mode = str(scene.get("visual_mode") or "").strip().casefold()
        if mode not in VISUAL_MODES:
            issues.append(
                f"Scene {index} visual_mode must be one of: "
                + ", ".join(sorted(VISUAL_MODES))
            )
        else:
            modes.append(mode)
        if not str(scene.get("caption") or "").strip():
            issues.append(f"Scene {index} needs a concise caption.")
        if not str(scene.get("image_prompt") or "").strip():
            issues.append(f"Scene {index} needs a specific visual prompt.")

    if len(set(modes)) < 2:
        issues.append("The scenes need at least two distinct visual modes.")
    if scenes and isinstance(scenes[-1], dict):
        if str(scenes[-1].get("visual_mode") or "").strip().casefold() != "cover_performance":
            issues.append(
                f"Scene {len(scenes)} must deliver the musical payoff through a cover_performance insert."
            )

    return issues


def channel_fit_report(plan: dict[str, Any]) -> dict[str, Any]:
    """Create a machine-readable record of the channel-format review."""
    scenes = plan.get("scenes") if isinstance(plan.get("scenes"), list) else []
    modes = [
        str(scene.get("visual_mode") or "").strip().casefold()
        for scene in scenes if isinstance(scene, dict)
    ]
    issues = validate_creative_plan(plan)
    return {
        "version": CREATIVE_DIRECTION_VERSION,
        "status": "passed" if not issues else "blocked",
        "channel_brief": CHANNEL_BRIEF,
        "story_type": str(plan.get("story_type") or ""),
        "visual_modes": modes,
        "cover_payoff": str(plan.get("cover_payoff") or ""),
        "biography_flags": biography_reasons(plan),
        "issues": issues,
    }
