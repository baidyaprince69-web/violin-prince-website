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


if __name__ == "__main__":
    unittest.main()
