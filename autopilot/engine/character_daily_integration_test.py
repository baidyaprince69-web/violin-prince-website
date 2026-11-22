#!/usr/bin/env python3
"""Build a production-sized portrait Motion project from the tested presenter rig."""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))

from illustration_asset_factory import prepare_character_assets  # noqa: E402
from character_presenter import attach_violin_prince_presenter  # noqa: E402


def build_daily_portrait_project(
    bundle_dir: str | Path,
    output_dir: str | Path,
) -> Path:
    bundle_dir = Path(bundle_dir).resolve(strict=True)
    output_dir = Path(output_dir).resolve()
    package_dir = output_dir / "package"
    assets_dir = output_dir / "assets" / "characters" / "violin-prince"
    package_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)

    scenes = [
        ("scene-neutral", "Presenter introduction", "Relaxed presenter in a resting pose", "resting_hands"),
        ("scene-wave", "Welcome", "The presenter greets the viewer", "one_arm_raised"),
        ("scene-explain", "Key explanation", "Two-hand explaining pose", "explaining_two_hands"),
        ("scene-left", "First detail", "Point toward the left-side graphic", "point_left"),
        ("scene-right", "Second detail", "Point toward the right-side graphic", "point_right"),
        ("scene-palms", "Summary", "Open-palms presenting gesture", "open_palms"),
        ("scene-close", "Closing", "Return to a relaxed presenter pose", "resting_hands"),
    ]
    plan = {
        "use_violin_prince_presenter": True,
        "scenes": [
            {
                "id": scene_id,
                "start": round(index * 1.12, 3),
                "duration": 1.35,
                "title": title,
                "caption": caption,
                "background_color": ["#101b2b", "#142c35", "#1c2437"][index % 3],
                "presenter_pose": pose,
            }
            for index, (scene_id, title, caption, pose) in enumerate(scenes)
        ],
    }
    # A final procedural performance shot exercises real vector scenery,
    # moving stage objects, articulated character motion and director camera
    # movement in the same portrait render used for the daily integration proof.
    plan["scenes"].append({
        "id": "scene-procedural-performance",
        "start": 7.85,
        "duration": 2.2,
        "title": "The stage comes alive",
        "caption": "Procedural animation integration proof",
        "background_color": "#080c18",
        "visual_mode": "cover_performance",
        "director_camera": {"movement": "dolly_in", "shot_size": "medium"},
        "camera_motion_start_offset": 0.0,
        "camera_motion_duration": 2.2,
        "stagecraft": {
            "environment": "concert_stage",
            "objects": [
                {
                    "id": "rising-music-note",
                    "kind": "music_note",
                    "x": 0.18,
                    "y": 0.34,
                    "size": 28,
                    "color": "#e5c38b",
                    "motion": "float",
                    "period_seconds": 1.7,
                },
                {
                    "id": "passing-light",
                    "kind": "light_streak",
                    "x": 0.16,
                    "y": 0.82,
                    "size": 62,
                    "color": "#72cdd3",
                    "motion": "travel_right",
                    "period_seconds": 2.0,
                },
                {
                    "id": "accent-spark",
                    "kind": "spark",
                    "x": 0.83,
                    "y": 0.42,
                    "size": 18,
                    "color": "#f3d59a",
                    "motion": "pulse",
                    "period_seconds": 1.1,
                },
                {
                    "id": "rotating-ring",
                    "kind": "ring",
                    "x": 0.78,
                    "y": 0.68,
                    "size": 42,
                    "color": "#78d6d0",
                    "motion": "rotate",
                    "period_seconds": 3.0,
                },
            ],
        },
        "character_actions": {
            "violin-prince": {
                "visible": True,
                "gesture": "dance_groove",
                "expression": "smile",
                "loop": True,
                "cycle_duration_seconds": 1.25,
                "root_motion": {"type": "sway", "intensity": 0.38},
            }
        },
    })
    plan = attach_violin_prince_presenter(
        plan,
        package_dir=package_dir,
        rig_bundle_dir=bundle_dir,
    )
    # The Motion renderer does not consume the descriptive presenter_pose
    # field. Convert it to the scene action contract so the selected full-body
    # pose plate is actually shown in the rendered integration proof.
    for scene in plan["scenes"]:
        pose_asset = str(scene.pop("presenter_pose", "") or "").strip().casefold()
        if pose_asset:
            scene.setdefault("character_actions", {})["violin-prince"] = {
                "visible": True,
                "pose_asset": pose_asset,
            }
    staged = prepare_character_assets(
        plan,
        source_root=package_dir,
        destination_root=output_dir / "staged-character-assets",
    )
    if len(staged) != 1 or staged[0].get("id") != "violin-prince":
        raise RuntimeError("The daily asset factory did not stage exactly one Violin Prince presenter.")

    character = staged[0]
    for layer in character["layers"]:
        source = Path(layer["src"]).resolve(strict=True)
        target = assets_dir / source.name
        shutil.copy2(source, target)
        layer["src"] = (Path("assets") / "characters" / "violin-prince" / target.name).as_posix()
    for expression in character["expressions"].values():
        source = Path(expression["src"]).resolve(strict=True)
        target = assets_dir / source.name
        shutil.copy2(source, target)
        expression["src"] = (Path("assets") / "characters" / "violin-prince" / target.name).as_posix()
    for pose in character["pose_assets"].values():
        source = Path(pose["src"]).resolve(strict=True)
        target = assets_dir / source.name
        shutil.copy2(source, target)
        pose["src"] = (Path("assets") / "characters" / "violin-prince" / target.name).as_posix()

    project = {
        "title": "Violin Prince — Daily Portrait Integration Test",
        "width": 720,
        "height": 1280,
        "fps": 25,
        "duration_seconds": 10.05,
        "scenes": plan["scenes"],
        "characters": staged,
        "diagnostics": {
            "kind": "daily_pipeline_character_integration",
            "presenter_enabled": True,
            "rig_source": "tested_character_autorig_bundle",
            "character_source_canvas": character.get("canvas"),
            "composition_canvas": {"width": 720, "height": 1280},
            "publishing": "disabled",
        },
    }
    project_path = output_dir / "project.json"
    project_path.write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "README.txt").write_text(
        "Portrait-size integration test of the daily Motion + HyperFrames character path.\n"
        "The project uses the saved auto-rig bundle, authored presenter poses, articulated gestures,\n"
        "procedural concert-stage environment, moving vector props, camera choreography and\n"
        "animated spectrum graphics at 720x1280. It is not a production Short and is not published.\n",
        encoding="utf-8",
    )
    return project_path


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit(
            "Usage: character_daily_integration_test.py BUNDLE_DIR OUTPUT_DIR"
        )
    path = build_daily_portrait_project(sys.argv[1], sys.argv[2])
    print(f"DAILY_PORTRAIT_PROJECT={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
