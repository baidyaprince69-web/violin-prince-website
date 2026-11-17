"""Stable scene identity, safe scene operations, and narration-aware timing."""
from __future__ import annotations

import copy
import hashlib
import json
import re
from typing import Any

SCENE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
EDITABLE_SCENE_FIELDS = frozenset({
    "title", "caption", "image_prompt", "visual_mode", "graphic_label",
    "graphic_detail", "graphic_data", "character_actions", "transition",
    "narration_sentence_indexes", "music_only",
})


class ScenePlanError(ValueError):
    """Raised when a scene edit would break stable identity or narration mapping."""


def split_narration_sentences(text: str) -> list[str]:
    normalised = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalised:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", normalised) if part.strip()]


def _stable_scene_id(scene: dict[str, Any], index: int) -> str:
    label = str(scene.get("title") or scene.get("caption") or f"scene-{index + 1}")
    slug = re.sub(r"[^a-z0-9]+", "-", label.casefold()).strip("-")[:32] or f"scene-{index + 1}"
    identity = {
        key: scene.get(key)
        for key in ("title", "caption", "image_prompt", "visual_mode")
        if scene.get(key) is not None
    }
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()[:8]
    return f"{slug}-{digest}"


def _partition_sentence_indexes(scene_count: int, sentence_count: int) -> list[list[int]]:
    if scene_count < 1 or sentence_count < scene_count:
        raise ScenePlanError(
            f"{scene_count} scenes cannot be mapped to {sentence_count} narration sentences; "
            "use fewer scenes or add verified narration sentences."
        )
    quotient, remainder = divmod(sentence_count, scene_count)
    result: list[list[int]] = []
    cursor = 0
    for index in range(scene_count):
        count = quotient + (1 if index < remainder else 0)
        result.append(list(range(cursor, cursor + count)))
        cursor += count
    return result


def _normalise_scene_ids(
    scenes: list[dict[str, Any]],
    *,
    assign_legacy_asset_names: bool = True,
) -> None:
    used: set[str] = set()
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise ScenePlanError(f"Scene {index + 1} must be an object.")
        raw = str(scene.get("id") or "").strip().casefold()
        if not raw and assign_legacy_asset_names:
            scene.setdefault("_legacy_asset_filename", f"scene-{index + 1}.jpg")
        scene_id = raw or _stable_scene_id(scene, index)
        if not SCENE_ID.fullmatch(scene_id):
            raise ScenePlanError(f"Invalid scene id {scene_id!r}; use lowercase letters, numbers, '-' or '_'.")
        if scene_id in used:
            if raw:
                raise ScenePlanError(f"Duplicate scene id: {scene_id}")
            suffix = 2
            candidate = f"{scene_id}-{suffix}"
            while candidate in used:
                suffix += 1
                candidate = f"{scene_id}-{suffix}"
            scene_id = candidate
        scene["id"] = scene_id
        used.add(scene_id)


def _validate_narration_mapping(scenes: list[dict[str, Any]], sentence_count: int) -> None:
    assigned: list[int] = []
    for scene in scenes:
        values = scene.get("narration_sentence_indexes")
        if values is None:
            raise ScenePlanError(f"Scene {scene['id']} has no narration sentence mapping.")
        if not isinstance(values, list):
            raise ScenePlanError(f"Scene {scene['id']} narration_sentence_indexes must be an array.")
        indexes: list[int] = []
        for value in values:
            if isinstance(value, bool) or not isinstance(value, int):
                raise ScenePlanError(f"Scene {scene['id']} has a non-integer narration sentence index.")
            if value < 0 or value >= sentence_count:
                raise ScenePlanError(f"Scene {scene['id']} refers to missing narration sentence {value}.")
            indexes.append(value)
        if len(indexes) != len(set(indexes)):
            raise ScenePlanError(f"Scene {scene['id']} repeats a narration sentence.")
        if not indexes and scene.get("music_only") is not True:
            raise ScenePlanError(
                f"Scene {scene['id']} has no narration. Mark it music_only=true explicitly."
            )
        assigned.extend(indexes)
    if len(assigned) != len(set(assigned)):
        raise ScenePlanError("A narration sentence is assigned to more than one scene.")
    missing = sorted(set(range(sentence_count)) - set(assigned))
    if missing:
        raise ScenePlanError(
            "Scene edits left narration sentences unmapped: " + ", ".join(str(item) for item in missing)
        )


def apply_scene_operations(
    plan: dict[str, Any],
    narration_script: str | None = None,
    *,
    minimum_scenes: int = 2,
    maximum_scenes: int = 4,
) -> dict[str, Any]:
    """Apply explicit insert/delete/update/reorder operations without editing narration."""
    if not isinstance(plan, dict):
        raise ScenePlanError("A daily scene plan must be an object.")
    result = copy.deepcopy(plan)
    scenes = result.get("scenes")
    if not isinstance(scenes, list):
        raise ScenePlanError("A daily scene plan must contain a scenes array.")
    _normalise_scene_ids(scenes)

    sentences = split_narration_sentences(narration_script or result.get("narration_script", ""))
    sentence_count = len(sentences)
    if sentence_count < minimum_scenes:
        raise ScenePlanError("There are too few verified narration sentences for the requested scene count.")

    # Older three-scene plans receive a deterministic mapping once. Existing
    # explicit mappings are kept, including across reorder operations.
    if all(scene.get("narration_sentence_indexes") is None for scene in scenes):
        partitions = _partition_sentence_indexes(len(scenes), sentence_count)
        for scene, indexes in zip(scenes, partitions):
            scene["narration_sentence_indexes"] = indexes
    elif any(scene.get("narration_sentence_indexes") is None for scene in scenes):
        missing_scenes = [scene for scene in scenes if scene.get("narration_sentence_indexes") is None]
        already = {
            value
            for scene in scenes
            for value in (scene.get("narration_sentence_indexes") or [])
            if isinstance(value, int) and not isinstance(value, bool)
        }
        free = [value for value in range(sentence_count) if value not in already]
        partitions = _partition_sentence_indexes(len(missing_scenes), len(free))
        for scene, partition in zip(missing_scenes, partitions):
            scene["narration_sentence_indexes"] = [free[index] for index in partition]

    operations = result.pop("scene_operations", [])
    if operations is None:
        operations = []
    if not isinstance(operations, list):
        raise ScenePlanError("scene_operations must be an array.")
    audit: list[dict[str, Any]] = []

    for op_index, operation in enumerate(operations, start=1):
        if not isinstance(operation, dict):
            raise ScenePlanError(f"Scene operation {op_index} must be an object.")
        kind = str(operation.get("type") or "").strip().casefold()
        scene_id = str(operation.get("scene_id") or "").strip().casefold()
        positions = {scene["id"]: index for index, scene in enumerate(scenes)}

        if kind == "insert":
            scene = copy.deepcopy(operation.get("scene"))
            if not isinstance(scene, dict):
                raise ScenePlanError(f"Insert operation {op_index} requires a scene object.")
            _normalise_scene_ids([scene], assign_legacy_asset_names=False)
            scene["_visual_asset_invalidated"] = True
            if scene["id"] in positions:
                raise ScenePlanError(f"Insert operation repeats scene id {scene['id']}.")
            if "narration_sentence_indexes" not in scene:
                raise ScenePlanError("Inserted scenes must explicitly map narration_sentence_indexes or be music_only.")
            if not scene.get("caption") or not scene.get("image_prompt"):
                raise ScenePlanError("Inserted scenes require a caption and image_prompt.")
            if operation.get("before_scene_id"):
                anchor = str(operation["before_scene_id"]).strip().casefold()
                if anchor not in positions:
                    raise ScenePlanError(f"Insert anchor scene {anchor} does not exist.")
                insert_at = positions[anchor]
            elif operation.get("after_scene_id"):
                anchor = str(operation["after_scene_id"]).strip().casefold()
                if anchor not in positions:
                    raise ScenePlanError(f"Insert anchor scene {anchor} does not exist.")
                insert_at = positions[anchor] + 1
            else:
                insert_at = int(operation.get("index", len(scenes)))
                if insert_at < 0 or insert_at > len(scenes):
                    raise ScenePlanError("Insert index is outside the current scene order.")
            scenes.insert(insert_at, scene)
            audit.append({"type": kind, "scene_id": scene["id"], "index": insert_at})

        elif kind == "delete":
            if scene_id not in positions:
                raise ScenePlanError(f"Cannot delete unknown scene {scene_id!r}.")
            scenes.pop(positions[scene_id])
            audit.append({"type": kind, "scene_id": scene_id})

        elif kind == "update":
            if scene_id not in positions:
                raise ScenePlanError(f"Cannot update unknown scene {scene_id!r}.")
            changes = operation.get("changes")
            if not isinstance(changes, dict) or not changes:
                raise ScenePlanError("Update operations require a non-empty changes object.")
            forbidden = sorted(set(changes) - EDITABLE_SCENE_FIELDS)
            if forbidden:
                raise ScenePlanError(
                    "Scene operations cannot silently rewrite narration or factual evidence: "
                    + ", ".join(forbidden)
                )
            scenes[positions[scene_id]].update(copy.deepcopy(changes))
            if set(changes).intersection({"title", "caption", "image_prompt", "visual_mode"}):
                scenes[positions[scene_id]]["_visual_asset_invalidated"] = True
            audit.append({"type": kind, "scene_id": scene_id, "fields": sorted(changes)})

        elif kind == "reorder":
            order = operation.get("order")
            current = {scene["id"]: scene for scene in scenes}
            if not isinstance(order, list) or len(order) != len(current):
                raise ScenePlanError("Reorder must list every current scene id exactly once.")
            normalised_order = [str(value).strip().casefold() for value in order]
            if len(set(normalised_order)) != len(normalised_order) or set(normalised_order) != set(current):
                raise ScenePlanError("Reorder list must contain every current scene id exactly once.")
            scenes[:] = [current[value] for value in normalised_order]
            audit.append({"type": kind, "order": normalised_order})

        else:
            raise ScenePlanError(f"Unsupported scene operation type {kind!r}.")

    if not minimum_scenes <= len(scenes) <= maximum_scenes:
        raise ScenePlanError(
            f"Scene count must be between {minimum_scenes} and {maximum_scenes}; received {len(scenes)}."
        )
    _normalise_scene_ids(scenes)
    _validate_narration_mapping(scenes, sentence_count)

    for scene in scenes:
        if not scene.get("caption") or not scene.get("image_prompt"):
            raise ScenePlanError(f"Scene {scene['id']} requires both caption and image_prompt.")
    if audit:
        result["scene_operations_applied"] = audit
    result["scenes"] = scenes
    return result


def _allocate_durations(weights: list[float], total_seconds: float, minimum_seconds: float) -> list[float]:
    if not weights:
        raise ScenePlanError("Cannot allocate a timeline without scenes.")
    total = float(total_seconds)
    minimum = float(minimum_seconds)
    if total <= 0 or minimum <= 0 or total < len(weights) * minimum:
        raise ScenePlanError("The total timeline is too short for the requested scene count.")
    clean = [max(0.01, float(value)) for value in weights]
    remaining = total - len(clean) * minimum
    weight_total = sum(clean)
    return [minimum + remaining * value / weight_total for value in clean]


def snap_scene_boundaries(
    boundaries: list[float],
    beat_analysis: dict[str, Any] | None,
    *,
    minimum_scene_seconds: float = 2.5,
    maximum_shift_fraction: float = 0.25,
) -> tuple[list[float], dict[str, Any]]:
    """Snap interior cuts only when beat confidence is adequate and movement is small."""
    original = [float(value) for value in boundaries]
    result = list(original)
    diagnostics = {"enabled": False, "snapped": [], "reason": "no_confident_beat_map"}
    if not isinstance(beat_analysis, dict) or beat_analysis.get("confidence", 0) < 0.45:
        return result, diagnostics
    beats = beat_analysis.get("beat_times")
    bpm = beat_analysis.get("bpm")
    if not isinstance(beats, list) or not beats or not bpm:
        return result, diagnostics
    beat_seconds = 60.0 / float(bpm)
    tolerance = beat_seconds * maximum_shift_fraction
    diagnostics = {"enabled": True, "snapped": [], "reason": "analysed_audio"}
    for index in range(1, len(result) - 1):
        boundary = original[index]
        nearest = min((float(value) for value in beats), key=lambda value: abs(value - boundary))
        delta = nearest - boundary
        if abs(delta) > tolerance:
            continue
        if nearest - result[index - 1] < minimum_scene_seconds:
            continue
        if result[index + 1] - nearest < minimum_scene_seconds:
            continue
        result[index] = nearest
        diagnostics["snapped"].append({
            "boundary_index": index,
            "from_seconds": round(boundary, 4),
            "to_seconds": round(nearest, 4),
            "shift_seconds": round(delta, 4),
        })
    return result, diagnostics


def build_scene_timeline(
    scenes: list[dict[str, Any]],
    narration_info: dict[str, Any],
    *,
    total_seconds: float = 24.0,
    transition_seconds: float = 0.32,
    beat_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a deterministic scene timeline aligned to mapped narration and optional beats."""
    if not isinstance(scenes, list) or not scenes:
        raise ScenePlanError("A timeline requires at least one scene.")
    cues = narration_info.get("word_cues") or narration_info.get("subtitle_cues") or []
    if not isinstance(cues, list):
        cues = []
    transition = max(0.0, float(transition_seconds))
    transition = min(transition, 0.6)

    weights: list[float] = []
    for scene in scenes:
        indexes = set(scene.get("narration_sentence_indexes") or [])
        relevant = [
            cue for cue in cues
            if isinstance(cue, dict) and cue.get("sentence_index", 0) in indexes
        ]
        spans = []
        for cue in relevant:
            try:
                start = float(cue["start"])
                end = float(cue["end"])
                if end > start >= 0:
                    spans.append((start, end))
            except (KeyError, TypeError, ValueError):
                continue
        if spans:
            weights.append(max(0.25, max(end for _, end in spans) - min(start for start, _ in spans)))
        else:
            indexes = scene.get("narration_sentence_indexes") or []
            weights.append(max(1.0, float(len(indexes))))

    # Reserve a restrained visual hold for the final beat; the scene weights still
    # preserve the relative length of each mapped narration segment.
    if weights:
        weights[-1] += 1.8
    durations = _allocate_durations(weights, total_seconds, minimum_seconds=2.5)
    boundaries = [0.0]
    for value in durations:
        boundaries.append(boundaries[-1] + value)
    boundaries[-1] = float(total_seconds)

    snapped, beat_diagnostics = snap_scene_boundaries(boundaries, beat_analysis)
    durations = [snapped[index + 1] - snapped[index] for index in range(len(scenes))]
    entries = []
    for index, (scene, duration) in enumerate(zip(scenes, durations)):
        start = snapped[index] - index * transition
        clip_duration = duration + ((len(scenes) - 1) * transition if index == len(scenes) - 1 else 0.0)
        entries.append({
            "scene_id": str(scene["id"]),
            "index": index,
            "start": round(start, 4),
            "duration": round(duration, 4),
            "clip_duration": round(clip_duration, 4),
            "transition_in": round(transition if index else 0.0, 4),
            "narration_sentence_indexes": list(scene.get("narration_sentence_indexes") or []),
            "music_only": bool(scene.get("music_only", False)),
        })
    return {
        "duration_seconds": round(float(total_seconds), 4),
        "transition_seconds": round(transition, 4),
        "scenes": entries,
        "beat_alignment": beat_diagnostics,
    }


def scene_asset_path(
    package_dir: str,
    scene: dict[str, Any],
    index: int,
    *,
    allow_legacy: bool = True,
):
    """Resolve a stable image, optionally supporting a mapped legacy stage artifact."""
    from pathlib import Path

    root = Path(package_dir).resolve()
    scene_id = str(scene.get("id") or f"scene-{index + 1}")
    stable = root / f"scene-{scene_id}.jpg"
    if scene.get("_visual_asset_invalidated") is True:
        return stable
    if stable.is_file():
        return stable
    legacy_name = str(scene.get("_legacy_asset_filename") or "")
    if allow_legacy and legacy_name and Path(legacy_name).name == legacy_name:
        legacy = root / legacy_name
        if legacy.is_file():
            return legacy
    return stable
