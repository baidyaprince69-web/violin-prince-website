#!/usr/bin/env python3
"""Create an isolated Motion + HyperFrames animation project from a rig bundle."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parent
ANIMATION_DIR = ENGINE_DIR / "animation2d"


class RigPreviewError(RuntimeError):
    """Raised when the isolated character-rig preview cannot be prepared."""


def build_rig_preview_project(bundle_dir: str | Path, output_dir: str | Path) -> Path:
    bundle_dir = Path(bundle_dir).resolve(strict=True)
    output_dir = Path(output_dir).resolve()
    spec_path = bundle_dir / "character.json"
    report_path = bundle_dir / "separation-report.json"
    if not spec_path.is_file() or not report_path.is_file():
        raise RigPreviewError("The bundle must include character.json and separation-report.json.")

    from character_rig import validate_character_spec
    character = json.loads(spec_path.read_text(encoding="utf-8"))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if report.get("status") != "candidate_ready_for_visual_review":
        raise RigPreviewError("The separation report is not ready for rig preview.")
    try:
        character = validate_character_spec(character)
    except Exception as exc:
        raise RigPreviewError(f"The generated character spec failed rig validation: {exc}") from exc

    asset_dir = output_dir / "assets" / "characters" / character["id"]
    asset_dir.mkdir(parents=True, exist_ok=True)
    staged = {**character, "layers": [], "expressions": {}}
    for layer in character["layers"]:
        source = bundle_dir / layer["src"]
        if not source.is_file():
            raise RigPreviewError(f"Missing rig layer: {source.name}")
        target = asset_dir / source.name
        shutil.copy2(source, target)
        staged["layers"].append({**layer, "src": target.relative_to(output_dir).as_posix()})
    face_layer = next(layer for layer in staged["layers"] if layer["role"] == "face")
    for name, expression in character["expressions"].items():
        source = bundle_dir / expression["src"]
        if not source.is_file():
            raise RigPreviewError(f"Missing expression image: {source.name}")
        target = asset_dir / source.name
        shutil.copy2(source, target)
        staged["expressions"][name] = {
            "src": target.relative_to(output_dir).as_posix(),
            "x": face_layer["x"], "y": face_layer["y"],
            "width": face_layer["width"], "height": face_layer["height"],
        }

    scene_actions = {
        "scene-neutral": {"expression": "neutral", "duration": 1.2},
        "scene-blink": {"expression": "blink", "duration": 1.0},
        "scene-wave": {"gesture": "wave", "expression": "smile", "duration": 1.25},
        "scene-explain": {"gesture": "explain", "expression": "speaking", "duration": 1.25},
        "scene-left": {"gesture": "point_left", "expression": "neutral", "duration": 1.2},
        "scene-right": {"gesture": "point_right", "expression": "neutral", "duration": 1.2},
        "scene-palms": {"gesture": "open_palms", "expression": "smile", "duration": 1.2},
    }
    staged["scene_actions"] = scene_actions
    titles = [
        ("scene-neutral", "Neutral rig", "Separate character layers and joint anchors"),
        ("scene-blink", "Blink expression", "Facial expression reference alignment"),
        ("scene-wave", "Wave gesture", "Shoulder, elbow and wrist articulation"),
        ("scene-explain", "Explain gesture", "Two-arm movement and speaking face"),
        ("scene-left", "Point left", "Independent arm and hand movement"),
        ("scene-right", "Point right", "Independent arm and hand movement"),
        ("scene-palms", "Open palms", "Both hands move into a presenting gesture"),
    ]
    scenes = []
    for index, (scene_id, title, caption) in enumerate(titles):
        scenes.append({
            "id": scene_id,
            "start": round(index * 1.12, 3),
            "duration": 1.35,
            "title": title,
            "caption": caption,
            "background_color": ["#101b2b", "#142c35", "#1c2437"][index % 3],
        })
    project = {
        "title": "Violin Prince — Character Rig Test",
        "width": int(character["canvas"]["width"]),
        "height": int(character["canvas"]["height"]),
        "fps": 25,
        "duration_seconds": 8.2,
        "scenes": scenes,
        "characters": [staged],
        "diagnostics": {
            "kind": "isolated_character_rig_test",
            "separation_status": report["status"],
            "visual_review_required": True,
            "publishing": "disabled",
        },
    }
    output_dir.mkdir(parents=True, exist_ok=True)
    project_path = output_dir / "project.json"
    project_path.write_text(json.dumps(project, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (output_dir / "README.txt").write_text(
        "Isolated character-rig preview only. This is not a production video.\n"
        "Review separation-preview.png and separation-report.json before accepting the rig.\n"
        "No publishing or YouTube actions are performed.\n",
        encoding="utf-8",
    )
    return project_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build an isolated rig-preview project.")
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        project = build_rig_preview_project(args.bundle, args.output)
    except Exception as exc:
        print("CHARACTER_RIG_TEST_FAILED=" + str(exc))
        return 1
    print("CHARACTER_RIG_TEST_RESULT=" + json.dumps({
        "project": str(project),
        "rendered": False,
        "next": "Build and render this project with the pinned Motion + HyperFrames engine.",
    }))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
