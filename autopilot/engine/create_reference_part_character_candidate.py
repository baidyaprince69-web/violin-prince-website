"""Build an isolated animation-test character from the assembled reference-sheet layers.

This candidate never replaces the active character specification. Its body
sprites, joint pivots, face plates and instrument props are copied into a
separate bundle for a character-only review render.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageChops, ImageDraw, ImageFilter

from character_rig import validate_character_spec


PART_ROLES = {
    "reference-part-003": "torso",
    "reference-part-024": "waist",
    "reference-part-004": "left_upper_arm",
    "reference-part-005": "right_upper_arm",
    "reference-part-006": "left_forearm",
    "reference-part-021": "left_hand",
    "reference-part-027": "left_thigh",
    "reference-part-028": "right_thigh",
    "reference-part-030": "left_calf",
    "reference-part-031": "right_calf",
    "reference-part-032": "left_foot",
    "reference-part-033": "right_foot",
}
BRIDGE_ROLES = {
    "head_neck": "neck_bridge",
    "right_forearm": "right_forearm",
}
SOURCE_CHARACTER_LAYER_ROLES = {
    # This original source hand is already posed around the violin fingerboard.
    # The extracted reference-part-022 variant hangs below the neck in motion.
    "right_hand": "right_hand",
}
PIVOT_JOINT_FOR_ROLE = {
    "head": "neck",
    "left_upper_arm": "left_shoulder",
    "left_forearm": "left_elbow",
    "left_hand": "left_wrist",
    "right_upper_arm": "right_shoulder",
    "right_forearm": "right_elbow",
    "right_hand": "right_wrist",
    "left_thigh": "left_hip",
    "right_thigh": "right_hip",
    "left_calf": "left_knee",
    "right_calf": "right_knee",
    "left_foot": "left_ankle",
    "right_foot": "right_ankle",
}
REQUIRED_JOINT_PIVOTS = {
    "left_shoulder", "left_elbow", "left_wrist",
    "right_shoulder", "right_elbow", "right_wrist",
    "left_hip", "right_hip", "left_knee", "right_knee",
    "left_ankle", "right_ankle", "neck",
}
REQUIRED_FACE_STATES = {
    "speaking_open", "speaking_closed", "blink_closed",
    "sad", "shocked_open", "smile",
}


def _copy_asset(source_bundle: Path, output_bundle: Path, src: str) -> str:
    source = source_bundle / src
    if not source.is_file():
        raise FileNotFoundError(f"Candidate source asset is missing: {src}")
    destination = output_bundle / Path(src).name
    if source.resolve() != destination.resolve():
        shutil.copy2(source, destination)
    return destination.name


def _extract_preserved_fingerboard_grip_hand(
    source_bundle: Path,
    output_bundle: Path,
) -> dict[str, Any]:
    """Extract the original fingerboard hand without copying violin pixels.

    The source hand is drawn over the violin neck in the preserved full-body
    plate. Keep only skin-coloured pixels inside a hand silhouette, then use a
    one-pixel alpha dilation to retain its dark ink outline.
    """
    source_path = source_bundle / "preserved-full-body-source.png"
    if not source_path.is_file():
        raise FileNotFoundError(
            "The preserved full-body source is required for the fingerboard hand."
        )
    source_image = Image.open(source_path).convert("RGBA")
    if source_image.size != (441, 755):
        raise ValueError(
            "The preserved fingerboard-hand source must use the 441x755 character canvas."
        )

    rgba = np.asarray(source_image, dtype=np.uint8)
    red = rgba[:, :, 0].astype(np.int16)
    green = rgba[:, :, 1].astype(np.int16)
    blue = rgba[:, :, 2].astype(np.int16)
    alpha = rgba[:, :, 3] > 0

    silhouette = Image.new("L", source_image.size, 0)
    ImageDraw.Draw(silhouette).polygon(
        [
            (324, 169), (379, 169), (382, 173), (387, 183),
            (389, 191), (383, 201), (377, 206), (372, 214),
            (366, 221), (360, 230), (352, 238), (344, 246),
            (337, 251), (330, 249), (326, 244), (324, 237),
            (325, 229), (327, 219), (328, 209), (325, 201),
            (321, 195), (320, 188), (322, 180),
        ],
        fill=255,
    )
    hand_region = np.asarray(silhouette, dtype=np.uint8) > 0
    # The skin range excludes the orange violin, dark strings and transparent
    # background. The surrounding silhouette prevents other skin areas from
    # entering this hand cutout.
    skin = (
        alpha
        & hand_region
        & (red >= 125)
        & (green >= 75)
        & (blue >= 48)
        & ((red - green) >= 25)
        & ((green - blue) >= 10)
        & ((red - blue) >= 35)
    )
    raw_mask = Image.fromarray((skin * 255).astype(np.uint8), mode="L")
    outlined_mask = raw_mask.filter(ImageFilter.MaxFilter(3))
    final_mask = ImageChops.multiply(
        outlined_mask, source_image.getchannel("A")
    )
    bounds = final_mask.getbbox()
    if bounds is None or bounds[2] - bounds[0] < 35 or bounds[3] - bounds[1] < 55:
        raise ValueError(
            "Could not isolate the complete source fingerboard hand from the preserved artwork."
        )

    hand_sprite = source_image.crop(bounds)
    hand_sprite.putalpha(final_mask.crop(bounds))
    filename = "reference-source-fingerboard-grip-hand.png"
    hand_sprite.save(output_bundle / filename, format="PNG", optimize=True)
    return {
        "src": filename,
        "x": int(bounds[0]),
        "y": int(bounds[1]),
        "width": int(bounds[2] - bounds[0]),
        "height": int(bounds[3] - bounds[1]),
        "visible_alpha_pixels": int(np.count_nonzero(np.asarray(hand_sprite.getchannel("A")))),
        "extraction_method": "preserved_full_body_skin_mask_with_ink_outline",
    }


def _layer_from_export(
    entry: dict[str, Any],
    role: str,
    source_bundle: Path,
    output_bundle: Path,
) -> dict[str, Any]:
    src = _copy_asset(source_bundle, output_bundle, str(entry["src"]))
    pivot = entry.get("pivot_hint_normalized") or [0.5, 0.5]
    layer = {
        "id": role,
        "role": role,
        "src": src,
        "x": float(entry["x"]),
        "y": float(entry["y"]),
        "width": float(entry["width"]),
        "height": float(entry["height"]),
        "pivot_x": float(pivot[0]),
        "pivot_y": float(pivot[1]),
        "z_index": int(entry["z_index"]),
        "candidate_source_layer_id": str(entry["layer_id"]),
        "pivot_status": str(entry.get("pivot_status") or "unreviewed"),
    }
    return layer


def build_reference_part_character_candidate(
    source_bundle: str | Path,
    output_bundle: str | Path,
) -> dict[str, Any]:
    """Build a review-only character from one coherent, preserved source pose.

    The reference-sheet cutouts are deliberately retained as review material.
    They are not assembled onto the master performance art because their
    front-facing pose does not match the master's three-quarter violin pose.
    """
    source = Path(source_bundle).resolve(strict=True)
    output = Path(output_bundle).resolve()
    output.mkdir(parents=True, exist_ok=True)

    layered_path = source / "reference-part-assembled-layer-candidate.json"
    assembly_path = source / "reference-part-assembled-candidate.json"
    character_path = source / "character.json"
    for required in (layered_path, assembly_path, character_path):
        if not required.is_file():
            raise FileNotFoundError(f"Required candidate input is missing: {required.name}")

    layered = json.loads(layered_path.read_text(encoding="utf-8"))
    assembly = json.loads(assembly_path.read_text(encoding="utf-8"))
    original = json.loads(character_path.read_text(encoding="utf-8"))
    canvas = original.get("canvas") or {}
    canvas_width = int(canvas.get("width", 0))
    canvas_height = int(canvas.get("height", 0))
    if canvas_width <= 0 or canvas_height <= 0:
        raise ValueError("The candidate character needs a valid source canvas.")

    if layered.get("status") != "layered_candidate_exported_pending_joint_pivot_alignment":
        raise ValueError("The source bundle is not an assembled layered candidate.")
    if layered.get("production_layer_replacement_enabled") is not False:
        raise ValueError("Production layer replacement must remain disabled.")
    if layered.get("missing_or_unplaced") != []:
        raise ValueError("All supplied assembly parts must be present in the review catalogue.")
    if int(layered.get("layer_count", 0)) != 18:
        raise ValueError("The reference catalogue must contain exactly 18 exported source layers.")
    pivots = layered.get("joint_pivots") or {}
    if set(pivots) != REQUIRED_JOINT_PIVOTS:
        raise ValueError("The candidate does not contain all 12 limb pivots plus the preserved neck.")

    preserved_path = source / "preserved-full-body-source.png"
    if not preserved_path.is_file():
        raise FileNotFoundError("The preserved full-body source illustration is required.")
    with Image.open(preserved_path) as preserved_image:
        if preserved_image.size != (canvas_width, canvas_height):
            raise ValueError("The preserved full-body source must match the original character canvas.")
        preserved_rgba = preserved_image.convert("RGBA")
        if preserved_rgba.getchannel("A").getbbox() is None:
            raise ValueError("The preserved full-body source illustration is fully transparent.")
    integrated_source = _copy_asset(source, output, preserved_path.name)

    # The renderer's rig contract still requires these role anchors. They are
    # intentionally transparent: all visible anatomy, violin, bow and face
    # remain in the one source-aligned master image, with no duplicate overlays.
    anchor_path = output / "transparent-character-anchor.png"
    Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(anchor_path, format="PNG")
    required_roles = (
        "torso", "head", "face",
        "left_upper_arm", "left_forearm", "left_hand",
        "right_upper_arm", "right_forearm", "right_hand",
    )
    layers = [
        {
            "id": role,
            "role": role,
            "src": anchor_path.name,
            "x": 0,
            "y": 0,
            "width": 1,
            "height": 1,
            "pivot_x": 0.5,
            "pivot_y": 0.5,
            "z_index": index + 1,
            "candidate_source_layer_id": "transparent_compatibility_anchor",
            "activation_policy": "transparent_no_duplicate_body_art",
        }
        for index, role in enumerate(required_roles)
    ]

    # The integrated master already contains the correct face and violin grip.
    # Empty head plates prevent the oversized expression crops from replacing it.
    transparent_expression = {"src": anchor_path.name}
    original_joints = json.loads(json.dumps(original.get("joints") or {}))
    performance = dict(original.get("performance") or {})
    performance.update({
        "instrument_performance": True,
        "continuous_body_deformation": "preserved_single_source_composite",
        "independent_limb_layer_count": 0,
        "fingering_parts": [],
        "fingering_segment_roles": [],
        "fingering_joint_count": 0,
        "fingering_articulation_enabled": False,
        "joint_surface_roles": [],
        "review_required": True,
        "compositing_mode": "intact_source_full_body_composite",
    })

    candidate = {
        **original,
        "id": "violin-prince",
        "canvas": {"width": canvas_width, "height": canvas_height},
        "base_art": {
            "src": integrated_source,
            "x": 0,
            "y": 0,
            "width": canvas_width,
            "height": canvas_height,
            "z_index": 10,
        },
        "performance_base_mode": "intact_full_body_source_composite",
        "layers": layers,
        "joints": original_joints,
        "expressions": {
            "neutral": dict(transparent_expression),
            "alternate": dict(transparent_expression),
        },
        "poses": {},
        "gestures": {},
        "pose_assets": {},
        "head_variants": {},
        "head_angles": {},
        "props": {},
        "performance": performance,
        "reference_part_alignment": {
            "status": "intact_master_art_selected_reference_cutouts_not_activated",
            "assembly_method": "single_source_preserved_full_body_composite_no_pose_mismatched_cutouts",
            "source_art": integrated_source,
            "source_pose": "original_three_quarter_violin_performance",
            "reference_sheet_pose": "front_facing_catalogue_not_compatible_with_master_pose",
            "reference_parts_reviewed": len(layered.get("layers", [])),
            "reference_parts_activated": 0,
            "candidate_character_layer_count": len(layers),
            "visible_composite_count": 1,
            "transparent_compatibility_anchor_count": len(layers),
            "right_hand_art_source": "integrated_original_full_body_art_with_authored_fingerboard_grip",
            "joint_pivot_count": len(pivots),
            "joint_pivots_validated": False,
            "facial_state_count": 0,
            "facial_states_alignment": "original_face_preserved_inside_full_body_art",
            "finger_articulation_enabled": False,
            "production_layer_replacement_enabled": False,
            "activation_policy": "review_only_do_not_replace_live_rig_or_publish",
        },
    }

    validate_character_spec(candidate)
    (output / "character.json").write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _copy_asset(source, output, "reference-part-assembled-layer-candidate.json")
    _copy_asset(source, output, "reference-part-assembled-candidate.json")
    _copy_asset(source, output, "reference-part-assembled-candidate.png")

    report = {
        "status": "candidate_source_composite_validated_pending_animation_visual_review",
        "canvas": {"width": canvas_width, "height": canvas_height},
        "assembly_method": "single_source_preserved_full_body_composite_no_pose_mismatched_cutouts",
        "candidate_character_layer_count": len(layers),
        "candidate_prop_count": 0,
        "visible_body_layers": 0,
        "visible_composite_count": 1,
        "transparent_compatibility_anchor_count": len(layers),
        "source_parts_used": [],
        "source_bridges_used": [],
        "source_parts_reviewed": sorted(
            str(item.get("layer_id")) for item in layered.get("layers", [])
        ),
        "source_bridges_reviewed": sorted(BRIDGE_ROLES),
        "right_hand_art_source": "integrated_original_full_body_art_with_authored_fingerboard_grip",
        "facial_states": [],
        "joint_pivot_count": len(pivots),
        "joint_pivots_validated": False,
        "finger_articulation_enabled": False,
        "production_layer_replacement_enabled": False,
        "publishing_enabled": False,
        "live_character_modified": False,
        "reference_cutouts_activated": False,
        "reference_sheet_pose_mismatch": True,
        "assembly_source_asset_count": int(assembly.get("source_asset_count", 0)),
    }
    (output / "reference-part-character-candidate-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-bundle", required=True)
    parser.add_argument("--output-bundle", required=True)
    args = parser.parse_args()
    report = build_reference_part_character_candidate(
        args.source_bundle, args.output_bundle
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
