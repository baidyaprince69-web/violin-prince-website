"""Offline regression tests for SCHP mask assembly and hidden-area reconstruction."""
import unittest

import numpy as np
from PIL import Image

from character_autorig import (
    AutoRigError,
    ManualReviewRequired,
    _repair_hidden_area,
    _close_small_mask_holes,
    _soft_alpha_from_mask,
    _morph,
    _dark_garment_underlap,
    _joint_disk,
    _recover_hand_fingers_from_skin,
    _save_pose_plate,
    _face_region_from_head,
    _face_expression_crop_box,
    _face_plate,
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
        face_interior = _morph(masks["face"], 3, "erode")
        face_perimeter_ring = masks["face"] & ~face_interior
        face_overlap_mask = masks["head"] & masks["face"]
        face_overlap = int(face_overlap_mask.sum())
        self.assertGreater(face_overlap, 0, "head shell must underlap the feathered face edge")
        self.assertLessEqual(
            face_overlap,
            int(face_perimeter_ring.sum()),
            "head/face overlap must stay inside the eroded face perimeter ring",
        )
        self.assertEqual(
            int((masks["head"] & face_interior).sum()),
            0,
            "original facial pixels must remain excluded from the centre of the face plate",
        )
        self.assertGreater(report["face_edge_blend"]["alpha_gaussian_blur_px"], 0)
        for role, region in masks.items():
            self.assertGreater(int(region.sum()), 20, role)
        for side in ("left", "right"):
            self.assertGreater(
                int((masks[f"{side}_upper_arm"] & masks[f"{side}_forearm"]).sum()),
                0,
                f"{side} elbow layers must overlap under the child segment",
            )
            self.assertGreater(
                int((masks[f"{side}_forearm"] & masks[f"{side}_hand"]).sum()),
                0,
                f"{side} wrist layers must overlap under the hand",
            )
        self.assertTrue(report["joint_underlap"]["joint_anchors_use_unexpanded_masks"])
        self.assertEqual(report["joint_underlap"]["wrist_patch"], "localized_around_joint_anchor_only")
        self.assertLess(
            max(report["joint_underlap"]["overlap_pixels"].values()),
            2500,
            "joint underlap must stay local rather than copying whole hand/arm regions",
        )
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

    def test_skin_connected_fingers_are_recovered_into_hand_layer(self):
        width, height = 160, 112
        image = Image.new("RGB", (width, height), (30, 30, 36))
        pixels = image.load()
        hand = np.zeros((height, width), dtype=bool)
        upper = np.zeros((height, width), dtype=bool)

        # Semantic parser hand seed is only the palm. Warm skin pixels that
        # continue past it represent fingers omitted from the coarse arm class.
        hand[43:59, 18:32] = True
        upper[39:53, 35:58] = True
        for y in range(43, 59):
            for x in range(5, 33):
                pixels[x, y] = (205, 140, 100)
        # A second finger-like extension separated by a narrow antialias gap.
        for y in range(55, 60):
            for x in range(8, 19):
                pixels[x, y] = (198, 132, 94)

        recovered, added = _recover_hand_fingers_from_skin(image, hand, upper)
        self.assertGreater(added, 0)
        self.assertTrue(np.any(recovered[45:52, 5:18]))
        self.assertTrue(np.any(recovered[55:60, 8:18]))
        # Neutral background must not be pulled into the hand.
        self.assertFalse(np.any(recovered[:, 120:]))

    def test_hand_recovery_window_reaches_fingertips_beyond_small_mask_bbox(self):
        width, height = 260, 200
        image = Image.new("RGB", (width, height), (255, 255, 255))
        pixels = image.load()
        hand = np.zeros((height, width), dtype=bool)
        upper = np.zeros((height, width), dtype=bool)

        hand[45:185, 90:230] = True
        upper[30:100, 200:245] = True
        # The far fingertip lies beyond the old 24%-of-hand search padding.
        for y in range(45, 186):
            for x in range(48, 231):
                pixels[x, y] = (205, 140, 100)

        recovered, added = _recover_hand_fingers_from_skin(image, hand, upper)
        self.assertGreater(added, 0)
        self.assertTrue(recovered[150, 50], "distal fingertip must be included")
        self.assertFalse(recovered[10, 10], "unrelated white background must stay transparent")

    def test_joint_disk_stays_bounded_around_pivot(self):
        disk = _joint_disk((80, 100), (50, 40), radius=12)
        self.assertTrue(disk[40, 50])
        self.assertTrue(disk[40, 61])
        self.assertFalse(disk[40, 63])
        self.assertFalse(disk[10, 50])

    def test_joint_underlap_only_uses_dark_sleeve_pixels_not_skin(self):
        width, height = 40, 40
        image = Image.new("RGB", (width, height), (255, 255, 255))
        pixels = image.load()
        parent = np.zeros((height, width), dtype=bool)
        child = np.zeros((height, width), dtype=bool)
        allowed = np.ones((height, width), dtype=bool)

        parent[15:25, 5:11] = True
        child[11:29, 15:29] = True
        # Dark sleeve/cuff material forms the safe hidden overlap.
        for y in range(15, 25):
            for x in range(11, 15):
                pixels[x, y] = (35, 39, 45)
        # Skin tones belong only to the rotating hand and must not be copied
        # into the stationary forearm underlap.
        for y in range(11, 29):
            for x in range(15, 29):
                pixels[x, y] = (205, 140, 100)

        overlap = _dark_garment_underlap(
            image, child, parent, allowed, radius=5
        )
        self.assertTrue(np.any(overlap[15:25, 11:15]))
        self.assertFalse(np.any(overlap[11:29, 15:29]))

    def test_soft_face_alpha_feathers_the_edge_but_keeps_the_interior_opaque(self):
        mask = np.zeros((40, 40), dtype=bool)
        mask[10:30, 10:30] = True
        alpha = _soft_alpha_from_mask(mask, blur_radius=1.2)
        self.assertEqual(alpha.shape, mask.shape)
        self.assertEqual(int(alpha[20, 20]), 255)
        self.assertGreater(int(alpha[9, 20]), 0)
        self.assertLess(int(alpha[9, 20]), 255)
        self.assertEqual(int(alpha[0, 0]), 0)

    def test_head_neck_mask_closes_small_alpha_pinholes(self):
        neck = np.zeros((40, 60), dtype=bool)
        neck[5:35, 10:50] = True
        neck[15, 24] = False
        neck[20:22, 37] = False

        closed = _close_small_mask_holes(neck, size=5)
        self.assertTrue(closed[15, 24])
        self.assertTrue(closed[20, 37])
        self.assertFalse(closed[2, 2])
        self.assertFalse(closed[38, 58])

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

    def test_face_region_is_smooth_oval_inside_head_silhouette(self):
        head = np.zeros((120, 100), dtype=bool)
        head[5:115, 15:85] = True
        face = _face_region_from_head(head)
        self.assertTrue(face[60, 50])
        self.assertFalse(face[0, 0])
        self.assertFalse(face[60, 15])
        self.assertFalse(face[60, 84])
        self.assertFalse(np.any(face & ~head))

    def test_expression_plate_uses_exact_master_face_alpha_mask(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "speaking.jpg"
            output = root / "expression-speaking.png"
            image = Image.new("RGB", (400, 300), (250, 250, 250))
            for y in range(40, 260):
                for x in range(100, 300):
                    image.putpixel((x, y), (180, 100, 70))
            image.save(source, quality=95)
            alpha = np.zeros((60, 80), dtype=bool)
            yy, xx = np.ogrid[:60, :80]
            alpha[((xx - 40) / 32) ** 2 + ((yy - 30) / 25) ** 2 <= 1] = True
            _face_plate(source, (80, 60), output, alpha_mask=alpha)
            with Image.open(output) as plate:
                self.assertEqual(plate.mode, "RGBA")
                self.assertEqual(plate.size, (80, 60))
                self.assertEqual(plate.getpixel((0, 0))[3], 0)
                self.assertEqual(plate.getpixel((40, 30))[3], 255)
                self.assertEqual(plate.getpixel((40, 4))[3], 0)

    def test_expression_crop_matches_face_layer_aspect_and_includes_forehead(self):
        x0, y0, x1, y1 = _face_expression_crop_box((1644, 1096), (300, 286))
        self.assertAlmostEqual((x1 - x0) / (y1 - y0), 300 / 286, delta=0.005)
        self.assertLess(x0, round(1644 * 0.39))
        self.assertGreater(x1, round(1644 * 0.61))
        self.assertLess(y0, round(1096 * 0.33))
        self.assertLess(y1, round(1096 * 0.72))

    def test_face_plate_removes_edge_white_backdrop_and_keeps_enclosed_highlights(self):
        import tempfile
        from pathlib import Path
        from PIL import ImageDraw

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "expression.png"
            output = root / "expression-clean.png"
            image = Image.new("RGB", (400, 300), (255, 255, 255))
            draw = ImageDraw.Draw(image)
            # A face silhouette fills the wider crop, with a small white eye
            # highlight fully enclosed by skin so backdrop removal must retain it.
            draw.ellipse((120, 65, 280, 181), fill=(188, 125, 92))
            draw.ellipse((194, 117, 206, 129), fill=(250, 250, 250))
            image.save(source)
            alpha = np.full((60, 80), 255, dtype=np.uint8)
            _face_plate(source, (80, 60), output, alpha_mask=alpha)
            with Image.open(output) as plate:
                self.assertEqual(plate.getpixel((2, 30))[3], 0,
                    "border-connected white backdrop must not leak into the face plate")
                self.assertGreater(plate.getpixel((40, 20))[3], 245,
                    "the illustrated face interior must remain opaque")
                highlight = plate.getpixel((40, 30))
                self.assertGreater(highlight[3], 245,
                    "enclosed white eye details must remain opaque")
                self.assertGreater(min(highlight[:3]), 220,
                    "the enclosed white eye highlight must retain its colour")

    def test_expression_plate_preserves_master_hairline_from_base_face(self):
        import tempfile
        from pathlib import Path
        from PIL import Image, ImageDraw

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "expression.png"
            base = root / "master-face.png"
            output = root / "expression-clean.png"

            reference = Image.new("RGB", (400, 300), (255, 255, 255))
            ImageDraw.Draw(reference).ellipse((80, 20, 320, 280), fill=(188, 125, 92))
            reference.save(source)
            Image.new("RGBA", (80, 60), (24, 220, 40, 255)).save(base)

            alpha = np.full((60, 80), 255, dtype=np.uint8)
            _face_plate(
                source, (80, 60), output,
                alpha_mask=alpha, base_face_path=base,
            )
            with Image.open(output) as plate:
                top = plate.getpixel((40, 2))
                lower = plate.getpixel((40, 55))
                self.assertGreater(top[1], 200,
                    "the master hairline area must come from the original face layer")
                self.assertLess(top[0], 80)
                self.assertGreater(lower[0], 150,
                    "the lower expression region must come from the alternate expression")
                self.assertLess(lower[1], 170)

    def test_expression_plate_removes_top_connected_fringe_but_keeps_brows(self):
        import tempfile
        from pathlib import Path
        from PIL import Image, ImageDraw

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "expression.png"
            base = root / "master-face.png"
            output = root / "expression-clean.png"

            reference = Image.new("RGB", (400, 300), (255, 255, 255))
            draw = ImageDraw.Draw(reference)
            draw.ellipse((80, 20, 320, 280), fill=(188, 125, 92))
            # Hair touches the top edge of the selected crop; the eyebrow is
            # a separate dark feature that must remain visible.
            draw.rectangle((110, 40, 290, 110), fill=(35, 32, 31))
            draw.rectangle((150, 143, 250, 151), fill=(30, 27, 26))
            reference.save(source)
            Image.new("RGBA", (80, 60), (24, 220, 40, 255)).save(base)

            alpha = np.full((60, 80), 255, dtype=np.uint8)
            _face_plate(
                source, (80, 60), output,
                alpha_mask=alpha, base_face_path=base,
            )
            with Image.open(output) as plate:
                self.assertLess(plate.getpixel((40, 20))[3], 10,
                    "top-connected hair must be removed so the master hairline shows through")
                self.assertGreater(plate.getpixel((40, 40))[3], 220,
                    "the disconnected eyebrow must remain visible")

    def test_pose_reference_plate_removes_near_white_background(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder) / "pose.jpg"
            output = Path(folder) / "pose.png"
            image = Image.new("RGB", (160, 120), (255, 255, 255))
            for y in range(30, 90):
                for x in range(40, 120):
                    image.putpixel((x, y), (30, 40, 50))
            # Tiny black JPEG speck in the backdrop should be removed by the
            # closing pass, while an enclosed white eye/highlight stays opaque.
            for y in range(3, 6):
                for x in range(3, 6):
                    image.putpixel((x, y), (0, 0, 0))
            for y in range(50, 55):
                for x in range(75, 80):
                    image.putpixel((x, y), (255, 255, 255))
            image.save(source, quality=95)
            _save_pose_plate(source, output)
            with Image.open(output) as result:
                self.assertEqual(result.mode, "RGBA")
                # JPEG decoding and Pillow morphology can shift the detected
                # foreground edge by a pixel. Check the intended tight crop
                # and retained safety margin without pinning one exact size.
                self.assertGreaterEqual(result.width, 130)
                self.assertLess(result.width, 160)
                self.assertGreaterEqual(result.height, 110)
                self.assertLess(result.height, 120)
                self.assertEqual(result.getpixel((4, 4))[3], 0)
                self.assertGreater(result.getpixel((68, 58))[3], 240)
                self.assertGreater(result.getpixel((66, 51))[3], 240)

    def test_parser_maps_must_match_master_canvas(self):
        body, body_conf, detail, detail_conf = self.synthetic_maps()
        image = Image.new("RGB", (180, 112), (255, 255, 255))
        with self.assertRaisesRegex(AutoRigError, "match the master"):
            separate_from_parsing(image, body, body_conf, detail, detail_conf)


if __name__ == "__main__":
    unittest.main()
