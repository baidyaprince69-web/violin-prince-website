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
    "reference-part-027": "left_thigh",
    "reference-part-028": "right_thigh",
    "reference-part-030": "left_calf",
    "reference-part-031": "right_calf",
    "reference-part-032": "left_foot",
    "reference-part-033": "right_foot",
}
BRIDGES = {
    "source-bridge-head-neck": "neck_bridge",
    "source-bridge-right_forearm": "right_forearm",
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
        "preserved-right-hand",
        "reference-part-027", "reference-part-028", "reference-part-030",
        "reference-part-031", "reference-part-032", "reference-part-033",
        "source-bridge-head-neck", "source-bridge-right_forearm",
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
    write_image(source / "pose-resting_hands.png")
    write_image(source / "base-art.png")
    preserved_source = Image.new("RGBA", (441, 755), (0, 0, 0, 0))
    preserved_draw = ImageDraw.Draw(preserved_source)
    preserved_draw.rectangle((300, 181, 405, 196), fill=(115, 65, 35, 255))
    preserved_draw.polygon(
        [
            (324, 169), (379, 169), (382, 173), (387, 183),
            (389, 191), (383, 201), (377, 206), (372, 214),
            (366, 221), (360, 230), (352, 238), (344, 246),
            (337, 251), (330, 249), (326, 244), (324, 237),
            (325, 229), (327, 219), (328, 209), (325, 201),
            (321, 195), (320, 188), (322, 180),
        ],
        fill=(177, 123, 89, 255),
    )
    # A small exposed violin-neck area between the fingers must remain transparent.
    preserved_draw.rectangle((382, 185, 388, 191), fill=(87, 66, 44, 255))
    preserved_draw.line((337, 178, 342, 199), fill=(75, 42, 31, 255), width=2)
    preserved_draw.line((351, 176, 356, 201), fill=(75, 42, 31, 255), width=2)
    preserved_draw.line((365, 176, 369, 200), fill=(75, 42, 31, 255), width=2)
    preserved_source.save(source / "preserved-full-body-source.png")

    original_joints = {
        name: {"x": 0.5, "y": 0.5}
        for name in (
            "neck", "left_shoulder", "left_elbow", "left_wrist",
            "right_shoulder", "right_elbow", "right_wrist",
            "left_hip", "right_hip", "left_knee", "right_knee",
            "left_ankle", "right_ankle",
        )
    }
    original_joints["right_wrist"] = {
        "x": 350.8 / 441,
        "y": 239.3 / 755,
    }
    original = {
        "id": "violin-prince",
        "canvas": {"width": 441, "height": 755},
        "base_art": {"src": "base-art.png"},
        "performance_base_mode": "segmented_source_body",
        "layers": [
            {
                "id": "torso", "role": "torso", "src": "base-art.png",
                "x": 100, "y": 200, "width": 80, "height": 80,
                "pivot_x": 0.5, "pivot_y": 0.5,
            },
            {
                "id": "right_hand", "role": "right_hand", "src": "preserved-right-hand.png",
                "x": 321, "y": 170, "width": 67, "height": 78,
                "pivot_x": 0.5, "pivot_y": 0.5, "z_index": 42,
            },
        ],
        "joints": original_joints,
        "expressions": {
            "neutral": {"src": "expression-neutral.png"},
            "happy": {"src": "expression-happy.png"},
        },
        "head_variants": facial_assets,
        "head_angles": {},
        "pose_assets": {
            "resting_hands": {"src": "pose-resting_hands.png"},
        },
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
    write_image(source / "reference-part-assembled-candidate.png")

    exports = []
    role_by_id = {
        **PART_ROLES,
        "reference-part-001": "head",
        "reference-part-022": "unused_reference_hand_variant",
        "reference-part-025": "violin",
        **BRIDGES,
    }
    z_by_id = {
        "reference-part-006": 51,
        "source-bridge-right_forearm": 52,
        "reference-part-025": 60,
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
            "z_index": z_by_id.get(layer_id, index + 1),
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
    def test_uses_one_coherent_master_artwork_and_keeps_mismatched_cutouts_inactive(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = make_source_bundle(root)
            output = root / "candidate"

            expected_source_bytes = (source / "preserved-full-body-source.png").read_bytes()
            report = build_reference_part_character_candidate(source, output)
            candidate = json.loads((output / "character.json").read_text())
            alignment = candidate["reference_part_alignment"]

            self.assertEqual(
                report["status"],
                "candidate_source_composite_validated_pending_animation_visual_review",
            )
            self.assertEqual(report["candidate_character_layer_count"], 9)
            self.assertEqual(report["candidate_prop_count"], 0)
            self.assertEqual(report["visible_composite_count"], 1)
            self.assertEqual(report["source_parts_used"], [])
            self.assertEqual(report["source_bridges_used"], [])
            self.assertEqual(report["reference_cutouts_activated"], False)
            self.assertEqual(candidate["base_art"]["src"], "preserved-full-body-source.png")
            self.assertEqual(candidate["performance_base_mode"], "intact_full_body_source_composite")
            self.assertEqual((output / candidate["base_art"]["src"]).read_bytes(), expected_source_bytes)
            self.assertEqual(candidate["base_art"]["x"], 0)
            self.assertEqual(candidate["base_art"]["y"], 0)
            self.assertEqual(candidate["base_art"]["width"], 441)
            self.assertEqual(candidate["base_art"]["height"], 755)
            self.assertEqual(candidate["head_variants"], {})
            self.assertEqual(candidate["head_angles"], {})
            self.assertEqual(candidate["props"], {})
            self.assertEqual(candidate["pose_assets"], {})
            self.assertEqual(
                {layer["role"] for layer in candidate["layers"]},
                {
                    "torso", "head", "face",
                    "left_upper_arm", "left_forearm", "left_hand",
                    "right_upper_arm", "right_forearm", "right_hand",
                },
            )
            self.assertTrue(all(
                layer["src"] == "transparent-character-anchor.png"
                and layer["activation_policy"] == "transparent_no_duplicate_body_art"
                for layer in candidate["layers"]
            ))
            with Image.open(output / "transparent-character-anchor.png") as anchor:
                self.assertEqual(anchor.size, (1, 1))
                self.assertEqual(anchor.getpixel((0, 0))[3], 0)
            self.assertEqual(set(candidate["expressions"]), {"neutral", "alternate"})
            self.assertTrue(all(
                value["src"] == "transparent-character-anchor.png"
                for value in candidate["expressions"].values()
            ))
            self.assertEqual(
                alignment["assembly_method"],
                "single_source_preserved_full_body_composite_no_pose_mismatched_cutouts",
            )
            self.assertEqual(alignment["reference_parts_activated"], 0)
            self.assertEqual(
                alignment["right_hand_art_source"],
                "integrated_original_full_body_art_with_authored_fingerboard_grip",
            )
            self.assertFalse(alignment["production_layer_replacement_enabled"])
            self.assertFalse(alignment["joint_pivots_validated"])
            self.assertFalse(alignment["finger_articulation_enabled"])
            self.assertFalse(candidate["performance"]["fingering_articulation_enabled"])
            self.assertEqual(
                candidate["performance"]["compositing_mode"],
                "intact_source_full_body_composite",
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
