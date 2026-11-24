"""Build procedural Motion scenes directly from a Master Creative Director v3 plan.

No generated scene plates or transparent cutouts are accepted in procedural mode.
The renderer translates each authored shot into an animated environment, authored
moving vector objects, a whole-scene camera track, kinetic graphics and (where
requested) the existing articulated Violin Prince presenter rig.
"""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from character_presenter import attach_violin_prince_presenter
from illustration_asset_factory import prepare_character_assets
from master_creative_director import (
    DirectorPlanError,
    require_valid_director_plan,
)


class ProceduralDirectorError(RuntimeError):
    """Raised when a procedural Director plan cannot become a Motion project."""


TRANSITION_SECONDS = 0.36


def _transition_seconds(name: str, duration: float) -> float:
    value = str(name or "cut").strip().casefold()
    if value in {"none", "cut", "match_cut"}:
        return 0.0
    if value not in {
        "whip_pan", "dissolve", "luma_wipe", "shape_match",
        "speed_ramp", "light_transition", "foreground_wipe",
    }:
        raise ProceduralDirectorError(f"Unsupported transition: {value!r}.")
    return min(TRANSITION_SECONDS, max(0.0, float(duration)) * 0.22)


def build_procedural_director_project(
    director_plan: dict[str, Any],
    project_dir: str | Path,
    *,
    rig_bundle_dir: str | Path | None = None,
    width: int = 720,
    height: int = 1280,
    fps: int = 25,
) -> dict[str, Any]:
    """Translate a procedural v3 storyboard into a complete Motion project."""
    try:
        require_valid_director_plan(director_plan)
    except DirectorPlanError as exc:
        raise ProceduralDirectorError("Master Director plan failed validation: " + str(exc)) from exc

    if str(director_plan.get("render_mode") or "").casefold() != "procedural_2d":
        raise ProceduralDirectorError("The procedural renderer requires render_mode='procedural_2d'.")
    if not isinstance(width, int) or width != 720 or not isinstance(height, int) or height != 1280:
        raise ProceduralDirectorError("The Violin Prince Shorts renderer requires a 720x1280 portrait canvas.")
    if not isinstance(fps, int) or not 1 <= fps <= 60:
        raise ProceduralDirectorError("The procedural renderer frame rate must be 1–60 fps.")

    root = Path(project_dir).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    package = root / "package"
    staged_root = root / "staged-character-assets"
    character_root = root / "assets" / "characters" / "violin-prince"
    package.mkdir(parents=True, exist_ok=True)
    character_root.mkdir(parents=True, exist_ok=True)

    storyboard = director_plan["storyboard"]
    shots = storyboard["shots"]
    palette = director_plan["visual_concept"]["palette"]
    dominant = str(palette["dominant"]).upper()
    scenes: list[dict[str, Any]] = []
    transition_summary: list[dict[str, Any]] = []

    for index, shot in enumerate(shots):
        start = float(shot["start_seconds"])
        end = float(shot["end_seconds"])
        duration = end - start
        incoming_name = "cut" if index == 0 else str(shots[index - 1]["transition_to_next"]).casefold()
        incoming_seconds = 0.0 if index == 0 else _transition_seconds(incoming_name, duration)
        render_start = max(0.0, start - incoming_seconds)
        scene_duration = end - render_start
        action = dict(shot["character_action"])
        graphic = shot.get("graphic_data")
        procedural = shot["procedural_scene"]
        camera = dict(shot["camera"])
        transition_out = str(shot["transition_to_next"]).casefold()

        scene = {
            "id": str(shot["id"]),
            "start": round(render_start, 4),
            "duration": round(scene_duration, 4),
            "title": str(shot["visual_subject"]),
            "caption": str(shot["purpose"]).replace("_", " ").upper(),
            "graphic_label": str(shot["purpose"]).replace("_", " ").upper(),
            "graphic_detail": str(shot.get("setting") or ""),
            "background_color": dominant,
            "visual_mode": "procedural_2d",
            "stagecraft": {
                "environment": str(procedural["environment"]),
                "objects": [dict(item) for item in procedural["objects"]],
                "music_sync_cues": [
                    dict(cue)
                    for cue in director_plan["edit_direction"]["music_sync_cues"]
                    if start <= float(cue["time_seconds"]) < end
                ],
            },
            "director_camera": camera,
            "camera_motion_start_offset": round(incoming_seconds, 4),
            "camera_motion_duration": round(duration, 4),
            "camera_easing": "ease-in" if transition_out == "speed_ramp" else "ease-in-out",
            "transition_in": incoming_name,
            "transition_in_duration": round(incoming_seconds, 4),
            "transition_out": transition_out,
            "transition_out_duration": round(_transition_seconds(transition_out, duration), 4),
            "editorial_index": index + 1,
            "editorial_total": len(shots),
            "character_actions": {"violin-prince": action},
            "animation_execution_status": "procedural_environment_objects_articulated_character_and_camera",
            "director_purpose": str(shot["purpose"]),
            "director_setting": str(shot["setting"]),
            "director_description": str(shot["visual_description"]),
            "director_composition": str(shot["composition"]),
            "director_animation": dict(shot["animation"]),
            "director_narration_cue": str(shot["narration_cue"]),
            "director_music_cue": str(shot["music_cue"]),
            "director_sound_effects": list(shot.get("sound_effects") or []),
        }
        if graphic is not None:
            scene["graphic_data"] = dict(graphic)
            # Keep information cards in the left column and the articulated
            # presenter in the right safe area; never cover the face/gesture.
            scene["visual_composition"] = {"layout": "graphic_left_presenter_right"}
            action["x"] = 315
            action["scale"] = 0.56
            scene["character_actions"] = {"violin-prince": action}
        scenes.append(scene)
        if index < len(shots) - 1:
            transition_summary.append({
                "from_shot": str(shot["id"]),
                "transition": transition_out,
                "duration_seconds": _transition_seconds(transition_out, duration),
            })

    presenter_plan = {
        "use_violin_prince_presenter": True,
        "scenes": scenes,
        "characters": [],
    }
    try:
        attach_violin_prince_presenter(
            presenter_plan,
            package_dir=package,
            rig_bundle_dir=rig_bundle_dir,
        )
        characters = prepare_character_assets(
            presenter_plan,
            source_root=package,
            destination_root=staged_root,
        )
    except Exception as exc:
        raise ProceduralDirectorError("The tested Violin Prince presenter rig could not be staged: " + str(exc)) from exc

    if len(characters) != 1 or str(characters[0].get("id")) != "violin-prince":
        raise ProceduralDirectorError("Procedural preview must stage exactly one Violin Prince presenter.")
    character = characters[0]
    for section in ("layers",):
        for item in character.get(section, []):
            source = Path(item["src"]).resolve(strict=True)
            target = character_root / source.name
            shutil.copy2(source, target)
            item["src"] = (Path("assets") / "characters" / "violin-prince" / target.name).as_posix()
    def persist_asset(item: dict[str, Any]) -> None:
        source = Path(item["src"]).resolve(strict=True)
        target = character_root / source.name
        shutil.copy2(source, target)
        item["src"] = (
            Path("assets") / "characters" / "violin-prince" / target.name
        ).as_posix()

    for section in (
        "expressions", "pose_assets", "props", "head_variants", "head_angles",
    ):
        for item in (character.get(section) or {}).values():
            persist_asset(item)
    if isinstance(character.get("base_art"), dict):
        persist_asset(character["base_art"])

    leg_roles = {
        "left_thigh", "left_calf", "left_foot",
        "right_thigh", "right_calf", "right_foot",
    }
    staged_roles = {str(item.get("role") or "") for item in character.get("layers", [])}
    has_full_body_performance = (
        leg_roles.issubset(staged_roles)
        and isinstance(character.get("performance"), dict)
        and {"violin", "bow"}.issubset(set((character.get("props") or {}).keys()))
    )

    for scene in scenes:
        action = (scene.get("character_actions") or {}).get("violin-prince") or {}
        if action.get("visible") is True and not action.get("gesture"):
            raise ProceduralDirectorError(
                f"Scene {scene['id']} shows the presenter but has no articulated gesture."
            )

    concept = dict(director_plan["visual_concept"])
    project = {
        "schema_version": 4,
        "title": str(director_plan.get("title") or "Violin Prince — Procedural Master Director"),
        "width": width,
        "height": height,
        "fps": fps,
        "duration_seconds": float(storyboard["duration_seconds"]),
        "brand_system": "violin-prince-master-director-procedural-v3",
        "director_contract": "violin-prince-master-director-v3",
        "render_mode": "procedural_2d",
        "director_palette": dict(palette),
        "director_visual_concept": concept,
        "director_story_understanding": dict(director_plan["story_understanding"]),
        "director_edit_direction": dict(director_plan["edit_direction"]),
        "director_music_sync_cues": list(director_plan["edit_direction"]["music_sync_cues"]),
        "music_sync_report": dict(director_plan.get("music_sync_report") or {}),
        "director_transition_summary": transition_summary,
        "scenes": scenes,
        "characters": characters,
        "shot_asset_manifest": [],
        "visual_asset_policy": {
            "mode": "procedural_vectors_and_articulated_rig",
            "generated_scene_images": 0,
            "generated_cutout_images": 0,
            "static_image_fallback_allowed": False,
        },
        "diagnostics": {
            "publishing": "disabled",
            "preview_only": True,
            "rig_scope": (
                "full_body_violin_performance"
                if has_full_body_performance
                else "upper_body_presenter"
            ),
            "attached_instrument_props": sorted((character.get("props") or {}).keys()),
        },
    }
    destination = root / "project.json"
    temporary = destination.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(destination)
    rig_description = (
        "The Violin Prince full-body performance rig includes its leg joints, articulated "
        "fingers, and attached violin/bow props."
        if has_full_body_performance else
        "The Violin Prince upper-body presenter rig is used; this bundle does not include "
        "the full-body performance rig or attached violin/bow props."
    )
    (root / "README.txt").write_text(
        "Procedural Master Director preview project. Environments and props are live SVG Motion "
        "elements, camera movement targets the full scene world, and the Violin Prince presenter "
        "is articulated per shot. This preview contains no generated scene plates or cutout "
        "images and cannot be published. " + rig_description + "\n",
        encoding="utf-8",
    )
    return project
