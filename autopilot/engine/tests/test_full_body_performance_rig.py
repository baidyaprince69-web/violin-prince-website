import unittest
import numpy as np
from PIL import Image

from full_body_performance_rig import (
    _authored_performance_layers,
    _build_segmented_source_base,
    _clip_hand_from_violin_prop,
    _foot_mask,
    _leg_layers,
)
from character_autorig import _skin_material_mask


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
            bow_line = Image.new("L", (64, 64), 0)
            ImageDraw.Draw(bow_line).line((26, 22, 21, 42), fill=255, width=3)
            bow_alpha = np.maximum(bow_alpha, np.asarray(bow_line, dtype=np.uint8))
            source.crop((8, 20, 26, 42)).save(root / "left_hand.png")

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

    def test_source_aligned_manifest_extracts_twelve_independent_limb_layers(self):
        import json
        import tempfile
        from pathlib import Path

        asset_root = (
            Path(__file__).resolve().parents[1]
            / "assets" / "characters" / "violin-prince-performance"
        )
        source_path = asset_root / "master-character-performance.webp"
        manifest_path = asset_root / "performance-regions.json"
        prop_manifest = json.loads(
            (asset_root / "instrument-props.json").read_text(encoding="utf-8")
        )
        with Image.open(source_path) as opened:
            source = opened.convert("RGBA")

        prop_masks = {}
        for name, specification in prop_manifest["props"].items():
            with Image.open(asset_root / specification["src"]) as opened:
                prop_alpha = np.asarray(opened.convert("RGBA").getchannel("A"), dtype=np.uint8)
            canvas = np.zeros((source.height, source.width), dtype=np.uint8)
            x, y = int(specification["x"]), int(specification["y"])
            canvas[y:y + prop_alpha.shape[0], x:x + prop_alpha.shape[1]] = prop_alpha
            prop_masks[name] = canvas

        with tempfile.TemporaryDirectory() as folder:
            layers, joints, report, moving = _authored_performance_layers(
                source,
                Path(folder),
                regions_manifest_path=manifest_path,
                prop_masks=prop_masks,
            )
            self.assertEqual(len(layers), 12)
            self.assertEqual(report["independent_layer_count"], 12)
            self.assertEqual(set(report["parts"]), {
                "left_upper_arm", "left_forearm", "left_hand",
                "right_upper_arm", "right_forearm", "right_hand",
                "left_thigh", "left_calf", "left_foot",
                "right_thigh", "right_calf", "right_foot",
            })
            self.assertEqual(len(joints), 12)
            self.assertGreater(int(moving.sum()), 30000)
            self.assertLessEqual(max(report["joint_overlap_pixels"].values()), 500)
            self.assertGreater(report["parts"]["left_hand"]["pixel_area"], 500)
            self.assertGreater(report["parts"]["right_hand"]["pixel_area"], 700)
            self.assertTrue(all((Path(folder) / layer["src"]).is_file() for layer in layers))

    def test_skin_mask_rejects_violin_wood_inside_hand_region(self):
        pixels = np.full((40, 60, 4), (30, 30, 30, 255), dtype=np.uint8)
        pixels[8:25, 5:22, :3] = (173, 121, 88)   # illustrated hand skin
        pixels[8:25, 34:51, :3] = (182, 98, 38)   # warm violin varnish
        image = Image.fromarray(pixels, mode="RGBA")
        allowed = np.zeros((40, 60), dtype=bool)
        allowed[2:31, 2:55] = True
        mask = _skin_material_mask(
            image,
            allowed,
            thresholds={
                "red_min": 120, "red_max": 240, "green_min": 70, "blue_min": 55,
                "red_minus_green_min": 20, "green_minus_blue_min": 10,
                "red_minus_blue_min": 35,
            },
        )
        self.assertTrue(mask[15, 14], "skin pixels must remain in the source-derived hand")
        self.assertFalse(mask[15, 43], "low-blue violin wood must not be classified as a finger")

    def test_clips_source_hand_from_violin_prop_without_changing_other_alpha(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            hand = Image.new("RGBA", (18, 16), (170, 115, 85, 0))
            hand_pixels = np.asarray(hand, dtype=np.uint8).copy()
            hand_pixels[4:13, 5:16, 3] = 255
            hand = Image.fromarray(hand_pixels, mode="RGBA")
            hand.save(root / "right_hand.png")

            violin = Image.new("RGBA", (30, 20), (125, 62, 30, 255))
            violin.save(root / "prop-violin.webp", format="WEBP", lossless=True)

            report = _clip_hand_from_violin_prop(
                root,
                violin_specification={"src": "violin-prop.webp", "x": 20, "y": 15},
                hand_layer={
                    "src": "right_hand.png",
                    "x": 27, "y": 20,
                    "width": 18, "height": 16,
                },
                dilation_radius=1,
            )
            with Image.open(root / "prop-violin.webp") as opened:
                result = np.asarray(opened.convert("RGBA"), dtype=np.uint8)

            self.assertEqual(report["method"], "source_hand_alpha_cutout_plus_one_pixel_seam")
            self.assertGreater(report["pixels_removed"], 40)
            self.assertEqual(int(result[5, 8, 3]), 0,
                "overlapping fretting-hand pixels must be transparent in the violin sprite")
            self.assertEqual(int(result[0, 0, 3]), 255,
                "the violin body outside the hand overlap must remain opaque")

    def test_segmented_source_base_preserves_untouched_pixels_and_alpha(self):
        import tempfile
        from pathlib import Path
        import cv2

        source = Image.new("RGBA", (80, 80), (42, 48, 55, 255))
        pixels = np.asarray(source, dtype=np.uint8).copy()
        pixels[12:68, 12:68, :3] = (30, 35, 40)
        pixels[12:68, 12:68, 3] = 255
        source = Image.fromarray(pixels, mode="RGBA")
        original = np.asarray(source, dtype=np.uint8)

        moving = np.zeros((80, 80), dtype=bool)
        moving[22:52, 20:35] = True
        bow = np.zeros((80, 80), dtype=np.uint8)
        bow[18:58, 38:41] = 255
        violin = np.zeros((80, 80), dtype=np.uint8)
        violin[28:50, 48:63] = 255

        with tempfile.TemporaryDirectory() as folder:
            report = _build_segmented_source_base(
                source,
                Path(folder),
                bow_canvas_alpha=bow,
                violin_canvas_alpha=violin,
                moving_mask=moving,
            )
            with Image.open(Path(folder) / report["src"]) as opened:
                output = np.asarray(opened.convert("RGBA"), dtype=np.uint8)

        self.assertEqual(report["mode"], "segmented_source_body")
        self.assertLess(report["z_index"], 4,
            "the underpaint must remain behind the thigh/calf/foot sprites")
        self.assertGreater(report["pixels_cut_from_source"], 900)
        np.testing.assert_array_equal(output[:, :, 3], original[:, :, 3])
        untouched = np.ones((80, 80), dtype=bool)
        cut = cv2.dilate(
            (moving | (bow > 12) | (violin > 12)).astype(np.uint8),
            np.ones((5, 5), dtype=np.uint8),
        ) > 0
        cut &= original[:, :, 3] > 12
        untouched &= ~cut
        np.testing.assert_array_equal(output[untouched], original[untouched])
        self.assertGreater(report["violin_pixels_reconstructed"], 0)
        self.assertGreater(report["bow_pixels_reconstructed"], 0)
        self.assertTrue(report["source_alpha_preserved"])
        self.assertTrue(report["source_pixels_outside_cut_mask_preserved"])

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
