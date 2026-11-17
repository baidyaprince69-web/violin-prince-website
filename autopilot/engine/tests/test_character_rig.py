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
            self.assertIn("neutral", staged[0]["expressions"])
            self.assertIn("curious", staged[0]["expressions"])
            self.assertTrue(all(Path(layer["src"]).is_file() for layer in staged[0]["layers"]))
            self.assertTrue(all(Path(expression["src"]).is_file() for expression in staged[0]["expressions"].values()))
            self.assertTrue((destination_root / "manifest.json").is_file())

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
