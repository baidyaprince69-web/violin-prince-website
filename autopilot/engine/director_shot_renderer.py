"""Shot-level HyperFrames project preparation for Master Creative Director plans.

Each directed shot must receive its own verified image asset. This module never
recycles a scene image or fabricates a shot plate from a crop. The resulting
project preserves timing, camera, transition, palette and sync decisions.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from PIL import Image

from master_creative_director import DirectorPlanError, require_valid_director_plan


class DirectorShotRenderError(RuntimeError):
    """Raised when a shot-led plan cannot be converted to renderable assets."""


SUPPORTED_TRANSITION_IN = {
    "cut", "match_cut", "whip_pan", "dissolve", "luma_wipe",
    "shape_match", "speed_ramp", "light_transition", "foreground_wipe",
}
HYPERFRAMES_TRANSITION_NAMES = {name: name for name in SUPPORTED_TRANSITION_IN}
DEFAULT_TRANSITION_SECONDS = 0.36
MIN_IMAGE_BYTES = 1024


def _safe_hex(value: object, field: str) -> str:
    candidate = str(value or "").strip()
    if len(candidate) != 7 or candidate[0] != "#" or any(
        char not in "0123456789abcdefABCDEF" for char in candidate[1:]
    ):
        raise DirectorShotRenderError(f"Director palette {field} is not a valid #RRGGBB colour.")
    return candidate.upper()


def _transition_duration(transition: str, shot_duration: float) -> float:
    if transition in {"none", "cut", "match_cut"}:
        return 0.0
    if transition not in SUPPORTED_TRANSITION_IN:
        raise DirectorShotRenderError(
            f"Transition {transition!r} is not supported by the current shot renderer. "
            "Request a supported transition instead of silently approximating it."
        )
    return min(DEFAULT_TRANSITION_SECONDS, shot_duration * 0.22)


def _verify_unique_shot_images(
    shots: list[dict[str, Any]],
    image_paths: list[str | Path],
) -> list[dict[str, Any]]:
    if len(image_paths) != len(shots):
        raise DirectorShotRenderError(
            f"Every one of the {len(shots)} directed shots needs its own image asset; "
            f"received {len(image_paths)}."
        )

    seen_hashes: dict[str, str] = {}
    verified: list[dict[str, Any]] = []
    for index, (shot, raw_path) in enumerate(zip(shots, image_paths), start=1):
        path = Path(raw_path).expanduser().resolve()
        shot_id = str(shot.get("id") or index)
        if not path.is_file():
            raise DirectorShotRenderError(
                f"Shot {shot_id} is missing its visual asset: {path.name}."
            )
        if path.stat().st_size < MIN_IMAGE_BYTES:
            raise DirectorShotRenderError(f"Shot {shot_id} image is unexpectedly small.")
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        duplicate = seen_hashes.get(digest)
        if duplicate:
            raise DirectorShotRenderError(
                f"Shots {duplicate} and {shot_id} use identical image content. "
                "A new shot cannot be made by reusing or renaming an earlier image."
            )
        seen_hashes[digest] = shot_id
        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                width, height = image.size
                image_format = str(image.format or "").upper()
        except Exception as exc:
            raise DirectorShotRenderError(
                f"Shot {shot_id} asset is not a readable image."
            ) from exc
        if width < 256 or height < 256:
            raise DirectorShotRenderError(
                f"Shot {shot_id} image is too small ({width}x{height})."
            )
        if image_format not in {"PNG", "JPEG", "WEBP"}:
            raise DirectorShotRenderError(
                f"Shot {shot_id} image format {image_format or '[unknown]'} is unsupported."
            )
        verified.append({
            "path": path,
            "sha256": digest,
            "width": width,
            "height": height,
            "format": image_format,
            "file_size_bytes": path.stat().st_size,
        })
    return verified


def build_director_hyperframes_project(
    director_plan: dict[str, Any],
    image_paths: list[str | Path],
    project_dir: str | Path,
    *,
    width: int = 720,
    height: int = 1280,
    fps: int = 25,
) -> dict[str, Any]:
    """Copy unique shot plates and write a timed HyperFrames project."""
    try:
        require_valid_director_plan(director_plan)
    except DirectorPlanError as exc:
        raise DirectorShotRenderError(
            "Master Director plan failed validation: " + str(exc)
        ) from exc

    storyboard = director_plan["storyboard"]
    shots = storyboard["shots"]
    if not isinstance(width, int) or width < 1 or not isinstance(height, int) or height < 1:
        raise DirectorShotRenderError("Render dimensions must be positive integers.")
    if not isinstance(fps, int) or not 1 <= fps <= 120:
        raise DirectorShotRenderError("Render frame rate must be between 1 and 120.")

    verified_assets = _verify_unique_shot_images(shots, image_paths)
    root = Path(project_dir).expanduser().resolve()
    assets_dir = root / "assets" / "shots"
    assets_dir.mkdir(parents=True, exist_ok=True)

    palette = director_plan["visual_concept"]["palette"]
    director_palette = {
        "dominant": _safe_hex(palette.get("dominant"), "dominant"),
        "secondary": _safe_hex(palette.get("secondary"), "secondary"),
        "accent": _safe_hex(palette.get("accent"), "accent"),
        "harmony": str(palette.get("harmony") or ""),
        "reasoning": str(palette.get("reasoning") or ""),
        "contrast_strategy": str(palette.get("contrast_strategy") or ""),
    }

    scene_records: list[dict[str, Any]] = []
    shot_asset_records: list[dict[str, Any]] = []
    for index, (shot, asset) in enumerate(zip(shots, verified_assets)):
        shot_id = str(shot["id"])
        source = asset["path"]
        extension = source.suffix.lower()
        if extension not in {".png", ".jpg", ".jpeg", ".webp"}:
            extension = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[asset["format"]]
        target = assets_dir / f"{shot_id}{extension}"
        shutil.copy2(source, target)

        start = float(shot["start_seconds"])
        end = float(shot["end_seconds"])
        shot_duration = end - start
        outgoing_transition = str(shot["transition_to_next"]).casefold()
        outgoing_seconds = _transition_duration(outgoing_transition, shot_duration)
        incoming_transition = "cut"
        incoming_seconds = 0.0
        if index > 0:
            previous = shots[index - 1]
            previous_transition = str(previous["transition_to_next"]).casefold()
            incoming_transition = HYPERFRAMES_TRANSITION_NAMES[previous_transition]
            incoming_seconds = _transition_duration(
                previous_transition,
                float(previous["end_seconds"]) - float(previous["start_seconds"]),
            )

        render_start = max(0.0, start - incoming_seconds)
        render_duration = end - render_start
        camera = dict(shot["camera"])
        animation = dict(shot["animation"])
        scene_records.append({
            "id": shot_id,
            "start": round(render_start, 4),
            "duration": round(render_duration, 4),
            "image": target.relative_to(root).as_posix(),
            "title": "",
            "caption": "",
            "graphic_label": str(shot.get("purpose") or "SHOT").replace("_", " ").upper(),
            "graphic_detail": "",
            "editorial_index": index + 1,
            "editorial_total": len(shots),
            "visual_mode": "director_shot",
            "director_camera": camera,
            "director_animation": animation,
            "director_visual_subject": str(shot.get("visual_subject") or ""),
            "director_visual_description": str(shot.get("visual_description") or ""),
            "director_setting": str(shot.get("setting") or ""),
            "director_composition": str(shot.get("composition") or ""),
            "director_narration_cue": str(shot.get("narration_cue") or ""),
            "director_music_cue": str(shot.get("music_cue") or ""),
            "director_sound_effects": list(shot.get("sound_effects") or []),
            "director_transition_out": outgoing_transition,
            "transition_in": incoming_transition,
            "transition_in_duration": round(incoming_seconds, 4),
            "camera_motion_start_offset": round(incoming_seconds, 4),
            "camera_motion_duration": round(shot_duration, 4),
            "transition_out_duration": round(outgoing_seconds, 4),
            "camera_easing": "ease-in" if outgoing_transition == "speed_ramp" else "ease-in-out",
            "animation_execution_status": (
                "camera_and_transition_tracks_only; "
                "subject_layer_animation_requires_separated_assets"
            ),
        })
        shot_asset_records.append({
            "shot_id": shot_id,
            "path": target.relative_to(root).as_posix(),
            "sha256": asset["sha256"],
            "width": asset["width"],
            "height": asset["height"],
            "format": asset["format"],
            "file_size_bytes": asset["file_size_bytes"],
        })

    edit_direction = dict(director_plan["edit_direction"])
    duration = float(storyboard["duration_seconds"])
    project = {
        "schema_version": 2,
        "title": str(director_plan.get("title") or "Violin Prince — Master Director"),
        "width": width,
        "height": height,
        "fps": fps,
        "duration_seconds": duration,
        "brand_system": "violin-prince-master-director-shot-led",
        "director_contract": "violin-prince-master-director-v1",
        "director_palette": director_palette,
        "director_visual_concept": dict(director_plan["visual_concept"]),
        "director_story_understanding": dict(director_plan["story_understanding"]),
        "director_edit_direction": edit_direction,
        "director_music_sync_cues": list(edit_direction.get("music_sync_cues") or []),
        "director_transition_summary": [
            {
                "from_shot": str(shot["id"]),
                "transition": str(shot["transition_to_next"]),
                "duration_seconds": _transition_duration(
                    str(shot["transition_to_next"]).casefold(),
                    float(shot["end_seconds"]) - float(shot["start_seconds"]),
                ),
            }
            for shot in shots[:-1]
        ],
        "shot_asset_manifest": shot_asset_records,
        "shots": [
            {
                "id": str(shot["id"]),
                "start_seconds": float(shot["start_seconds"]),
                "end_seconds": float(shot["end_seconds"]),
                "visual_subject": str(shot["visual_subject"]),
                "visual_description": str(shot["visual_description"]),
                "camera": dict(shot["camera"]),
                "animation": dict(shot["animation"]),
                "music_cue": str(shot["music_cue"]),
                "transition_to_next": str(shot["transition_to_next"]),
            }
            for shot in shots
        ],
        "scenes": scene_records,
        "characters": [],
    }
    destination = root / "project.json"
    root.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return project
