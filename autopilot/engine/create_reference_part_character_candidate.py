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

from PIL import Image

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
    """Create a review-only character spec using all aligned non-prop body parts."""
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
    canvas_width = float(canvas.get("width", 0))
    canvas_height = float(canvas.get("height", 0))
    if canvas_width <= 0 or canvas_height <= 0:
        raise ValueError("The candidate character needs a valid source canvas.")

    if layered.get("status") != "layered_candidate_exported_pending_joint_pivot_alignment":
        raise ValueError("The source bundle is not an assembled layered candidate.")
    if layered.get("production_layer_replacement_enabled") is not False:
        raise ValueError("Production layer replacement must remain disabled.")
    if layered.get("missing_or_unplaced") != []:
        raise ValueError("All supplied assembly parts must be placed before building the rig.")
    if int(layered.get("layer_count", 0)) != 18:
        raise ValueError("The reference candidate must contain exactly 18 exported source layers.")
    pivots = layered.get("joint_pivots") or {}
    if set(pivots) != REQUIRED_JOINT_PIVOTS:
        raise ValueError("The candidate does not contain all 12 limb pivots plus the preserved neck.")
    for joint_name in REQUIRED_JOINT_PIVOTS - {"neck"}:
        item = pivots[joint_name]
        if item.get("approved") is not False:
            raise ValueError(f"{joint_name} must remain a review-only pivot estimate.")
        if int(item.get("overlap_pixels", 0)) < int(item.get("minimum_overlap_pixels", 1)):
            raise ValueError(f"{joint_name} does not have enough source-alpha overlap evidence.")

    exported = {str(item["layer_id"]): item for item in layered.get("layers", [])}
    layers: list[dict[str, Any]] = []
    used_ids: set[str] = set()
    for part_id, role in PART_ROLES.items():
        entry = exported.get(part_id)
        if entry is None:
            raise ValueError(f"The layered candidate is missing required body part {part_id}.")
        layer = _layer_from_export(entry, role, source, output)
        joint_name = PIVOT_JOINT_FOR_ROLE.get(role)
        if joint_name:
            pivot = pivots[joint_name]["normalized"]
            x, y = float(entry["x"]), float(entry["y"])
            layer["pivot_x"] = (float(pivots[joint_name]["x"]) - x) / float(entry["width"])
            layer["pivot_y"] = (float(pivots[joint_name]["y"]) - y) / float(entry["height"])
            layer["pivot_joint"] = joint_name
            layer["pivot_status"] = pivots[joint_name]["status"]
            if not 0 <= layer["pivot_x"] <= 1 or not 0 <= layer["pivot_y"] <= 1:
                raise ValueError(f"The {joint_name} pivot falls outside the {role} sprite.")
        elif role == "torso":
            old_torso = next(
                (item for item in original.get("layers", []) if item.get("role") == "torso"),
                None,
            )
            if old_torso:
                root_x = float(old_torso["x"]) + float(old_torso["width"]) * float(old_torso.get("pivot_x", .5))
                root_y = float(old_torso["y"]) + float(old_torso["height"]) * float(old_torso.get("pivot_y", .5))
                layer["pivot_x"] = (root_x - layer["x"]) / layer["width"]
                layer["pivot_y"] = (root_y - layer["y"]) / layer["height"]
        if role in used_ids:
            raise ValueError(f"Duplicate candidate rig role: {role}")
        used_ids.add(role)
        layers.append(layer)

    for bridge_id, role in BRIDGE_ROLES.items():
        candidate_layer_ids = (
            "source-bridge-" + bridge_id,
            "source-bridge-" + bridge_id.replace("_", "-"),
        )
        layer_id = next(
            (candidate_id for candidate_id in candidate_layer_ids if candidate_id in exported),
            candidate_layer_ids[0],
        )
        entry = exported.get(layer_id)
        if entry is None:
            raise ValueError(f"The layered candidate is missing source bridge {bridge_id}.")
        layer = _layer_from_export(entry, role, source, output)
        if role == "right_forearm":
            pivot = pivots["right_elbow"]
            layer["pivot_x"] = (float(pivot["x"]) - layer["x"]) / layer["width"]
            layer["pivot_y"] = (float(pivot["y"]) - layer["y"]) / layer["height"]
            layer["pivot_joint"] = "right_elbow"
            layer["pivot_status"] = pivot["status"]
            # This source bridge contains the upper finger/contact pixels that
            # wrap over the violin neck. Keep it above the violin, matching the
            # preserved source rig's right-forearm (z=31) > violin (z=25) order.
            layer["z_index"] = 64
        layers.append(layer)

    # Preserve the original source-rig fingerboard hand instead of activating
    # reference-part-022: that isolated hand drawing drops below the fingerboard
    # in the rendered performance. The original source hand already wraps the
    # neck and uses its authored right-wrist anchor.
    original_layers_by_role = {
        str(item.get("role") or ""): item
        for item in original.get("layers", [])
    }
    for source_role, candidate_role in SOURCE_CHARACTER_LAYER_ROLES.items():
        original_layer = original_layers_by_role.get(source_role)
        if original_layer is None:
            raise ValueError(
                f"The preserved source character is missing its {source_role} layer."
            )
        source_joint = (original.get("joints") or {}).get("right_wrist")
        if not isinstance(source_joint, dict):
            raise ValueError("The preserved source character has no right-wrist anchor.")
        x = float(original_layer["x"])
        y = float(original_layer["y"])
        width = float(original_layer["width"])
        height = float(original_layer["height"])
        wrist_x = float(source_joint["x"]) * canvas_width
        wrist_y = float(source_joint["y"]) * canvas_height
        pivot_x = (wrist_x - x) / width
        pivot_y = (wrist_y - y) / height
        if not 0 <= pivot_x <= 1 or not 0 <= pivot_y <= 1:
            raise ValueError("The preserved source right-wrist joint falls outside its hand sprite.")
        source_hand = {
            "id": candidate_role,
            "role": candidate_role,
            "src": _copy_asset(source, output, str(original_layer["src"])),
            "x": x,
            "y": y,
            "width": width,
            "height": height,
            "pivot_x": pivot_x,
            "pivot_y": pivot_y,
            "z_index": 70,
            "candidate_source_layer_id": "preserved-original-right-hand",
            "pivot_joint": "right_wrist",
            "pivot_status": "preserved_source_fingerboard_grip_joint_pending_visual_review",
            "source_art_policy": "preserved_original_fingerboard_grip",
        }
        layers.append(source_hand)
        used_ids.add(candidate_role)

    # The supplied head portrait is retained as a hidden anchor. The visible
    # head is replaced by the six aligned full-head expression plates.
    head_entry = exported.get("reference-part-001")
    if head_entry is None:
        raise ValueError("The assembled candidate has no head portrait anchor.")
    head_x = float(head_entry["x"])
    head_y = float(head_entry["y"])
    head_width = float(head_entry["width"])
    head_height = float(head_entry["height"])
    neck = pivots["neck"]
    head_pivot_x = (float(neck["x"]) - head_x) / head_width
    head_pivot_y = (float(neck["y"]) - head_y) / head_height
    if not 0 <= head_pivot_x <= 1 or not 0 <= head_pivot_y <= 1:
        raise ValueError("The preserved neck pivot is outside the assembled head anchor.")

    anchor_path = output / "reference-candidate-transparent-anchor.png"
    Image.new("RGBA", (1, 1), (0, 0, 0, 0)).save(anchor_path, format="PNG")
    for anchor_role, anchor_id, z_index in (
        ("head", "head", 80),
        ("face", "face", 81),
    ):
        layers.append({
            "id": anchor_id,
            "role": anchor_role,
            "src": anchor_path.name,
            "x": head_x,
            "y": head_y,
            "width": head_width,
            "height": head_height,
            "pivot_x": head_pivot_x,
            "pivot_y": head_pivot_y,
            "z_index": z_index,
            "candidate_source_layer_id": "reference-part-001",
            "pivot_joint": "neck",
            "pivot_status": "source_coordinate_preserved_pending_candidate_visual_review",
        })

    layers.sort(key=lambda item: item["z_index"])

    source_props = original.get("props") or {}
    violin_entry = exported.get("reference-part-025")
    bow_entry = exported.get("source-bridge-bow")
    if violin_entry is None or bow_entry is None:
        raise ValueError("The candidate must include both the violin and the approved bow.")
    violin_source = source_props.get("violin") or {}
    bow_source = source_props.get("bow") or {}
    props = {
        "violin": {
            "id": "violin",
            "src": _copy_asset(source, output, str(violin_entry["src"])),
            "x": float(violin_entry["x"]),
            "y": float(violin_entry["y"]),
            "width": float(violin_entry["width"]),
            "height": float(violin_entry["height"]),
            "pivot_x": float(violin_source.get("pivot_x", .5)),
            "pivot_y": float(violin_source.get("pivot_y", .5)),
            "z_index": int(violin_entry["z_index"]),
            "attach_to": "torso",
        },
        "bow": {
            "id": "bow",
            "src": _copy_asset(source, output, str(bow_entry["src"])),
            "x": float(bow_entry["x"]),
            "y": float(bow_entry["y"]),
            "width": float(bow_entry["width"]),
            "height": float(bow_entry["height"]),
            "pivot_x": float(bow_source.get("pivot_x", .5)),
            "pivot_y": float(bow_source.get("pivot_y", .5)),
            "z_index": int(bow_entry["z_index"]),
            "attach_to": "left_hand",
        },
    }

    # The face variants are full-head plates. They replace the static portrait
    # instead of being layered over it, which prevents a doubled/ghosted face.
    head_variants: dict[str, dict[str, Any]] = {}
    source_head_variants = original.get("head_variants") or {}
    for name, asset in source_head_variants.items():
        if not isinstance(asset, dict):
            continue
        entry = dict(asset)
        entry["src"] = _copy_asset(source, output, str(asset["src"]))
        entry.update({
            "x": head_x,
            "y": head_y,
            "width": head_width,
            "height": head_height,
            "pivot_x": head_pivot_x,
            "pivot_y": head_pivot_y,
            "z_index": 90,
        })
        head_variants[str(name)] = entry
    if not REQUIRED_FACE_STATES.issubset(set(head_variants)):
        raise ValueError("The candidate head is missing one or more of the six required facial states.")

    expressions: dict[str, dict[str, str]] = {}
    for name, asset in (original.get("expressions") or {}).items():
        src = asset.get("src") if isinstance(asset, dict) else asset
        expressions[str(name)] = {"src": _copy_asset(source, output, str(src))}

    # The animation preview stages every pose asset referenced by the candidate
    # character, so copy those source files into the isolated bundle as well.
    pose_assets: dict[str, dict[str, Any]] = {}
    for name, asset in (original.get("pose_assets") or {}).items():
        src = asset.get("src") if isinstance(asset, dict) else asset
        entry = dict(asset) if isinstance(asset, dict) else {"src": str(src)}
        entry["src"] = _copy_asset(source, output, str(src))
        pose_assets[str(name)] = entry

    candidate_joints = json.loads(json.dumps(original.get("joints") or {}))
    for name, pivot in pivots.items():
        if name == "right_wrist":
            # The active candidate right hand is preserved original grip art,
            # so retain its matching authored wrist coordinate.
            continue
        candidate_joints[name] = {
            "x": float(pivot["x"]) / canvas_width,
            "y": float(pivot["y"]) / canvas_height,
        }

    performance = dict(original.get("performance") or {})
    performance.update({
        "instrument_performance": True,
        "continuous_body_deformation": "alpha_overlap_pivot_hierarchy_review_candidate",
        "independent_limb_layer_count": 12,
        "fingering_parts": [],
        "fingering_segment_roles": [],
        "fingering_joint_count": 0,
        "fingering_articulation_enabled": False,
        "joint_surface_roles": [],
        "review_required": True,
        "compositing_mode": "reference_sheet_layered_candidate",
    })

    candidate = {
        **original,
        "id": "violin-prince",
        "canvas": dict(canvas),
        "layers": layers,
        "joints": candidate_joints,
        "expressions": expressions,
        "pose_assets": pose_assets,
        "head_variants": head_variants,
        "head_angles": {},
        "props": props,
        "performance": performance,
        "reference_part_alignment": {
            "status": "candidate_layered_rig_built_pending_animation_visual_review",
            "manifest": "reference-part-assembled-layer-candidate.json",
            "primary_part_count": int(layered.get("primary_part_count", 0)),
            "source_bridge_count": int(layered.get("source_bridge_count", 0)),
            "exported_source_layer_count": int(layered.get("layer_count", 0)),
            "candidate_character_layer_count": len(layers),
            "candidate_prop_count": len(props),
            "source_character_layer_roles_used": sorted(SOURCE_CHARACTER_LAYER_ROLES),
            "right_hand_art_source": "preserved_original_fingerboard_grip",
            "joint_pivot_count": len(pivots),
            "joint_pivots_validated": False,
            "facial_state_count": len(REQUIRED_FACE_STATES),
            "facial_states_alignment": "positioned_on_candidate_head_pending_visual_review",
            "finger_articulation_enabled": False,
            "finger_articulation_status": "intact_preserved_source_fingerboard_grip_without_independent_finger_layers",
            "production_layer_replacement_enabled": False,
            "activation_policy": "review_only_do_not_replace_live_rig_or_publish",
        },
    }
    candidate.pop("base_art", None)
    candidate.pop("performance_base_mode", None)

    validate_character_spec(candidate)
    (output / "character.json").write_text(
        json.dumps(candidate, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    _copy_asset(source, output, "reference-part-assembled-layer-candidate.json")
    _copy_asset(source, output, "reference-part-assembled-candidate.json")
    _copy_asset(source, output, "reference-part-assembled-candidate.png")

    report = {
        "status": "candidate_character_spec_validated_pending_animation_visual_review",
        "canvas": dict(canvas),
        "candidate_character_layer_count": len(layers),
        "candidate_prop_count": len(props),
        "visible_body_layers": len(layers) - 2,
        "head_anchor_layers": 2,
        "source_parts_used": sorted(PART_ROLES),
        "source_bridges_used": sorted(BRIDGE_ROLES),
        "source_character_layers_used": sorted(SOURCE_CHARACTER_LAYER_ROLES),
        "right_hand_art_source": "preserved_original_fingerboard_grip",
        "props": sorted(props),
        "facial_states": sorted(REQUIRED_FACE_STATES),
        "joint_pivots": {
            name: (
                {
                    "x": float(candidate_joints[name]["x"]) * canvas_width,
                    "y": float(candidate_joints[name]["y"]) * canvas_height,
                    "overlap_pixels": None,
                    "method": "preserved_original_source_fingerboard_grip_wrist",
                    "approved": False,
                }
                if name == "right_wrist" else
                {
                    "x": value["x"],
                    "y": value["y"],
                    "overlap_pixels": value.get("overlap_pixels"),
                    "method": value.get("method"),
                    "approved": False,
                }
            )
            for name, value in pivots.items()
        },
        "finger_articulation_enabled": False,
        "production_layer_replacement_enabled": False,
        "publishing_enabled": False,
        "live_character_modified": False,
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
