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



    def test_full_body_leg_and_finger_roles_require_complete_joint_chains(self):
        character = self.valid_character()
        extra_roles = [
            "left_thigh", "left_calf", "left_foot",
            "right_thigh", "right_calf", "right_foot",
            "finger_index", "finger_middle", "finger_ring", "finger_little",
        ]
        for role in extra_roles:
            character["layers"].append({
                "id": role, "role": role, "src": role + ".png",
                "x": 0, "y": 0, "width": 30, "height": 30,
            })
        for name in (
            "left_hip", "left_knee", "left_ankle",
            "right_hip", "right_knee", "right_ankle",
            "right_index_base", "right_middle_base",
            "right_ring_base", "right_little_base",
        ):
            character["joints"][name] = {"x": 0.5, "y": 0.5}
        character["props"] = {
            "violin": {
                "src": "violin.webp", "x": 10, "y": 12, "width": 90, "height": 32,
                "pivot_x": 0.2, "pivot_y": 0.5, "z_index": 25, "attach_to": "torso",
            },
            "bow": {
                "src": "bow.webp", "x": 30, "y": 4, "width": 12, "height": 96,
                "pivot_x": 0.1, "pivot_y": 0.95, "z_index": 35, "attach_to": "left_hand",
            },
        }
        result = validate_character_spec(character)
        self.assertEqual(len(result["props"]), 2)
        self.assertEqual(result["props"]["bow"]["attach_to"], "left_hand")
        self.assertTrue(set(extra_roles).issubset({layer["role"] for layer in result["layers"]}))

    def test_rejects_partial_leg_chains_and_unknown_instrument_attachment(self):
        character = self.valid_character()
        character["layers"].append({
            "id": "left_thigh", "role": "left_thigh", "src": "left_thigh.png",
            "x": 0, "y": 0, "width": 30, "height": 60,
        })
        with self.assertRaisesRegex(CharacterRigError, "all six leg layers"):
            validate_character_spec(character)

        character = self.valid_character()
        character["props"] = {
            "bow": {
                "src": "bow.webp", "x": 1, "y": 2, "width": 10, "height": 80,
                "attach_to": "unknown_joint",
            }
        }
        with self.assertRaisesRegex(CharacterRigError, "unknown rig role"):
            validate_character_spec(character)

    def test_asset_factory_stages_instrument_props_with_the_character(self):
        import tempfile
        from pathlib import Path
        from PIL import Image
        from illustration_asset_factory import prepare_character_assets

        with tempfile.TemporaryDirectory() as folder:
            source_root = Path(folder) / "source"
            destination_root = Path(folder) / "staged"
            source_root.mkdir()
            character = self.valid_character()
            character["props"] = {
                "violin": {
                    "src": "violin.webp", "x": 10, "y": 12, "width": 90, "height": 32,
                    "pivot_x": 0.2, "pivot_y": 0.5, "z_index": 25, "attach_to": "torso",
                },
                "bow": {
                    "src": "bow.webp", "x": 30, "y": 4, "width": 12, "height": 96,
                    "pivot_x": 0.1, "pivot_y": 0.95, "z_index": 35, "attach_to": "left_hand",
                },
            }
            for layer in character["layers"]:
                Image.new("RGBA", (32, 32), (180, 120, 60, 255)).save(source_root / layer["src"])
            for name in ("neutral.png", "curious.png"):
                Image.new("RGBA", (32, 32), (200, 160, 130, 255)).save(source_root / name)
            Image.new("RGBA", (90, 32), (160, 80, 30, 255)).save(source_root / "violin.webp")
            Image.new("RGBA", (12, 96), (50, 35, 25, 255)).save(source_root / "bow.webp")

            staged = prepare_character_assets(
                {"characters": [character]},
                source_root=source_root,
                destination_root=destination_root,
            )
            self.assertEqual(set(staged[0]["props"]), {"violin", "bow"})
            self.assertTrue(Path(staged[0]["props"]["violin"]["src"]).is_file())
            self.assertTrue(Path(staged[0]["props"]["bow"]["src"]).is_file())

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
