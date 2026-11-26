import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from create_reference_part_character_candidate import (
    REQUIRED_FACE_STATES,
    REQUIRED_JOINT_PIVOTS,
    build_reference_part_character_candidate,
)


PART_ROLES = {
    "reference-part-003": "torso",
    "reference-part-024": "waist",
    "reference-part-004": "left_upper_arm",
    "reference-part-005": "right_upper_arm",
    "reference-part-006": "left_forearm",
    "reference-part-021": "left_hand",
    "reference-part-022": "right_hand",
    "reference-part-027": "left_thigh",
    "reference-part-028": "right_thigh",
    "reference-part-030": "left_calf",
    "reference-part-031": "right_calf",
    "reference-part-032": "left_foot",
    "reference-part-033": "right_foot",
}
BRIDGES = {
    "source-bridge-head-neck": "neck_bridge",
    "source-bridge-right-forearm": "right_forearm",
    "source-bridge-bow": "bow",
}
PRIMARY_IDS = [
    "reference-part-032", "reference-part-033",
    "reference-part-030", "reference-part-031",
    "reference-part-027", "reference-part-028",
    "reference-part-024", "reference-part-003",
    "reference-part-004", "reference-part-005", "reference-part-006",
    "reference-part-025", "reference-part-021", "reference-part-022",
    "reference-part-001",
]


def write_image(path: Path, colour=(170, 120, 80, 255)):
    image = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((2, 2, 21, 21), radius=4, fill=colour)
    image.save(path)


def make_source_bundle(root: Path):
    source = root / "source"
    source.mkdir()
    for name in (
        "reference-part-001", "reference-part-003", "reference-part-004",
        "reference-part-005", "reference-part-006", "reference-part-021",
        "reference-part-022", "reference-part-024", "reference-part-025",
        "reference-part-027", "reference-part-028", "reference-part-030",
        "reference-part-031", "reference-part-032", "reference-part-033",
        "source-bridge-head-neck", "source-bridge-right-forearm",
        "source-bridge-bow",
    ):
        write_image(source / f"{name}.png")

    facial_assets = {}
    for name in sorted(REQUIRED_FACE_STATES):
        filename = f"face-{name}.png"
        write_image(source / filename, (110, 70, 60, 255))
        facial_assets[name] = {
            "src": filename,
            "x": 0, "y": 0, "width": 24, "height": 24,
            "pivot_x": 0.5, "pivot_y": 0.9, "z_index": 90,
        }

    for name in ("neutral", "happy"):
        write_image(source / f"expression-{name}.png")
    write_image(source / "base-art.png")

    original_joints = {
        name: {"x": 0.5, "y": 0.5}
        for name in (
            "neck", "left_shoulder", "left_elbow", "left_wrist",
            "right_shoulder", "right_elbow", "right_wrist",
            "left_hip", "right_hip", "left_knee", "right_knee",
            "left_ankle", "right_ankle",
        )
    }
    original = {
        "id": "violin-prince",
        "canvas": {"width": 441, "height": 755},
        "base_art": {"src": "base-art.png"},
        "performance_base_mode": "segmented_source_body",
        "layers": [{
            "id": "torso", "role": "torso", "src": "base-art.png",
            "x": 100, "y": 200, "width": 80, "height": 80,
            "pivot_x": 0.5, "pivot_y": 0.5,
        }],
        "joints": original_joints,
        "expressions": {
            "neutral": {"src": "expression-neutral.png"},
            "happy": {"src": "expression-happy.png"},
        },
        "head_variants": facial_assets,
        "head_angles": {},
        "props": {
            "violin": {
                "id": "violin", "src": "reference-part-025.png",
                "x": 100, "y": 200, "width": 80, "height": 80,
                "pivot_x": 0.5, "pivot_y": 0.5, "attach_to": "torso",
            },
            "bow": {
                "id": "bow", "src": "source-bridge-bow.png",
                "x": 100, "y": 200, "width": 80, "height": 80,
                "pivot_x": 0.5, "pivot_y": 0.98, "attach_to": "left_hand",
            },
        },
        "performance": {"instrument_performance": True},
    }
    (source / "character.json").write_text(
        json.dumps(original, indent=2), encoding="utf-8"
    )
    (source / "reference-part-assembled-candidate.json").write_text(
        json.dumps({
            "canvas": {"width": 441, "height": 755},
            "source_asset_count": 18,
            "production_layer_replacement_enabled": False,
        }),
        encoding="utf-8",
    )

    exports = []
    role_by_id = {
        **PART_ROLES,
        "reference-part-001": "head",
        "reference-part-025": "violin",
        **BRIDGES,
    }
    for index, layer_id in enumerate(PRIMARY_IDS + list(BRIDGES)):
        role = role_by_id[layer_id]
        layer_x, layer_y, layer_width, layer_height = 100, 200, 80, 80
        if layer_id == "reference-part-001":
            layer_x, layer_y, layer_width, layer_height = 100, 100, 80, 100
        exports.append({
            "layer_id": layer_id,
            "src": f"{layer_id}.png",
            "kind": "approved_source_bridge" if layer_id in BRIDGES else "reference_sheet_part",
            "part_id": layer_id if layer_id.startswith("reference-part-") else None,
            "bridge_id": next((key for key in BRIDGES if key == layer_id), None),
            "target_role": role,
            "x": layer_x, "y": layer_y, "width": layer_width, "height": layer_height,
            "z_index": index + 1,
            "rotation_deg": 0, "scale": 1,
            "pivot_hint_normalized": [0.5, 0.5],
            "pivot_status": "alpha_overlap_candidate_estimate_not_approved",
        })

    joint_pivots = {}
    for name in REQUIRED_JOINT_PIVOTS:
        if name == "neck":
            x, y = 140.0, 180.0
            joint_pivots[name] = {
                "x": x, "y": y, "normalized": {"x": x/441, "y": y/755},
                "overlap_pixels": None, "minimum_overlap_pixels": None,
                "status": "source_coordinate_preserved_pending_candidate_visual_review",
                "approved": False,
            }
        else:
            x, y = 140.0, 240.0
            joint_pivots[name] = {
                "x": x, "y": y, "normalized": {"x": x/441, "y": y/755},
                "overlap_pixels": 100, "minimum_overlap_pixels": 40,
                "status": "candidate_estimate_pending_visual_joint_review",
                "approved": False,
            }
    layered = {
        "schema_version": 1,
        "status": "layered_candidate_exported_pending_joint_pivot_alignment",
        "activation_policy": "review_only_do_not_replace_live_or_production_layers",
        "canvas": {"width": 441, "height": 755},
        "layers": exports,
        "layer_count": 18,
        "joint_pivots": joint_pivots,
        "joint_pivot_count": len(joint_pivots),
        "primary_part_count": 15,
        "source_bridge_count": 3,
        "missing_or_unplaced": [],
        "joint_pivots_validated": False,
        "animation_ready": False,
        "production_layer_replacement_enabled": False,
        "facial_state_assets": {
            name: {"src": f"face-{name}.png"}
            for name in REQUIRED_FACE_STATES
        },
        "facial_state_build_status": "created_from_separate_eye_and_mouth_assets",
        "facial_state_alignment_status": "awaiting_candidate_head_alignment",
    }
    (source / "reference-part-assembled-layer-candidate.json").write_text(
        json.dumps(layered, indent=2), encoding="utf-8"
    )
    return source


class ReferencePartCharacterCandidateTests(unittest.TestCase):
    def test_builds_isolated_character_spec_from_assembled_reference_parts(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = make_source_bundle(root)
            output = root / "candidate"

            report = build_reference_part_character_candidate(source, output)
            candidate = json.loads((output / "character.json").read_text())
            alignment = candidate["reference_part_alignment"]

            self.assertEqual(
                report["status"],
                "candidate_character_spec_validated_pending_animation_visual_review",
            )
            self.assertEqual(report["candidate_character_layer_count"], 17)
            self.assertEqual(report["candidate_prop_count"], 2)
            self.assertEqual(set(candidate["head_variants"]), REQUIRED_FACE_STATES)
            self.assertEqual(candidate["props"]["bow"]["attach_to"], "left_hand")
            self.assertEqual(candidate["props"]["violin"]["attach_to"], "torso")
            self.assertFalse(alignment["production_layer_replacement_enabled"])
            self.assertFalse(alignment["joint_pivots_validated"])
            self.assertFalse(alignment["finger_articulation_enabled"])
            self.assertNotIn("base_art", candidate)
            self.assertNotIn("performance_base_mode", candidate)
            self.assertTrue(candidate["performance"]["instrument_performance"])
            self.assertTrue(
                all((output / layer["src"]).is_file()
                    for layer in candidate["layers"])
            )
            self.assertTrue(
                all((output / asset["src"]).is_file()
                    for asset in candidate["head_variants"].values())
            )
            persisted = json.loads(
                (output / "reference-part-character-candidate-report.json").read_text()
            )
            self.assertFalse(persisted["live_character_modified"])
            self.assertFalse(persisted["production_layer_replacement_enabled"])
            self.assertFalse(persisted["publishing_enabled"])

    def test_rejects_missing_candidate_wrist_pivot_before_build(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = make_source_bundle(root)
            path = source / "reference-part-assembled-layer-candidate.json"
            layered = json.loads(path.read_text())
            layered["joint_pivots"].pop("right_wrist")
            path.write_text(json.dumps(layered), encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "12 limb pivots plus the preserved neck"):
                build_reference_part_character_candidate(source, root / "candidate")


if __name__ == "__main__":
    unittest.main()
