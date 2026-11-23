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
    _register_expression_to_neutral,
    _split_arm,
    _repair_transparent_person_holes,
    _restore_person_holes_in_source,
    _clean_inherited_edge_matte,
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



    def test_neutral_expression_fallback_is_pixel_identical_and_explicit(self):
        import tempfile
        from pathlib import Path
        from PIL import Image, ImageChops
        from character_autorig import _copy_neutral_expression_fallback

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "face.png"
            destination = root / "expression-fallback.png"
            image = Image.new("RGBA", (17, 23), (140, 90, 70, 0))
            image.putpixel((8, 10), (210, 150, 110, 255))
            image.save(source)
            _copy_neutral_expression_fallback(source, destination)
            with Image.open(source) as expected, Image.open(destination) as actual:
                self.assertEqual(expected.mode, actual.mode)
                self.assertEqual(expected.size, actual.size)
                self.assertIsNone(ImageChops.difference(expected, actual).getbbox())

    def test_repairs_transparent_holes_only_inside_confident_person_regions(self):
        width, height = 40, 40
        pixels = np.full((height, width, 3), 255, dtype=np.uint8)
        pixels[8:32, 8:32] = (36, 44, 52)
        alpha = np.full((height, width), 255, dtype=np.uint8)
        alpha[16:24, 16:24] = 0
        labels = np.zeros((height, width), dtype=np.uint8)
        labels[8:32, 8:32] = 2
        confidence = np.full((height, width), 0.95, dtype=np.float32)
        image = Image.fromarray(pixels, mode="RGB")

        repaired, report = _repair_transparent_person_holes(
            image, alpha, labels, confidence, maximum_fraction=0.05
        )
        repaired_pixels = np.asarray(repaired, dtype=np.uint8)
        self.assertEqual(report["method"], "opencv_telea_semantic_alpha_holes")
        self.assertEqual(report["pixels_reconstructed"], 64)
        self.assertLess(float(repaired_pixels[16:24, 16:24].mean()), 100)
        self.assertTrue(np.all(repaired_pixels[0, 0] == 255),
                        "ordinary transparent background must not be reconstructed")

    def test_preserved_full_body_source_restores_only_confident_person_holes(self):
        width, height = 32, 32
        original = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        pixels = np.asarray(original, dtype=np.uint8).copy()
        pixels[6:26, 6:26] = (40, 48, 58, 255)
        pixels[14:19, 14:19] = (40, 48, 58, 0)
        original = Image.fromarray(pixels, mode="RGBA")

        repaired = Image.new("RGB", (width, height), (255, 255, 255))
        repaired_pixels = np.asarray(repaired, dtype=np.uint8).copy()
        repaired_pixels[14:19, 14:19] = (42, 49, 57)
        repaired = Image.fromarray(repaired_pixels, mode="RGB")

        source_alpha = pixels[:, :, 3].copy()
        labels = np.zeros((height, width), dtype=np.uint8)
        labels[6:26, 6:26] = 2
        confidence = np.full((height, width), 0.05, dtype=np.float32)
        confidence[6:26, 6:26] = 0.95

        preserved, report = _restore_person_holes_in_source(
            original, repaired, source_alpha, labels, confidence
        )
        result = np.asarray(preserved, dtype=np.uint8)
        self.assertTrue(np.all(result[14:19, 14:19, 3] == 255))
        self.assertTrue(np.all(result[14:19, 14:19, :3] == (42, 49, 57)))
        self.assertEqual(int(result[2, 2, 3]), 0,
            "transparent non-person background must stay transparent")
        self.assertEqual(tuple(result[8, 8]), (40, 48, 58, 255),
            "original non-hole body pixels must remain pixel-identical")
        self.assertEqual(report["pixels_restored"], 25)
        self.assertTrue(report["original_alpha_preserved_outside_holes"])

    def test_edge_matte_cleanup_removes_only_small_external_neutral_specks(self):
        pixels = np.zeros((32, 32, 4), dtype=np.uint8)
        pixels[7:26, 7:26] = (38, 42, 46, 255)
        # A single matte fleck and a detached two-pixel fleck on the exterior edge.
        pixels[6, 10] = (190, 190, 190, 255)
        pixels[6, 12:14] = (185, 185, 185, 255)
        # Skin-coloured edge detail, interior white detail, and feathered edge
        # pixels must not be removed by the conservative matte rule.
        pixels[6, 16] = (220, 150, 120, 255)
        pixels[12, 12] = (248, 246, 240, 255)
        pixels[6, 20] = (38, 42, 46, 153)
        # A short five-pixel neutral-grey remnant is also matte contamination,
        # not a deliberate highlight or part of the body outline.
        pixels[14:19, 6] = np.array([
            (145, 145, 143, 255),
            (152, 152, 150, 255),
            (160, 160, 158, 255),
            (168, 168, 166, 255),
            (175, 175, 173, 255),
        ], dtype=np.uint8)
        source = Image.fromarray(pixels, mode="RGBA")

        cleaned, report = _clean_inherited_edge_matte(source)
        result = np.asarray(cleaned, dtype=np.uint8)

        self.assertEqual(report["method"], "border_connected_neutral_edge_speck_cleanup")
        self.assertEqual(report["pixels_removed"], 8)
        self.assertEqual(report["components_removed"], 3)
        self.assertEqual(tuple(result[6, 10]), (0, 0, 0, 0))
        self.assertTrue(np.all(result[6, 12:14, 3] == 0))
        self.assertTrue(np.all(result[14:19, 6, 3] == 0),
            "small neutral-grey matte remnants on the outside alpha edge must be cleared")
        self.assertEqual(tuple(result[6, 16]), (220, 150, 120, 255))
        self.assertEqual(tuple(result[12, 12]), (248, 246, 240, 255))
        self.assertEqual(tuple(result[6, 20]), (38, 42, 46, 153))
        self.assertTrue(report["interior_details_preserved"])
        self.assertTrue(report["partial_alpha_edge_preserved"])


    def test_ignores_low_confidence_transparent_background(self):
        width, height = 40, 40
        image = Image.new("RGB", (width, height), (255, 255, 255))
        alpha = np.zeros((height, width), dtype=np.uint8)
        labels = np.zeros((height, width), dtype=np.uint8)
        confidence = np.full((height, width), 0.1, dtype=np.float32)
        repaired, report = _repair_transparent_person_holes(
            image, alpha, labels, confidence
        )
        self.assertEqual(report["method"], "not_required")
        self.assertEqual(report["pixels_reconstructed"], 0)
        self.assertEqual(repaired.getpixel((12, 12)), (255, 255, 255))

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
        torso_overlap = report["torso_backplate_arm_overlap"]
        self.assertEqual(
            torso_overlap["method"],
            "remove_source_arm_pixels_from_static_torso_keep_hidden_underlay",
        )
        self.assertGreater(torso_overlap["source_arm_pixels_removed"], 0)
        self.assertEqual(
            torso_overlap["independent_limb_assets_modified"], 0
        )
        self.assertFalse(torso_overlap["hand_animation_data_modified"])
        arm_union = np.zeros_like(masks["torso"], dtype=bool)
        for role in (
            "left_upper_arm", "right_upper_arm",
            "left_forearm", "right_forearm",
            "left_hand", "right_hand",
        ):
            arm_union |= masks[role]
        # The only arm pixels retained in the static torso are the explicitly
        # reconstructed underlay, not frozen copies of the source arms.
        self.assertEqual(
            int((masks["torso"] & arm_union).sum()),
            torso_overlap["hidden_underlay_pixels_retained"],
        )
        self.assertLess(
            max(report["joint_underlap"]["overlap_pixels"].values()),
            2500,
            "joint underlap must stay local rather than copying whole hand/arm regions",
        )
        for point in joints.values():
            self.assertTrue(0 <= point["x"] <= 1)
            self.assertTrue(0 <= point["y"] <= 1)
        self.assertTrue(report["needs_visual_review"])

    def test_exports_exact_hidden_overlap_mask_when_requested(self):
        import tempfile
        from pathlib import Path

        body, body_conf, detail, detail_conf = self.synthetic_maps()
        image = Image.new("RGB", (160, 112), (30, 30, 36))
        with tempfile.TemporaryDirectory() as folder:
            mask_path = Path(folder) / "torso-hidden-overlap-mask.png"
            _masks, _repaired, report, _joints = separate_from_parsing(
                image, body, body_conf, detail, detail_conf,
                hand_fraction=0.62,
                max_local_inpaint_ratio=0.12,
                hidden_mask_path=mask_path,
            )
            self.assertTrue(mask_path.is_file())
            with Image.open(mask_path) as opened:
                exported = np.asarray(opened.convert("L"), dtype=np.uint8) > 0
            self.assertEqual(exported.shape, (112, 160))
            self.assertGreater(int(exported.sum()), 0)
            self.assertEqual(
                int(exported.sum()),
                report["hidden_area_reconstruction"]["pixels_reconstructed"],
            )
            self.assertEqual(
                report["hidden_area_reconstruction"]["mask_asset"],
                "torso-hidden-overlap-mask.png",
            )
            self.assertTrue(report["hidden_area_reconstruction"]["mask_saved"])

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

    def test_expression_registration_recovers_translation_and_preserves_neutral_alpha(self):
        from PIL import Image, ImageDraw

        width, height = 100, 80
        neutral = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(neutral)
        skin = (206, 150, 116, 255)
        dark = (35, 30, 29, 255)
        white = (248, 242, 225, 255)
        iris = (64, 43, 32, 255)
        draw.ellipse((3, 1, width - 3, height - 1), fill=skin, outline=dark, width=2)
        draw.pieslice((2, -18, width - 2, 34), 180, 360, fill=dark)
        for center_x in (width * 0.32, width * 0.68):
            center_y = height * 0.43
            draw.arc((center_x - 18, center_y - 14, center_x + 18, center_y + 8),
                     190, 350, fill=dark, width=4)
            draw.ellipse((center_x - 17, center_y - 6, center_x + 17, center_y + 15),
                         outline=dark, width=2)
            draw.ellipse((center_x - 8, center_y - 1, center_x + 8, center_y + 10),
                         fill=white, outline=dark, width=1)
            draw.ellipse((center_x - 3, center_y + 1, center_x + 4, center_y + 9),
                         fill=iris)
            draw.ellipse((center_x - 1, center_y + 2, center_x + 1, center_y + 4),
                         fill=white)
        draw.line((width * 0.5, height * 0.4, width * 0.48, height * 0.62,
                   width * 0.55, height * 0.65), fill=dark, width=2)
        draw.arc((width * 0.34, height * 0.65, width * 0.68, height * 0.87),
                 5, 170, fill=dark, width=3)
        draw.arc((width * 0.37, height * 0.68, width * 0.65, height * 0.82),
                 5, 170, fill=(115, 65, 50, 255), width=2)
        for x, y in ((18, 45), (23, 49), (30, 55), (70, 50), (76, 54),
                     (60, 61), (45, 30), (56, 37)):
            draw.ellipse((x - 1, y - 1, x + 1, y + 1), fill=(160, 104, 79, 255))

        # Move the source six pixels left and twelve down; the estimated
        # source-to-neutral transform must recover (+6, -12).
        shifted = neutral.transform(
            neutral.size,
            Image.Transform.AFFINE,
            (1, 0, 6, 0, 1, -12),
            resample=Image.Resampling.BICUBIC,
            fillcolor=(0, 0, 0, 0),
        )
        aligned, metrics = _register_expression_to_neutral(shifted, neutral)
        self.assertAlmostEqual(metrics["translate_x"], 6.0, delta=0.75)
        self.assertAlmostEqual(metrics["translate_y"], -12.0, delta=0.75)
        self.assertGreater(metrics["inliers"], 20)
        self.assertLess(metrics["median_error_px"], 1.0)
        self.assertEqual(aligned.getchannel("A").tobytes(), neutral.getchannel("A").tobytes())

    def test_expression_registration_fails_closed_without_landmarks(self):
        flat = Image.new("RGBA", (100, 80), (180, 120, 90, 255))
        with self.assertRaisesRegex(ManualReviewRequired, "facial landmarks|reliable facial matches"):
            _register_expression_to_neutral(flat, flat)


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

    def test_missing_upper_arm_class_uses_only_identified_side_arm_mask(self):
        side_mask = np.zeros((110, 80), dtype=bool)
        side_mask[15:94, 16:34] = True
        upper_all = np.zeros_like(side_mask)
        lower_all = np.zeros_like(side_mask)
        lower_all[56:94, 16:34] = True

        upper, forearm, hand, used_fallback = _split_arm(
            side_mask, upper_all, lower_all, "left", hand_fraction=0.72
        )

        self.assertTrue(used_fallback)
        self.assertGreaterEqual(int(upper.sum()), 30)
        self.assertGreaterEqual(int(forearm.sum()), 20)
        self.assertGreaterEqual(int(hand.sum()), 20)
        self.assertFalse(np.any(upper & hand))
        self.assertTrue(np.all((upper | forearm | hand) <= side_mask))

    def test_upper_arm_fallback_fails_closed_without_a_lower_arm_seed(self):
        side_mask = np.zeros((100, 80), dtype=bool)
        side_mask[20:85, 15:32] = True
        with self.assertRaisesRegex(ManualReviewRequired, "upper arm"):
            _split_arm(
                side_mask,
                np.zeros_like(side_mask),
                np.zeros_like(side_mask),
                "right",
                hand_fraction=0.72,
            )

    def test_parser_maps_must_match_master_canvas(self):
        body, body_conf, detail, detail_conf = self.synthetic_maps()
        image = Image.new("RGB", (180, 112), (255, 255, 255))
        with self.assertRaisesRegex(AutoRigError, "match the master"):
            separate_from_parsing(image, body, body_conf, detail, detail_conf)


if __name__ == "__main__":
    unittest.main()
