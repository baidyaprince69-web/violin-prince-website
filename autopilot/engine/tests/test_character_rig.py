"""Offline tests for the 2D character-rig and illustration-asset contracts."""
import unittest

from character_rig import CharacterRigError, validate_character_spec


class CharacterRigContractTests(unittest.TestCase):
    def valid_character(self):
        roles = [
            "torso", "head", "face",
            "left_upper_arm", "left_forearm", "left_hand",
            "right_upper_arm", "right_forearm", "right_hand",
        ]
        joints = [
            "neck", "left_shoulder", "left_elbow", "left_wrist",
            "right_shoulder", "right_elbow", "right_wrist",
        ]
        return {
            "id": "guide",
            "canvas": {"width": 320, "height": 240},
            "layers": [
                {"id": role, "role": role, "src": role + ".png",
                 "x": 10, "y": 20, "width": 100, "height": 120}
                for role in roles
            ],
            "joints": {name: {"x": 0.5, "y": 0.5} for name in joints},
            "expressions": {
                "neutral": "neutral.png",
                "curious": "curious.png",
            },
        }

    def test_accepts_complete_detailed_layered_rig(self):
        result = validate_character_spec(self.valid_character())
        self.assertEqual(result["id"], "guide")
        self.assertEqual(len(result["layers"]), 9)
        self.assertIn("curious", result["expressions"])

    def test_full_body_rig_requires_six_leg_parts_and_six_lower_body_joints(self):
        character = self.valid_character()
        character["body_scope"] = "full_body"
        leg_roles = [
            "left_thigh", "left_shin", "left_foot",
            "right_thigh", "right_shin", "right_foot",
            "right_index_finger", "right_middle_finger",
            "right_ring_finger", "right_little_finger",
        ]
        leg_joints = [
            "left_hip", "left_knee", "left_ankle",
            "right_hip", "right_knee", "right_ankle",
            "right_index_knuckle", "right_middle_knuckle",
            "right_ring_knuckle", "right_little_knuckle",
        ]
        character["layers"].extend({
            "id": role, "role": role, "src": role + ".png",
            "x": 10, "y": 20, "width": 100, "height": 120,
        } for role in leg_roles)
        character["joints"].update({
            name: {"x": 0.5, "y": 0.8} for name in leg_joints
        })
        character["props"] = {
            "violin": {
                "src": "violin.png", "x": 10, "y": 20,
                "width": 60, "height": 24, "pivot_x": 0.2, "pivot_y": 0.5,
            },
            "bow": {
                "src": "bow.png", "x": 20, "y": 10,
                "width": 8, "height": 70, "pivot_x": 0.1, "pivot_y": 0.95,
            },
        }
        result = validate_character_spec(character)
        self.assertEqual(result["body_scope"], "full_body")
        self.assertEqual({item["role"] for item in result["layers"]} & set(leg_roles), set(leg_roles))
        self.assertEqual(set(result["props"]), {"violin", "bow"})
        self.assertEqual(result["props"]["bow"]["pivot_y"], 0.95)

    def test_full_body_contract_rejects_missing_knee_joint(self):
        character = self.valid_character()
        character["body_scope"] = "full_body"
        leg_roles = [
            "left_thigh", "left_shin", "left_foot",
            "right_thigh", "right_shin", "right_foot",
            "right_index_finger", "right_middle_finger",
            "right_ring_finger", "right_little_finger",
        ]
        for role in leg_roles:
            character["layers"].append({
                "id": role, "role": role, "src": role + ".png",
                "x": 10, "y": 20, "width": 100, "height": 120,
            })
        for name in (
            "left_hip", "left_knee", "left_ankle",
            "right_hip", "right_knee", "right_ankle",
            "right_index_knuckle", "right_middle_knuckle",
            "right_ring_knuckle", "right_little_knuckle",
        ):
            character["joints"][name] = {"x": 0.5, "y": 0.8}
        character["joints"].pop("left_knee")
        with self.assertRaisesRegex(CharacterRigError, "left_knee"):
            validate_character_spec(character)

    def test_rejects_missing_hand_layer(self):
        character = self.valid_character()
        character["layers"] = [
            layer for layer in character["layers"] if layer["role"] != "left_hand"
        ]
        with self.assertRaisesRegex(CharacterRigError, "left_hand"):
            validate_character_spec(character)

    def test_rejects_incomplete_joint_map(self):
        character = self.valid_character()
        character["joints"].pop("right_wrist")
        with self.assertRaisesRegex(CharacterRigError, "right_wrist"):
            validate_character_spec(character)

    def test_illustration_factory_stages_all_parts_and_expression_assets(self):
        import tempfile
        from pathlib import Path
        from PIL import Image
        from illustration_asset_factory import prepare_character_assets

        with tempfile.TemporaryDirectory() as folder:
            source_root = Path(folder) / "source"
            destination_root = Path(folder) / "staged"
            source_root.mkdir()
            character = self.valid_character()
            for layer in character["layers"]:
                Image.new("RGBA", (32, 32), (180, 120, 60, 255)).save(source_root / layer["src"])
            Image.new("RGBA", (32, 32), (200, 160, 130, 255)).save(source_root / "neutral.png")
            Image.new("RGBA", (32, 32), (200, 160, 130, 255)).save(source_root / "curious.png")

            staged = prepare_character_assets(
                {"characters": [character]},
                source_root=source_root,
                destination_root=destination_root,
            )
            self.assertEqual(len(staged), 1)
            self.assertEqual(len(staged[0]["layers"]), 9)
            self.assertEqual(staged[0]["canvas"], {"width": 320, "height": 240})
            self.assertIn("neutral", staged[0]["expressions"])
            self.assertIn("curious", staged[0]["expressions"])
            self.assertTrue(all(Path(layer["src"]).is_file() for layer in staged[0]["layers"]))
            self.assertTrue(all(Path(expression["src"]).is_file() for expression in staged[0]["expressions"].values()))
            self.assertTrue((destination_root / "manifest.json").is_file())

    def test_pose_assets_are_validated_and_staged_for_the_daily_pipeline(self):
        import tempfile
        from pathlib import Path
        from PIL import Image
        from illustration_asset_factory import prepare_character_assets

        with tempfile.TemporaryDirectory() as folder:
            source_root = Path(folder) / "source"
            destination_root = Path(folder) / "staged"
            source_root.mkdir()
            character = self.valid_character()
            character["pose_assets"] = {"point_left": {"src": "pose-point-left.png"}}
            for layer in character["layers"]:
                Image.new("RGBA", (32, 32), (180, 120, 60, 255)).save(source_root / layer["src"])
            for name in ("neutral.png", "curious.png", "pose-point-left.png"):
                Image.new("RGBA", (32, 32), (200, 160, 130, 255)).save(source_root / name)

            staged = prepare_character_assets(
                {"characters": [character]},
                source_root=source_root,
                destination_root=destination_root,
            )
            self.assertIn("point_left", staged[0]["pose_assets"])
            pose_path = Path(staged[0]["pose_assets"]["point_left"]["src"])
            self.assertTrue(pose_path.is_file())
            self.assertEqual(pose_path.name, "pose-point_left.png")

    def test_rejects_empty_pose_asset_sources(self):
        character = self.valid_character()
        character["pose_assets"] = {"wave": {"src": " "}}
        with self.assertRaisesRegex(CharacterRigError, "has no image source"):
            validate_character_spec(character)

    def test_illustration_factory_fails_closed_when_a_layer_image_is_missing(self):
        import tempfile
        from pathlib import Path
        from PIL import Image
        from illustration_asset_factory import IllustrationAssetError, prepare_character_assets

        with tempfile.TemporaryDirectory() as folder:
            source_root = Path(folder) / "source"
            destination_root = Path(folder) / "staged"
            source_root.mkdir()
            character = self.valid_character()
            for layer in character["layers"]:
                if layer["role"] != "left_hand":
                    Image.new("RGBA", (32, 32), (180, 120, 60, 255)).save(source_root / layer["src"])
            Image.new("RGBA", (32, 32), (200, 160, 130, 255)).save(source_root / "neutral.png")
            Image.new("RGBA", (32, 32), (200, 160, 130, 255)).save(source_root / "curious.png")
            with self.assertRaises(IllustrationAssetError):
                prepare_character_assets(
                    {"characters": [character]},
                    source_root=source_root,
                    destination_root=destination_root,
                )


if __name__ == "__main__":
    unittest.main()
