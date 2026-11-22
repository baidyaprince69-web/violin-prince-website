import unittest
import numpy as np
from PIL import Image

from full_body_performance_rig import _foot_mask, _leg_layers


class FullBodyPerformanceRigTests(unittest.TestCase):
    def test_shoe_mask_isolated_from_trouser_and_connected_to_bottom(self):
        width, height, split_x = 100, 120, 50
        rgb = np.full((height, width, 3), 220, dtype=np.uint8)
        alpha = np.zeros((height, width), dtype=np.uint8)
        # Lower trouser leg ends just above the shoe band.
        rgb[82:112, 18:39] = 32
        alpha[82:112, 18:39] = 255
        # Shoe is a distinct dark connected foreground component at the bottom.
        rgb[111:120, 12:43] = 28
        alpha[111:120, 12:43] = 255
        mask = _foot_mask(rgb, alpha, side="left", split_x=split_x)
        self.assertGreater(int(mask.sum()), 100)
        self.assertTrue(mask[116, 25])
        self.assertFalse(mask[90, 25])

    def test_leg_layers_create_hip_knee_ankle_anchors_for_both_sides(self):
        width, height = 240, 300
        pixels = np.zeros((height, width, 4), dtype=np.uint8)
        labels = np.zeros((height, width), dtype=np.uint8)
        # A torso with two distinct leg columns and a gap between the shoes.
        pixels[48:126, 92:148] = (30, 31, 34, 255)
        labels[48:126, 92:148] = 2
        pixels[120:186, 88:116] = (35, 35, 38, 255)
        pixels[120:186, 126:154] = (35, 35, 38, 255)
        labels[120:186, 88:116] = 5
        labels[120:186, 126:154] = 5
        pixels[180:270, 88:112] = (32, 33, 35, 255)
        pixels[180:270, 132:156] = (32, 33, 35, 255)
        labels[180:270, 88:112] = 6
        labels[180:270, 132:156] = 6
        pixels[267:299, 72:115] = (18, 18, 20, 255)
        pixels[267:299, 130:173] = (18, 18, 20, 255)
        source = Image.fromarray(pixels, mode="RGBA")
        character = {"layers":[{"role":"torso","x":92,"y":48,"width":56,"height":78}]}

        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as folder:
            layers, joints, report = _leg_layers(source, labels, character, Path(folder))
            self.assertEqual(len(layers), 6)
            for side in ("left", "right"):
                for joint in ("hip", "knee", "ankle"):
                    self.assertIn(side + "_" + joint, joints)
                    self.assertGreaterEqual(joints[side + "_" + joint]["x"], 0)
                    self.assertLessEqual(joints[side + "_" + joint]["x"], 1)
            self.assertTrue(report["review_required"])
            z_by_role = {layer["role"]: layer["z_index"] for layer in layers}
            for side in ("left", "right"):
                self.assertLess(z_by_role[side + "_thigh"], z_by_role[side + "_calf"])
                self.assertLess(z_by_role[side + "_calf"], z_by_role[side + "_foot"])
            self.assertTrue(all((Path(folder) / layer["src"]).is_file() for layer in layers))


if __name__ == "__main__":
    unittest.main()
