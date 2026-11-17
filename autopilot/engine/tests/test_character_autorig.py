"""Offline regression tests for SCHP mask assembly and hidden-area reconstruction."""
import unittest

import numpy as np
from PIL import Image

from character_autorig import (
    AutoRigError,
    ManualReviewRequired,
    _repair_hidden_area,
    _save_pose_plate,
    separate_from_parsing,
)


class CharacterAutoRigTests(unittest.TestCase):
    def synthetic_maps(self):
        width, height = 160, 112
        body = np.zeros((height, width), dtype=np.uint8)
        detail = np.zeros((height, width), dtype=np.uint8)
        body[7:31, 67:93] = 1
        body[31:98, 54:106] = 2
        body[39:53, 35:58] = 3
        body[39:53, 102:125] = 3
        body[43:58, 18:38] = 4
        body[43:58, 122:142] = 4
        detail[8:30, 72:88] = 11
        detail[5:17, 67:93] = 2
        detail[39:58, 18:58] = 14
        detail[39:58, 102:142] = 15
        body_conf = np.full((height, width), 0.94, dtype=np.float32)
        detail_conf = np.full((height, width), 0.92, dtype=np.float32)
        return body, body_conf, detail, detail_conf

    def test_creates_nine_nonempty_layers_and_seven_joint_anchors(self):
        body, body_conf, detail, detail_conf = self.synthetic_maps()
        image = Image.new("RGB", (160, 112), (30, 30, 36))
        masks, repaired, report, joints = separate_from_parsing(
            image, body, body_conf, detail, detail_conf,
            hand_fraction=0.62, max_local_inpaint_ratio=0.12,
        )
        self.assertEqual(len(masks), 9)
        self.assertEqual(len(joints), 7)
        self.assertEqual(repaired.size, image.size)
        for role, region in masks.items():
            self.assertGreater(int(region.sum()), 20, role)
        for point in joints.values():
            self.assertTrue(0 <= point["x"] <= 1)
            self.assertTrue(0 <= point["y"] <= 1)
        self.assertTrue(report["needs_visual_review"])

    def test_coarse_arm_side_fallback_when_atr_detects_only_one_side(self):
        body, body_conf, detail, detail_conf = self.synthetic_maps()
        detail[39:58, 102:142] = 0
        image = Image.new("RGB", (160, 112), (30, 30, 36))
        masks, _, report, joints = separate_from_parsing(
            image, body, body_conf, detail, detail_conf,
            hand_fraction=0.62, max_local_inpaint_ratio=0.12,
        )
        self.assertEqual(len(masks), 9)
        self.assertEqual(len(joints), 7)
        self.assertEqual(report["arm_side_source"], "pascal_coarse_screen_split")
        self.assertGreater(masks["left_hand"].sum(), 20)
        self.assertGreater(masks["right_hand"].sum(), 20)

    def test_large_hidden_area_fails_closed_without_lama(self):
        image = Image.new("RGB", (80, 80), (100, 100, 100))
        hole = np.zeros((80, 80), dtype=bool)
        hole[15:65, 15:65] = True
        with self.assertRaises(ManualReviewRequired):
            _repair_hidden_area(image, hole, max_local_ratio=0.02)

    def test_small_hidden_area_is_repaired(self):
        rgb = np.full((20, 20, 3), (120, 80, 60), dtype=np.uint8)
        image = Image.fromarray(rgb)
        hole = np.zeros((20, 20), dtype=bool)
        hole[9:11, 9:11] = True
        result, method, ratio = _repair_hidden_area(image, hole, max_local_ratio=0.1)
        self.assertEqual(method, "local_neighbour_propagation")
        self.assertGreater(ratio, 0)
        self.assertEqual(result.getpixel((9, 9)), (120, 80, 60))

    def test_pose_reference_plate_removes_near_white_background(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "pose.jpg"
            output = Path(folder) / "pose.png"
            image = Image.new("RGB", (80, 60), (255, 255, 255))
            for y in range(10, 50):
                for x in range(20, 60):
                    image.putpixel((x, y), (30, 40, 50))
            # Tiny black JPEG speck in the backdrop should be removed by the
            # closing pass, while an enclosed white eye/highlight stays opaque.
            for y in range(3, 6):
                for x in range(3, 6):
                    image.putpixel((x, y), (0, 0, 0))
            for y in range(25, 30):
                for x in range(35, 40):
                    image.putpixel((x, y), (255, 255, 255))
            image.save(source, quality=95)
            _save_pose_plate(source, output)
            with Image.open(output) as result:
                self.assertEqual(result.mode, "RGBA")
                self.assertEqual(result.size, (80, 60))
                self.assertEqual(result.getpixel((0, 0))[3], 0)
                self.assertEqual(result.getpixel((4, 4))[3], 0)
                self.assertGreater(result.getpixel((35, 25))[3], 240)
                self.assertGreater(result.getpixel((37, 27))[3], 240)

    def test_parser_maps_must_match_master_canvas(self):
        body, body_conf, detail, detail_conf = self.synthetic_maps()
        image = Image.new("RGB", (180, 112), (255, 255, 255))
        with self.assertRaisesRegex(AutoRigError, "match the master"):
            separate_from_parsing(image, body, body_conf, detail, detail_conf)


if __name__ == "__main__":
    unittest.main()
