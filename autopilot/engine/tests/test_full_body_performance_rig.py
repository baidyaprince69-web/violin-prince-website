import unittest
import numpy as np
from PIL import Image

from full_body_performance_rig import _foot_mask, _leg_layers


class FullBodyPerformanceRigTests(unittest.TestCase):
    def test_preserved_composite_keeps_body_and_cuts_only_bow_and_finger_regions(self):
        import json
        import tempfile
        from pathlib import Path
        from PIL import ImageDraw

        from full_body_performance_rig import _build_preserved_composite_base

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = Image.new("RGBA", (64, 64), (42, 48, 55, 255))
            draw = ImageDraw.Draw(source)
            draw.rectangle((8, 24, 22, 40), fill=(185, 122, 86, 255))
            # A white bow-hair stroke passes through the hand region; it must
            # be removed from the hand overlay and restored only by the bow prop.
            draw.line((26, 22, 21, 42), fill=(245, 238, 225, 255), width=3)
            original_hand_pixel = source.getpixel((14, 30))
            bow_alpha = np.zeros((64, 64), dtype=np.uint8)
            bow_alpha[6:58, 29:34] = 255

            finger_manifest = root / "fingers.json"
            finger_manifest.write_text(json.dumps({
                "schema_version": 1,
                "canvas": {"width": 64, "height": 64},
                "fingers": {
                    "index": {
                        "polygon": [[9, 9], [16, 9], [16, 19], [9, 19]],
                        "pivot": [13, 18]
                    }
                }
            }), encoding="utf-8")

            character = {
                "layers": [{
                    "id": "left_hand", "role": "left_hand", "src": "left_hand.png",
                    "x": 8, "y": 20, "width": 18, "height": 22, "z_index": 40,
                }],
                "joints": {"left_wrist": {"x": 0.25, "y": 0.55}},
            }
            result = _build_preserved_composite_base(
                source,
                root,
                bow_canvas_alpha=bow_alpha,
                finger_manifest_path=finger_manifest,
                character=character,
            )
            with Image.open(root / result["src"]) as opened:
                composite = opened.convert("RGBA")
            pixels = np.asarray(composite)
            self.assertEqual(composite.size, (64, 64))
            self.assertEqual(tuple(pixels[30, 14]), original_hand_pixel)
            self.assertEqual(int(pixels[12, 12, 3]), 0)
            self.assertEqual(int(pixels[30, 31, 3]), 255)
            self.assertLess(int(pixels[30, 31, :3].max()), 245)
            self.assertEqual(result["mode"], "intact_full_body_with_bow_and_finger_cutouts")
            self.assertTrue(result["preserves_original_arms_hands_legs_and_head"])
            self.assertGreater(result["bow_pixels_reconstructed"], 0)
            self.assertGreater(result["finger_pixels_separated"], 0)
            self.assertTrue(result["bow_grip_hand"]["excludes_original_bow_pixels"])
            hand_layer = next(layer for layer in character["layers"] if layer["role"] == "left_hand")
            self.assertEqual(hand_layer["src"], "bow-grip-hand.png")
            with Image.open(root / hand_layer["src"]) as hand_asset:
                hand_rgba = hand_asset.convert("RGBA")
                x0, y0, _x1, _y1 = result["bow_grip_hand"]["bbox"]
                self.assertEqual(hand_rgba.getpixel((26 - x0, 29 - y0))[3], 0,
                    "the bright bow hair must not be baked into the hand overlay")

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
