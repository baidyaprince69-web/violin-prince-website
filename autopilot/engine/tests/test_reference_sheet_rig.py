import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from reference_sheet_rig import build_reference_sheet_rig, _keyed_sheet


def draw_head(draw, center_x, top_y, scale=1.0, skin=(183, 119, 83), hair=(33, 29, 28)):
    width = int(38 * scale)
    height = int(48 * scale)
    draw.ellipse((center_x-width, top_y, center_x+width, top_y+height), fill=hair)
    draw.ellipse((center_x-int(30*scale), top_y+int(20*scale),
                  center_x+int(30*scale), top_y+int(86*scale)), fill=skin)
    draw.rectangle((center_x-int(13*scale), top_y+int(72*scale),
                    center_x+int(13*scale), top_y+int(112*scale)), fill=skin)


def make_head_sheet(path, *, with_lower_parts=False):
    image = Image.new("RGB", (800, 420), (255, 0, 255))
    draw = ImageDraw.Draw(image)
    for center in (100, 300, 500, 700):
        draw_head(draw, center, 36, scale=0.9)
    if with_lower_parts:
        for index in range(12):
            x = 30 + index * 64
            y = 280 + (index % 2) * 36
            draw.ellipse((x, y, x+22, y+18), fill=(80, 55, 48))
    image.save(path)


def make_parts_sheet(path):
    image = Image.new("RGB", (1000, 700), (255, 0, 255))
    draw = ImageDraw.Draw(image)
    for row in range(4):
        for column in range(5):
            x = 50 + column * 185
            y = 50 + row * 150
            if (row + column) % 2:
                draw.ellipse((x, y, x+70, y+100), fill=(40, 35, 34))
            else:
                draw.rounded_rectangle((x, y, x+82, y+100), radius=12, fill=(150, 95, 64))
    image.save(path)


class ReferenceSheetRigTests(unittest.TestCase):
    def test_removes_magenta_cutline_on_non_magenta_transparent_canvas(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "cutline.png"
            image = Image.new("RGBA", (64, 64), (30, 42, 58, 0))
            draw = ImageDraw.Draw(image)
            draw.rectangle((20, 20, 44, 44), fill=(190, 125, 88, 255))
            draw.rectangle((18, 18, 46, 46), outline=(255, 0, 255, 255), width=2)
            draw.line((20, 50, 44, 50), fill=(129, 8, 124, 255), width=2)
            draw.line((20, 55, 44, 55), fill=(54, 0, 45, 255), width=2)
            image.save(path)

            _source, alpha = _keyed_sheet(path)
            self.assertEqual(int(alpha[18, 24]), 0)
            self.assertEqual(int(alpha[50, 30]), 0)
            self.assertEqual(int(alpha[55, 30]), 0)
            self.assertEqual(int(alpha[32, 32]), 255)

    def test_builds_four_expression_plates_four_head_angles_and_parts_catalogue(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parts = root / "parts.png"
            expressions = root / "expressions.png"
            angles = root / "angles.png"
            make_parts_sheet(parts)
            make_head_sheet(expressions)
            make_head_sheet(angles, with_lower_parts=True)

            roles = (
                "torso", "head", "face",
                "left_upper_arm", "left_forearm", "left_hand",
                "right_upper_arm", "right_forearm", "right_hand",
                "left_thigh", "right_thigh", "left_calf", "right_calf",
                "left_foot", "right_foot",
            )
            layers = [
                {"id": role, "role": role, "src": role + ".png",
                 "x": 160, "y": 45 if role in ("head", "face") else 180,
                 "width": 120 if role in ("head", "face") else 180,
                 "height": 160 if role in ("head", "face") else 210}
                for role in roles
            ]
            joints = {
                name: {"x": 0.5, "y": 0.3}
                for name in (
                    "neck", "left_shoulder", "left_elbow", "left_wrist",
                    "right_shoulder", "right_elbow", "right_wrist",
                    "left_hip", "right_hip", "left_knee", "right_knee",
                    "left_ankle", "right_ankle",
                )
            }
            character_path = root / "character.json"
            character_path.write_text(json.dumps({
                "id": "violin-prince",
                "canvas": {"width": 500, "height": 600},
                "layers": layers,
                "joints": joints,
                "expressions": {
                    "neutral": {"src": "neutral.png"},
                    "smile": {"src": "smile.png"},
                },
            }), encoding="utf-8")

            report = build_reference_sheet_rig(
                character_path, root,
                rigging_sheet_path=parts,
                expression_sheet_path=expressions,
                head_angle_sheet_path=angles,
            )
            character = json.loads(character_path.read_text(encoding="utf-8"))
            self.assertEqual(set(character["head_variants"]), {
                "happy", "focused", "surprised", "neutral"
            })
            self.assertEqual(set(character["head_angles"]), {
                "front", "three_quarter", "profile_right", "profile_left"
            })
            self.assertGreaterEqual(report["reference_part_count"], 12)
            self.assertEqual(
                report["reference_parts_mapping"],
                "explicit_rig_role_and_target_geometry_candidates",
            )
            self.assertEqual(
                report["reference_part_alignment_candidate_count"],
                report["reference_part_count"],
            )
            self.assertTrue((root / "reference-parts-contact-sheet.png").is_file())
            self.assertTrue((root / "facial-parts-contact-sheet.png").is_file())
            self.assertGreater(report["facial_part_count"], 4)
            self.assertEqual(
                character["facial_part_catalogue"]["status"],
                "extracted_pending_feature_alignment",
            )
            self.assertTrue(
                character["facial_part_catalogue"]["state_build_status"].startswith(
                    "skipped_missing_required_components:"
                )
            )
            self.assertFalse(
                character["facial_part_catalogue"]["production_face_overlay_enabled"]
            )
            self.assertTrue((root / "reference-part-alignment-review.jpg").is_file())
            self.assertTrue((root / "reference-part-assembled-candidate.png").is_file())
            self.assertTrue((root / "reference-part-assembled-comparison.jpg").is_file())
            assembly = json.loads((root / "reference-part-assembled-candidate.json").read_text())
            self.assertEqual(assembly["status"], "assembled_candidate_not_active_pending_visual_review")
            self.assertFalse(assembly["production_layer_replacement_enabled"])
            expected_fixture_parts = sum(
                (root / f"{part_id}.png").is_file()
                for part_id in assembly["primary_part_ids"]
            )
            self.assertEqual(assembly["primary_part_count"], expected_fixture_parts)
            self.assertEqual(
                assembly["source_asset_count"],
                assembly["primary_part_count"] + assembly["source_bridge_count"],
            )
            self.assertEqual(assembly["canvas"], {"width": 500, "height": 600})
            self.assertNotIn("reference-part-014", assembly["primary_part_ids"])
            self.assertNotIn("reference-part-026", assembly["primary_part_ids"])
            self.assertIn("reference-part-030", assembly["primary_part_ids"])
            self.assertIn("reference-part-031", assembly["primary_part_ids"])
            self.assertIn("reference-part-026", assembly["review_exclusions"])
            alignment = json.loads((root / "reference-part-alignment-candidate.json").read_text())
            self.assertEqual(alignment["status"], "candidate_not_active_pending_visual_review")
            self.assertEqual(len(alignment["parts"]), report["reference_part_count"])
            self.assertTrue(all(
                item["alignment_status"] == "candidate_not_active"
                and item["target_box"] is not None
                and item["candidate_transform"]["scale"] > 0
                for item in alignment["parts"]
            ))
            self.assertFalse(
                character["reference_part_alignment"]["production_layer_replacement_enabled"]
            )
            mapping = json.loads((root / "reference-part-map.json").read_text(encoding="utf-8"))
            self.assertEqual(len(mapping["parts"]), report["reference_part_count"])
            self.assertFalse(mapping["automatic_body_part_replacement"])
            self.assertEqual(
                mapping["alignment_policy"],
                "explicit_candidate_not_active_pending_visual_review",
            )
            self.assertTrue(all(
                part["use_policy"] == "alignment_candidate_created_pending_visual_review"
                and part["alignment_candidate"]["alignment_status"] == "candidate_not_active"
                for part in mapping["parts"]
            ))
            self.assertEqual(mapping["parts"][0]["reference_role"], "head_portrait")
            self.assertEqual(mapping["parts"][0]["suggested_rig_role"], "head")
            self.assertEqual(mapping["parts"][2]["reference_role"], "jacket_torso")
            self.assertEqual(
                report["head_plate_normalization"],
                "fixed_canvas_bottom_centre_neck_anchor",
            )
            plate_sizes = []
            for asset in list(character["head_variants"].values()) + list(character["head_angles"].values()):
                image = Image.open(root / asset["src"]).convert("RGBA")
                self.assertEqual(image.getchannel("A").getextrema()[0], 0)
                self.assertGreater(image.getchannel("A").getextrema()[1], 0)
                plate_sizes.append(image.size)
                alpha_bounds = image.getchannel("A").getbbox()
                self.assertIsNotNone(alpha_bounds)
                left, top, right, bottom = alpha_bounds
                expected_x = asset["pivot_x"] * image.width
                actual_x = (left + right - 1) / 2
                self.assertLessEqual(abs(actual_x - expected_x), 1.5)
                self.assertAlmostEqual(asset["pivot_x"], 0.5)
                self.assertAlmostEqual(asset["pivot_y"], 0.92)
            self.assertEqual(
                len(set(plate_sizes)), 1,
                "all expression and head-angle plates must use the same pixel canvas",
            )

    def test_builds_distinct_speaking_blink_sad_and_shocked_head_variants(self):
        from reference_sheet_rig import _build_facial_state_head_variants

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            base = Image.new("RGBA", (136, 159), (180, 122, 84, 255))
            draw = ImageDraw.Draw(base)
            draw.ellipse((22, 10, 115, 145), fill=(180, 122, 84, 255))
            draw.ellipse((38, 64, 62, 84), fill=(245, 245, 235, 255))
            draw.ellipse((76, 64, 100, 84), fill=(245, 245, 235, 255))
            draw.ellipse((47, 70, 56, 80), fill=(30, 25, 22, 255))
            draw.ellipse((85, 70, 94, 80), fill=(30, 25, 22, 255))
            draw.ellipse((50, 99, 88, 120), fill=(70, 20, 20, 255))
            base.save(root / "head-variant-neutral.png")

            # Distinct shapes model the separately extracted eye, eyelid and
            # mouth assets; do not make different expressions share one fixture.
            for number in (15, 16, 17, 20, 28, 31, 32, 33, 34):
                asset = Image.new("RGBA", (46, 26), (0, 0, 0, 0))
                marker = ImageDraw.Draw(asset)
                if number in (15, 16):
                    marker.ellipse((4, 3, 42, 23), fill=(250, 250, 240, 255))
                    marker.ellipse((17, 7, 29, 20), fill=(35, 30, 28, 255))
                elif number in (32, 33):
                    marker.arc((3, 3, 43, 24), start=8, end=172, fill=(65, 28, 31, 255), width=4)
                elif number == 17:
                    marker.ellipse((4, 1, 42, 25), fill=(80, 20, 30, 255))
                elif number == 31:
                    marker.ellipse((12, 1, 34, 25), fill=(80, 20, 30, 255))
                elif number == 20:
                    marker.rounded_rectangle((5, 7, 41, 19), radius=5, fill=(80, 20, 30, 255))
                elif number == 28:
                    marker.arc((5, 2, 41, 25), start=195, end=345, fill=(80, 20, 30, 255), width=5)
                else:  # 34: a broad smile curve, unlike the speaking/sad mouths.
                    marker.arc((3, 0, 43, 27), start=20, end=160, fill=(80, 20, 30, 255), width=5)
                asset.save(root / f"facial-part-{number:03d}.png")

            parts = [
                {"part_id": f"facial-part-{number:03d}", "path": root / f"facial-part-{number:03d}.png"}
                for number in (15, 16, 17, 20, 28, 31, 32, 33, 34)
            ]
            bounds = {
                "x": 0, "y": 0, "width": 136, "height": 159,
                "pivot_x": 0.5, "pivot_y": 0.92, "z_index": 85,
            }
            variants, contact, status = _build_facial_state_head_variants(
                parts, {"neutral": {"src": "head-variant-neutral.png", **bounds}}, root
            )
            self.assertEqual(status, "created_from_separate_eye_and_mouth_assets")
            self.assertEqual(set(variants), {
                "speaking_open", "speaking_closed", "blink_closed",
                "sad", "shocked_open", "smile",
            })
            self.assertTrue((root / str(contact)).is_file())
            hashes = {
                (root / variant["src"]).read_bytes()
                for variant in variants.values()
            }
            self.assertGreaterEqual(len(hashes), 5)
            for variant in variants.values():
                image = Image.open(root / variant["src"]).convert("RGBA")
                self.assertEqual(image.size, (136, 159))


    def test_rejects_expression_sheet_without_four_separate_heads(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            parts = root / "parts.png"
            expressions = root / "expressions.png"
            angles = root / "angles.png"
            make_parts_sheet(parts)
            image = Image.new("RGB", (800, 420), (255, 0, 255))
            draw_head(ImageDraw.Draw(image), 200, 40)
            image.save(expressions)
            make_head_sheet(angles)
            character_path = root / "character.json"
            character_path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "Expected four separated"):
                build_reference_sheet_rig(
                    character_path, root,
                    rigging_sheet_path=parts,
                    expression_sheet_path=expressions,
                    head_angle_sheet_path=angles,
                )


if __name__ == "__main__":
    unittest.main()
