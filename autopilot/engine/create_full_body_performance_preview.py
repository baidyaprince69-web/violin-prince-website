#!/usr/bin/env python3
"""Build a non-publishing Motion project for the full-body violin rig preview."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


def stage_asset(bundle: Path, asset_root: Path, source: str) -> str:
    source_path = (bundle / str(source)).resolve(strict=True)
    if bundle.resolve() not in source_path.parents:
        raise ValueError(f"Character asset path escapes its rig bundle: {source}")
    destination = asset_root / source_path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination)
    return destination.relative_to(asset_root.parent.parent.parent).as_posix()


def build_preview_project(bundle_dir: str | Path, output_dir: str | Path) -> dict[str, Any]:
    bundle = Path(bundle_dir).resolve(strict=True)
    output = Path(output_dir).resolve()
    asset_root = output / "assets" / "characters" / "violin-prince"
    asset_root.mkdir(parents=True, exist_ok=True)
    character_path = bundle / "character.json"
    if not character_path.is_file():
        raise FileNotFoundError("The full-body rig bundle does not contain character.json.")

    character = json.loads(character_path.read_text(encoding="utf-8"))
    if character.get("performance", {}).get("instrument_performance") is not True:
        raise ValueError("The candidate character bundle is not marked as an instrument-performance rig.")
    for layer in character.get("layers", []):
        layer["src"] = stage_asset(bundle, asset_root, layer["src"])
    for collection_name in ("expressions", "pose_assets", "props"):
        for asset in (character.get(collection_name) or {}).values():
            asset["src"] = stage_asset(bundle, asset_root, asset["src"])

    scene = {
        "id": "full-body-violin-performance",
        "start": 0,
        "duration": 8,
        "visual_mode": "cover_performance",
        "background_color": "#08111b",
        "title": "FULL-BODY VIOLIN PERFORMANCE",
        "caption": "ARTICULATED BODY · FINGERING · BOW STROKES",
        "character_actions": {
            "violin-prince": {
                "visible": True,
                "gesture": "violin_performance",
                "instrument_performance": True,
                "expression": "neutral",
                "loop": True,
                "cycle_duration_seconds": 2.4,
                "start_offset": 0.12,
                "prop_keyframes": {
                    "bow": {"rotate": [0, -6, 6, -6, 6, 0]},
                    "violin": {"rotate": [0, -0.45, 0.35, 0.45, 0]},
                },
            }
        },
    }
    project = {
        "schema_version": 4,
        "title": "Violin Prince — Full-Body Performance Rig Preview",
        "width": 720,
        "height": 1280,
        "fps": 25,
        "duration_seconds": 8,
        "brand_system": "violin-prince-fullbody-performance-rig-v1",
        "render_mode": "preview_only",
        "director_palette": {
            "dominant": "#08111b",
            "secondary": "#f5ecde",
            "accent": "#d9b77a",
        },
        "scenes": [scene],
        "characters": [character],
        "publishing": {
            "enabled": False,
            "preview_only": True,
            "schedule_enabled": False,
        },
        "diagnostics": {
            "publishing": "disabled",
            "preview_only": True,
            "character_rig": "full_body",
            "instrument_performance": "candidate_requires_visual_review",
        },
    }
    (output / "project.json").write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "README.txt").write_text(
        "Non-publishing full-body violin performance preview. The scene uses the "
        "candidate full-body rig, individual leg/finger layers, and separately "
        "attached violin/bow props. Inspect the render and the separation report "
        "before considering this rig for any production workflow. Publishing and "
        "scheduling are disabled. Synthetic or temporary audio is not included.\n",
        encoding="utf-8",
    )
    return {
        "status": "preview_project_ready",
        "duration_seconds": project["duration_seconds"],
        "canvas": [project["width"], project["height"]],
        "layer_count": len(character.get("layers", [])),
        "prop_ids": sorted((character.get("props") or {}).keys()),
        "publishing": "disabled",
        "preview_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    result = build_preview_project(args.bundle, args.output)
    print("FULL_BODY_PREVIEW_PROJECT=" + json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
