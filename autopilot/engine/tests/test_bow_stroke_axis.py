import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from create_full_body_performance_preview import derive_bow_stroke_axis


class BowStrokeAxisTests(unittest.TestCase):
    def test_axis_follows_sprite_long_axis_from_grip_to_tip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "diagonal-bow.png"
            image = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
            ImageDraw.Draw(image).line((12, 82, 91, 8), fill=(220, 200, 160, 255), width=5)
            image.save(path)
            axis = derive_bow_stroke_axis(path, {"pivot_x": 0.12, "pivot_y": 0.82})
        self.assertGreater(axis["x"], 0.0)
        self.assertLess(axis["y"], 0.0)
        self.assertAlmostEqual((axis["x"] ** 2 + axis["y"] ** 2) ** 0.5, 1.0, places=5)

    def test_empty_alpha_silhouette_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "empty-bow.png"
            Image.new("RGBA", (100, 100), (0, 0, 0, 0)).save(path)
            with self.assertRaisesRegex(ValueError, "alpha silhouette"):
                derive_bow_stroke_axis(path, {"pivot_x": 0.1, "pivot_y": 0.8})


if __name__ == "__main__":
    unittest.main()
