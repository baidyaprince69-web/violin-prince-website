import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image
import numpy as np

from joint_artwork_authoring import build_joint_artwork_review_pack


class JointArtworkAuthoringTests(unittest.TestCase):
    def test_review_pack_creates_lower_body_template_without_modifying_source_assets(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundle = root / "bundle"
            output = root / "review"
            bundle.mkdir()
            source_path = root / "source.png"
            Image.new("RGBA", (64, 80), (40, 50, 60, 255)).save(source_path)
            parent = Image.new("RGBA", (24, 24), (20, 30, 40, 255))
            child = Image.new("RGBA", (24, 24), (50, 60, 70, 255))
            parent.save(bundle / "parent.png")
            child.save(bundle / "child.png")
            parent.save(bundle / "hip_parent.png")
            child.save(bundle / "hip_child.png")
            parent_before = (bundle / "parent.png").read_bytes()
            child_before = (bundle / "child.png").read_bytes()
            hip_parent_before = (bundle / "hip_parent.png").read_bytes()
            hip_child_before = (bundle / "hip_child.png").read_bytes()
            lower_joints = (
                "left_hip", "right_hip", "left_knee",
                "right_knee", "left_ankle", "right_ankle",
            )
            character = {
                "canvas": {"width": 64, "height": 80},
                "joints": {
                    name: {
                        "x": (
                            36 / 64 if name == "left_hip"
                            else 62 / 64 if name == "right_hip"
                            else 0.25 + index * 0.1
                        ),
                        "y": 0.5,
                    }
                    for index, name in enumerate(lower_joints)
                },
                "layers": [
                    {"role": "parent", "src": "parent.png", "x": 20, "y": 26, "width": 24, "height": 24},
                    {"role": "child", "src": "child.png", "x": 20, "y": 30, "width": 24, "height": 24},
                    {"role": "hip_parent", "src": "hip_parent.png", "x": 10, "y": 26, "width": 24, "height": 24},
                    {"role": "hip_child", "src": "hip_child.png", "x": 38, "y": 26, "width": 24, "height": 24},
                ],
            }
            (bundle / "character.json").write_text(json.dumps(character), encoding="utf-8")
            regions = {
                "joint_surfaces": {
                    "regions": {
                        name: {
                            "anchor": name,
                            "parent_role": "hip_parent" if name in ("left_hip", "right_hip") else "parent",
                            "child_role": "hip_child" if name in ("left_hip", "right_hip") else "child",
                            "minimum_pixels": 20,
                            "blend_axis_joints": [name, name],
                        }
                        for name in lower_joints
                    }
                }
            }
            regions_path = root / "regions.json"
            regions_path.write_text(json.dumps(regions), encoding="utf-8")

            result = build_joint_artwork_review_pack(
                source_path, bundle, regions_path, output,
                crop_radius=16, scale=2,
            )
            template = json.loads((output / "joint-artwork-template.json").read_text(encoding="utf-8"))
            annotator_path = output / "joint-artwork-annotator.html"
            annotator = annotator_path.read_text(encoding="utf-8")

            self.assertEqual(result["status"], "review_pack_created")
            self.assertEqual(result["joint_count"], 6)
            self.assertEqual(result["production_art_assets_created"], 0)
            self.assertEqual(result["annotator"], "joint-artwork-annotator.html")
            self.assertTrue(annotator_path.is_file())
            self.assertIn("annotator-canvas", annotator)
            self.assertIn("Export reviewed JSON", annotator)
            self.assertIn("artist_source_polygon", annotator)
            self.assertIn("candidate_source_polygon", annotator)
            self.assertIn("artist_approved", annotator)
            self.assertIn('source.src="../bundle/source.png"', annotator)
            self.assertNotIn("fetch(", annotator)
            contact_path = output / "joint-artwork-contact-sheet.jpg"
            self.assertTrue(contact_path.is_file())
            contact = np.asarray(Image.open(contact_path).convert("RGB"))
            cyan_boundary_pixels = np.count_nonzero(
                (contact[:, :, 1] > 180)
                & (contact[:, :, 2] > 180)
                & (contact[:, :, 0] < 150)
            )
            amber_boundary_pixels = np.count_nonzero(
                (contact[:, :, 0] > 180)
                & (contact[:, :, 1] > 110)
                & (contact[:, :, 2] < 140)
            )
            self.assertGreater(cyan_boundary_pixels, 20,
                "the review sheet must render parent-surface contours in cyan")
            self.assertGreater(amber_boundary_pixels, 20,
                "the review sheet must render child-surface contours in amber")
            magenta_candidate_pixels = np.count_nonzero(
                (contact[:, :, 0] > 180)
                & (contact[:, :, 2] > 150)
                & (contact[:, :, 1] < 165)
            )
            self.assertGreater(magenta_candidate_pixels, 10,
                "shared source-pixel overlap evidence must be outlined in magenta")
            self.assertEqual(template["joint_surfaces"]["regions"]["left_knee"]["artist_source_polygon"], [])
            self.assertEqual(template["joint_surfaces"]["regions"]["left_knee"]["artwork_status"], "awaiting_artist_alignment")
            candidate = template["joint_surfaces"]["regions"]["left_knee"]
            self.assertGreater(len(candidate["candidate_source_polygon"]), 2)
            self.assertGreater(candidate["candidate_source_pixels"], 0)
            self.assertEqual(candidate["candidate_status"],
                "source_alpha_overlap_evidence_only_not_full_joint_surface")
            self.assertFalse(candidate["candidate_is_production_art"])
            self.assertEqual(candidate["candidate_parent_child_gap_px"], 0.0)
            hip_candidate = template["joint_surfaces"]["regions"]["left_hip"]
            self.assertEqual(hip_candidate["candidate_source_polygon"], [])
            self.assertEqual(hip_candidate["candidate_status"],
                "manual_seam_trace_required_no_shared_parent_child_pixels")
            self.assertFalse(hip_candidate["candidate_is_production_art"])
            self.assertGreater(hip_candidate["candidate_parent_child_gap_px"], 0)
            self.assertEqual(hip_candidate["manual_trace_reason"], "source_layers_separated_near_anchor")
            self.assertIsNotNone(hip_candidate["closest_parent_source_pixel"])
            self.assertIsNotNone(hip_candidate["closest_child_source_pixel"])
            right_hip_candidate = template["joint_surfaces"]["regions"]["right_hip"]
            self.assertIsNone(right_hip_candidate["candidate_parent_child_gap_px"])
            self.assertEqual(right_hip_candidate["manual_trace_reason"], "parent_source_pixels_absent_near_anchor")
            self.assertEqual(right_hip_candidate["parent_pixels_near_anchor"], 0)
            self.assertGreater(right_hip_candidate["child_pixels_near_anchor"], 0)
            self.assertGreater(result["candidate_joint_polygons"], 0)
            self.assertGreater(result["manual_seam_trace_required"], 0)
            self.assertEqual(result["candidate_polygons_artist_approved"], 0)
            self.assertEqual(result["rig_layers_modified"], 0)
            self.assertEqual((bundle / "parent.png").read_bytes(), parent_before)
            self.assertEqual((bundle / "child.png").read_bytes(), child_before)
            self.assertEqual((bundle / "hip_parent.png").read_bytes(), hip_parent_before)
            self.assertEqual((bundle / "hip_child.png").read_bytes(), hip_child_before)


if __name__ == "__main__":
    unittest.main()
