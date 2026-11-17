from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from character_rig import REQUIRED_JOINTS, REQUIRED_LAYER_ROLES
from character_visual_validation import JOINT_LAYER_PAIRS, verify_character_visuals


class CharacterVisualValidationTests(unittest.TestCase):
    def _bundle(self, root: Path):
        layers = []
        roles = sorted(REQUIRED_LAYER_ROLES)
        for index, role in enumerate(roles):
            image = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
            draw = ImageDraw.Draw(image)
            draw.ellipse((35, 35, 65, 65), fill=(255, 120, 80, 255))
            image.save(root / f"{role}.png")
            layers.append({
                "id": role,
                "role": role,
                "src": f"{role}.png",
                "x": 0,
                "y": 0,
                "width": 100,
                "height": 100,
                "z_index": index + 1,
            })
        joints = {name: {"x": 0.5, "y": 0.5} for name in REQUIRED_JOINTS}
        return {
            "id": "violin-prince",
            "canvas": {"width": 100, "height": 100},
            "layers": layers,
            "joints": joints,
        }

    def test_layer_dimensions_and_all_seven_joint_anchors_are_reported(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            character = self._bundle(root)
            report = verify_character_visuals(character, root)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["layer_count"], len(REQUIRED_LAYER_ROLES))
        self.assertEqual(report["joint_count"], len(REQUIRED_JOINTS))
        self.assertEqual(
            {item["joint"] for item in report["joint_alignment"]},
            set(JOINT_LAYER_PAIRS),
        )
        self.assertTrue(report["visual_review_required"])

    def test_empty_layer_is_a_hard_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            character = self._bundle(root)
            Image.new("RGBA", (100, 100), (0, 0, 0, 0)).save(root / "head.png")
            report = verify_character_visuals(character, root)
        self.assertEqual(report["status"], "failed")
        self.assertIn("empty_alpha_layer:head", report["errors"])

    def test_absolute_staged_layer_paths_inside_bundle_are_accepted(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            character = self._bundle(root)
            for layer in character["layers"]:
                layer["src"] = str((root / layer["src"]).resolve())
            report = verify_character_visuals(character, root)
        self.assertEqual(report["status"], "passed")

    def test_layer_outside_canvas_is_a_hard_failure(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            character = self._bundle(root)
            head = next(item for item in character["layers"] if item["role"] == "head")
            head["x"] = 5
            report = verify_character_visuals(character, root)
        self.assertEqual(report["status"], "failed")
        self.assertIn("layer_outside_canvas:head", report["errors"])


if __name__ == "__main__":
    unittest.main()
