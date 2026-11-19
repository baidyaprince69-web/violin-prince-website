"""Narration-aware composition and visual-beat direction for daily Shorts."""

from __future__ import annotations

import re
from typing import Any


SUPPORTED_GRAPHIC_TYPES = frozenset({
    "process_flow", "signal_path", "comparison", "arch_heights", "waveform",
})
_FLOW_TYPES = frozenset({"process_flow", "signal_path", "comparison", "arch_heights"})
_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "by", "for", "from", "how", "in",
    "into", "is", "it", "of", "on", "or", "the", "their", "this", "to",
    "with", "your", "then", "apply", "adjust",
}


class SceneDirectionError(ValueError):
    """Raised when a scene cannot be translated into a renderable visual plan."""


def _tokens(value: object) -> set[str]:
    return {
        token for token in re.findall(r"[a-z0-9]+", str(value or "").casefold())
        if len(token) > 2 and token not in _STOP_WORDS
    }


def _item_label(item: object) -> str:
    if isinstance(item, dict):
        return str(item.get("label") or item.get("display") or item.get("title") or "")
    return str(item or "")


def _scene_cues(
    narration_info: dict[str, Any],
    sentence_indexes: list[int],
) -> list[dict[str, Any]]:
    allowed = {int(value) for value in sentence_indexes}
    result = []
    for cue in narration_info.get("word_cues") or []:
        if not isinstance(cue, dict):
            continue
        try:
            start = float(cue.get("start"))
            sentence_index = int(cue.get("sentence_index"))
        except (TypeError, ValueError):
            continue
        if start >= 0 and sentence_index in allowed:
            result.append({**cue, "start": start, "sentence_index": sentence_index})
    return sorted(result, key=lambda value: value["start"])


def _graphic_reveal_times(
    items: list[object],
    cues: list[dict[str, Any]],
    *,
    scene_start: float,
    scene_duration: float,
) -> list[float]:
    """Map graphic steps to spoken label words, with evenly-spaced safe fallbacks."""
    used_cue_times: set[float] = set()
    reveals = []
    for index, item in enumerate(items):
        fallback = min(
            max(0.12, scene_duration - 0.35),
            0.24 + index * min(0.72, scene_duration / max(3, len(items) + 1)),
        )
        if isinstance(item, dict) and item.get("reveal_at") is not None:
            try:
                chosen = float(item["reveal_at"])
            except (TypeError, ValueError):
                chosen = fallback
        else:
            wanted = _tokens(_item_label(item))
            matches = []
            for cue in cues:
                cue_time = float(cue["start"])
                word = str(cue.get("text") or "").casefold()
                if cue_time in used_cue_times:
                    continue
                if word in wanted:
                    matches.append(cue_time)
            chosen = matches[0] - scene_start if matches else fallback
            if matches:
                used_cue_times.add(matches[0])
        reveals.append(round(max(0.08, min(max(0.12, scene_duration - 0.2), chosen)), 3))
    return reveals


def direct_scene_composition(
    plan: dict[str, Any],
    timeline: dict[str, Any],
    narration_info: dict[str, Any],
) -> dict[str, Any]:
    """Add per-scene layout, presenter placement and narration-timed graphic reveals.

    The presenter is deliberately not shown in every scene. When enabled, it
    appears in one explanatory scene with a real articulated gesture; other
    scenes remain full-frame visual scenes unless the plan explicitly requests
    a presenter action.
    """
    scenes = plan.get("scenes") or []
    if not isinstance(scenes, list):
        raise SceneDirectionError("The scene plan must contain a list of scenes.")

    timing_by_id = {
        str(item.get("scene_id") or ""): item
        for item in timeline.get("scenes") or []
        if isinstance(item, dict)
    }
    graphic_scenes = []
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise SceneDirectionError(f"Scene {index + 1} must be an object.")
        data = scene.get("graphic_data")
        if not data:
            continue
        if not isinstance(data, dict):
            raise SceneDirectionError(f"Scene {index + 1} graphic_data must be an object.")
        graphic_type = str(data.get("type") or "").strip().casefold()
        if graphic_type not in SUPPORTED_GRAPHIC_TYPES:
            raise SceneDirectionError(
                f"Scene {index + 1} uses unsupported motion graphic type: {graphic_type or '[missing]'}. "
                "Use process_flow, signal_path, comparison, arch_heights or waveform."
            )
        items = data.get("items") or []
        if graphic_type in _FLOW_TYPES and not 2 <= len(items) <= 4:
            raise SceneDirectionError(
                f"Scene {index + 1} {graphic_type} graphics require two to four items."
            )
        timing = timing_by_id.get(str(scene.get("id") or ""))
        if not timing:
            raise SceneDirectionError(f"Scene {index + 1} has no narration-aware timeline entry.")
        graphic_scenes.append((index, scene, data, timing))

    presenter_enabled = plan.get("use_violin_prince_presenter") is True
    presenter_candidate = None
    if presenter_enabled and graphic_scenes:
        # Put the presenter beside the most explanatory graphic, not on top of
        # decorative or performance plates. Prefer a process/signal diagram.
        ranked = sorted(
            graphic_scenes,
            key=lambda entry: (
                0 if str(entry[2].get("type") or "").casefold() in {"process_flow", "signal_path"} else 1,
                entry[0],
            ),
        )
        presenter_candidate = ranked[0][0]

    report_scenes = []
    for index, scene in enumerate(scenes):
        timing = timing_by_id[str(scene.get("id") or "")]
        scene_start = float(timing.get("start") or 0)
        scene_duration = float(timing.get("duration") or timing.get("clip_duration") or 1)
        actions = scene.get("character_actions") or {}
        if not isinstance(actions, dict):
            raise SceneDirectionError(f"Scene {index + 1} character_actions must be an object.")

        data = scene.get("graphic_data")
        layout = "full_bleed"
        if isinstance(data, dict):
            is_presenter_scene = index == presenter_candidate
            layout = "graphic_left_presenter_right" if is_presenter_scene else "graphic_full"
            items = data.get("items") or []
            cues = _scene_cues(
                narration_info,
                list(timing.get("narration_sentence_indexes") or []),
            )
            reveal_times = _graphic_reveal_times(
                items,
                cues,
                scene_start=scene_start,
                scene_duration=scene_duration,
            ) if items else []
            normalised_items = []
            for item_index, item in enumerate(items):
                value = dict(item) if isinstance(item, dict) else {"label": str(item)}
                value["reveal_at"] = reveal_times[item_index]
                value.setdefault("reveal_duration", 0.52)
                normalised_items.append(value)
            if items:
                data["items"] = normalised_items
            data["animation_timing"] = "narration_word_cues_with_even_spacing_fallback"
            scene["graphic_data"] = data

            scene["visual_composition"] = {
                "layout": layout,
                "graphic_area": "left_column" if is_presenter_scene else "full_canvas",
                "presenter_area": "right_column" if is_presenter_scene else "none",
                "safe_margin_percent": 6,
            }

            if is_presenter_scene and "violin-prince" not in actions:
                actions["violin-prince"] = {
                    "visible": True,
                    "x": 372,
                    "y": 155,
                    "scale": 0.48,
                    "start_offset": 0.18,
                    "duration": max(1.0, scene_duration - 0.18),
                    "gesture": "point_left",
                    "expression": "speaking",
                }
        else:
            scene.setdefault("visual_composition", {
                "layout": "full_bleed",
                "graphic_area": "none",
                "presenter_area": "none",
                "safe_margin_percent": 6,
            })

        if "violin-prince" not in actions:
            actions["violin-prince"] = {"visible": False}
        scene["character_actions"] = actions
        visible = actions.get("violin-prince", {}).get("visible") is not False
        report_scenes.append({
            "scene_id": str(scene.get("id") or ""),
            "layout": layout,
            "graphic_type": str((data or {}).get("type") or "") if isinstance(data, dict) else "",
            "graphic_item_count": len((data or {}).get("items") or []) if isinstance(data, dict) else 0,
            "presenter_visible": bool(visible),
            "presenter_gesture": str(
                actions.get("violin-prince", {}).get("gesture") or ""
            ),
        })

    report = {
        "status": "directed",
        "presenter_enabled": presenter_enabled,
        "presenter_scene_id": (
            str(scenes[presenter_candidate].get("id") or "")
            if presenter_candidate is not None else ""
        ),
        "scenes": report_scenes,
        "rules": [
            "presenter is not a global overlay",
            "graphic items reveal on matched narration words when available",
            "portrait explainer composition reserves a separate presenter column",
            "one dominant focal point per scene with deliberate caption-safe space",
            "graphic scenes must be animated by the Motion renderer",
        ],
    }
    plan["visual_direction_report"] = report
    return report
