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
    composite_base_mode = bool(character.get("base_art"))
    if composite_base_mode:
        character["base_art"]["src"] = stage_asset(bundle, asset_root, character["base_art"]["src"])
    if character.get("performance", {}).get("instrument_performance") is not True:
        raise ValueError("The candidate character bundle is not marked as an instrument-performance rig.")
    for layer in character.get("layers", []):
        layer["src"] = stage_asset(bundle, asset_root, layer["src"])
    for collection_name in ("expressions", "pose_assets", "props", "head_variants", "head_angles"):
        for asset in (character.get(collection_name) or {}).values():
            asset["src"] = stage_asset(bundle, asset_root, asset["src"])

    scene = {
        "id": "full-body-violin-performance",
        "start": 0,
        "duration": 8,
        "visual_mode": "full_body_performance",
        "background_color": "#08111b",
        "graphic_label": "FULL-BODY RIG TEST",
        "title": "",
        "caption": "",
        "character_actions": {
            "violin-prince": {
                "visible": True,
                "gesture": "violin_performance",
                "instrument_performance": True,
                "expression": "neutral",
                **({} if composite_base_mode else {
                    "head_angle": "front",
                    "head_angle_sequence": ["front", "three_quarter", "profile_right", "profile_left", "front"],
                    "head_angle_cycle_duration_seconds": 7.2,
                }),
                "x": 46,
                "y": 58,
                "scale": 0.84,
                "loop": True,
                "cycle_duration_seconds": 2.4,
                "start_offset": 0.12,
                "prop_keyframes": {
                    "bow": {
                        "rotate": [0, -3.5, 3.5, -3.5, 3.5, 0],
                        "translate": [
                            "-18px -4px", "18px 4px", "-18px -4px",
                            "18px 4px", "-18px -4px", "0px 0px"
                        ]
                    },
                    **({} if composite_base_mode else {
                        "violin": {"rotate": [0, -0.45, 0.35, 0.45, 0]},
                    }),
                },
            }
        },
    }
    project = {
        "schema_version": 4,
        "title": "",
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
            "character_rig": "intact_full_body_composite_review" if composite_base_mode else "segmented_full_body",
            "instrument_performance": "candidate_requires_visual_review",
        },
    }
    (output / "project.json").write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output / "README.txt").write_text(
        (
            "Non-publishing complete-body review preview. The original full-body "
            "source plate preserves both arms, both hands, shirt, trousers and shoes. "
            "The bow and four finger controls are separate animated overlays. "
            "Independent arm, leg and head motion is intentionally paused while the "
            "segmentation masks are rebuilt. Inspect the bow grip, finger seams and "
            "full-body silhouette before any production use. Publishing and "
            "scheduling are disabled.\n"
            if composite_base_mode else
            "Non-publishing segmented full-body rig preview. Inspect all layers "
            "and motion before any production use. Publishing and scheduling are "
            "disabled.\n"
        ),
        encoding="utf-8",
    )
    return {
        "status": "preview_project_ready",
        "duration_seconds": project["duration_seconds"],
        "canvas": [project["width"], project["height"]],
        "layer_count": len(character.get("layers", [])),
        "prop_ids": sorted((character.get("props") or {}).keys()),
        "head_variant_ids": sorted((character.get("head_variants") or {}).keys()),
        "head_angle_ids": sorted((character.get("head_angles") or {}).keys())
        if not character.get("base_art") else [],
        "composite_base_mode": bool(character.get("base_art")),
        "bow_hand_mode": "preserved_original_hand_plate" if character.get("base_art") else "segmented",
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
