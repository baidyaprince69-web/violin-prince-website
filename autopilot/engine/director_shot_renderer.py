"""Shot-level, independently layered HyperFrames project preparation."""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path
from typing import Any

from PIL import Image

from master_creative_director import DirectorPlanError, require_valid_director_plan


class DirectorShotRenderError(RuntimeError):
    """Raised when a layered shot plan cannot be staged safely."""


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


def _verify_layer_asset(
    raw_path: str | Path,
    *,
    identity: str,
    asset_mode: str,
    seen_hashes: dict[str, str],
) -> dict[str, Any]:
    path = Path(raw_path).expanduser().resolve()
    if not path.is_file():
        raise DirectorShotRenderError(f"Visual layer {identity} is missing its generated image asset.")
    if path.stat().st_size < MIN_IMAGE_BYTES:
        raise DirectorShotRenderError(f"Visual layer {identity} image is unexpectedly small.")

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    duplicate = seen_hashes.get(digest)
    if duplicate:
        raise DirectorShotRenderError(
            f"Visual layers {duplicate} and {identity} use identical image content. "
            "Each layer and shot must have independently generated pixels."
        )
    seen_hashes[digest] = identity

    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            width, height = image.size
            image_format = str(image.format or "").upper()
            bands = image.getbands()
            has_alpha = "A" in bands or "transparency" in image.info
            alpha_extrema = image.getchannel("A").getextrema() if "A" in bands else None
    except Exception as exc:
        raise DirectorShotRenderError(
            f"Visual layer {identity} asset is not a readable image."
        ) from exc

    if width < 256 or height < 256:
        raise DirectorShotRenderError(
            f"Visual layer {identity} image is too small ({width}x{height})."
        )
    if image_format not in {"PNG", "JPEG", "WEBP"}:
        raise DirectorShotRenderError(
            f"Visual layer {identity} uses unsupported image format {image_format or '[unknown]'}."
        )

    if asset_mode == "transparent_png":
        if image_format != "PNG" or not has_alpha or alpha_extrema is None or alpha_extrema[0] >= 255:
            raise DirectorShotRenderError(
                f"Visual layer {identity} must be a PNG with a real non-opaque alpha channel; "
                "a full-frame image pretending to be a cutout is blocked."
            )
        if alpha_extrema[1] <= 0:
            raise DirectorShotRenderError(f"Visual layer {identity} is fully transparent.")
    elif asset_mode == "opaque":
        if alpha_extrema is not None and alpha_extrema[0] < 255:
            raise DirectorShotRenderError(
                f"Visual layer {identity} is marked opaque but contains transparent pixels."
            )
    else:
        raise DirectorShotRenderError(f"Visual layer {identity} has unsupported asset_mode {asset_mode!r}.")

    return {
        "path": path,
        "sha256": digest,
        "width": width,
        "height": height,
        "format": image_format,
        "has_alpha": bool(has_alpha),
        "file_size_bytes": path.stat().st_size,
    }


def build_director_hyperframes_project(
    director_plan: dict[str, Any],
    image_paths: list[str | Path],
    project_dir: str | Path,
    *,
    layer_assets: dict[str, dict[str, str | Path]] | None = None,
    width: int = 720,
    height: int = 1280,
    fps: int = 25,
) -> dict[str, Any]:
    """Copy each independently generated layer and create the timed Motion project.

    image_paths supplies one opaque full-frame background per shot.
    layer_assets supplies transparent PNGs for every other director layer,
    indexed by shot ID and layer ID. Identical content is rejected globally.
    """
    try:
        require_valid_director_plan(director_plan)
    except DirectorPlanError as exc:
        raise DirectorShotRenderError(
            "Master Director plan failed validation: " + str(exc)
        ) from exc

    storyboard = director_plan["storyboard"]
    shots = storyboard["shots"]
    if len(image_paths) != len(shots):
        raise DirectorShotRenderError(
            f"Every one of the {len(shots)} shots needs one opaque background; "
            f"received {len(image_paths)}."
        )
    if not isinstance(layer_assets, dict):
        raise DirectorShotRenderError("Transparent subject, foreground and graphic layer assets are required.")
    if not isinstance(width, int) or width < 1 or not isinstance(height, int) or height < 1:
        raise DirectorShotRenderError("Render dimensions must be positive integers.")
    if not isinstance(fps, int) or not 1 <= fps <= 120:
        raise DirectorShotRenderError("Render frame rate must be between 1 and 120.")

    root = Path(project_dir).expanduser().resolve()
    assets_dir = root / "assets" / "shots"
    assets_dir.mkdir(parents=True, exist_ok=True)
    seen_hashes: dict[str, str] = {}

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
    expected_shot_ids = {str(shot["id"]) for shot in shots}
    if set(layer_assets) != expected_shot_ids:
        raise DirectorShotRenderError(
            "Layer asset map must contain exactly every storyboard shot ID; no shots may be skipped or added."
        )

    for index, (shot, raw_background) in enumerate(zip(shots, image_paths)):
        shot_id = str(shot["id"])
        shot_folder = assets_dir / shot_id
        shot_folder.mkdir(parents=True, exist_ok=True)
        layer_specs = shot["visual_layers"]
        layer_map = layer_assets.get(shot_id)
        expected_non_background = {
            str(layer["id"]) for layer in layer_specs if layer["role"] != "background"
        }
        if not isinstance(layer_map, dict) or set(layer_map) != expected_non_background:
            raise DirectorShotRenderError(
                f"Shot {shot_id} needs exactly these independently generated non-background layers: "
                + ", ".join(sorted(expected_non_background))
            )

        staged_layers: list[dict[str, Any]] = []
        background_path: str | None = None
        for layer in sorted(layer_specs, key=lambda item: int(item["z_index"])):
            layer_id = str(layer["id"])
            role = str(layer["role"])
            identity = f"{shot_id}/{layer_id}"
            raw_path = raw_background if role == "background" else layer_map[layer_id]
            asset = _verify_layer_asset(
                raw_path,
                identity=identity,
                asset_mode=str(layer["asset_mode"]),
                seen_hashes=seen_hashes,
            )
            extension = {"PNG": ".png", "JPEG": ".jpg", "WEBP": ".webp"}[asset["format"]]
            target = shot_folder / f"{layer_id}{extension}"
            shutil.copy2(asset["path"], target)
            relative_path = target.relative_to(root).as_posix()
            record = {
                "id": layer_id,
                "role": role,
                "description": str(layer["description"]),
                "generation_prompt": str(layer["generation_prompt"]),
                "z_index": int(layer["z_index"]),
                "asset_mode": str(layer["asset_mode"]),
                "image": relative_path,
                "motion": dict(layer["motion"]),
                "asset_sha256": asset["sha256"],
                "asset_width": asset["width"],
                "asset_height": asset["height"],
                "asset_format": asset["format"],
                "asset_has_alpha": asset["has_alpha"],
            }
            staged_layers.append(record)
            shot_asset_records.append({
                "shot_id": shot_id,
                "layer_id": layer_id,
                "role": role,
                "path": relative_path,
                "sha256": asset["sha256"],
                "width": asset["width"],
                "height": asset["height"],
                "format": asset["format"],
                "has_alpha": asset["has_alpha"],
                "file_size_bytes": asset["file_size_bytes"],
            })
            if role == "background":
                if background_path is not None:
                    raise DirectorShotRenderError(f"Shot {shot_id} declares more than one background layer.")
                background_path = relative_path

        if background_path is None:
            raise DirectorShotRenderError(f"Shot {shot_id} is missing its required background layer.")

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
        scene_records.append({
            "id": shot_id,
            "start": round(render_start, 4),
            "duration": round(render_duration, 4),
            "image": background_path,
            "visual_layers": staged_layers,
            "title": "",
            "caption": "",
            "graphic_label": str(shot.get("purpose") or "SHOT").replace("_", " ").upper(),
            "graphic_detail": "",
            "editorial_index": index + 1,
            "editorial_total": len(shots),
            "visual_mode": "director_shot",
            "director_camera": dict(shot["camera"]),
            "director_animation": dict(shot["animation"]),
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
            "animation_execution_status": "separate_image_layers_staged_for_independent_motion",
        })

    edit_direction = dict(director_plan["edit_direction"])
    duration = float(storyboard["duration_seconds"])
    project = {
        "schema_version": 3,
        "title": str(director_plan.get("title") or "Violin Prince — Master Director"),
        "width": width,
        "height": height,
        "fps": fps,
        "duration_seconds": duration,
        "brand_system": "violin-prince-master-director-multilayer-v2",
        "director_contract": "violin-prince-master-director-v2",
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
                "visual_layers": list(shot["visual_layers"]),
                "music_cue": str(shot["music_cue"]),
                "transition_to_next": str(shot["transition_to_next"]),
            }
            for shot in shots
        ],
        "scenes": scene_records,
        "characters": [],
    }
    root.mkdir(parents=True, exist_ok=True)
    destination = root / "project.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(destination)
    return project
