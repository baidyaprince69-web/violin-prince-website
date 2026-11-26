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
            self.assertTrue((root / "reference-part-alignment-review.jpg").is_file())
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
