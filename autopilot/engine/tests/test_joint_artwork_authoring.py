import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image
import numpy as np

from joint_artwork_authoring import (
    build_joint_artwork_review_pack,
    validate_reviewed_joint_artwork_export,
)


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
            self.assertIn("persistActiveDraft", annotator)
            self.assertIn("persistActiveDraft();", annotator)
            self.assertIn("closest_parent_source_pixel", annotator)
            self.assertIn('strokeStyle="#ffe26a"', annotator)
            self.assertIn("Switching joints preserves the current draft", annotator)
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


    def test_reviewed_export_validator_checks_source_hash_pivot_and_both_alpha_surfaces(self):
        import hashlib

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundle = root / "bundle"
            bundle.mkdir()
            source_path = root / "preserved-source.png"
            source_pixels = np.zeros((100, 100, 4), dtype=np.uint8)
            source_pixels[20:80, 20:80] = (86, 54, 38, 255)
            Image.fromarray(source_pixels, mode="RGBA").save(source_path)
            for role in ("left_thigh", "left_calf"):
                Image.new("RGBA", (60, 60), (86, 54, 38, 255)).save(bundle / (role + ".png"))
            character = {
                "canvas": {"width": 100, "height": 100},
                "joints": {
                    "left_hip": {"x": 0.30, "y": 0.50},
                    "left_knee": {"x": 0.50, "y": 0.50},
                    "left_ankle": {"x": 0.70, "y": 0.50},
                },
                "layers": [
                    {"role": "left_thigh", "src": "left_thigh.png", "x": 20, "y": 20, "width": 60, "height": 60},
                    {"role": "left_calf", "src": "left_calf.png", "x": 20, "y": 20, "width": 60, "height": 60},
                ],
            }
            (bundle / "character.json").write_text(
                json.dumps(character), encoding="utf-8"
            )
            pairs = {
                "left_hip": ("torso", "left_thigh"),
                "right_hip": ("torso", "right_thigh"),
                "left_knee": ("left_thigh", "left_calf"),
                "right_knee": ("right_thigh", "right_calf"),
                "left_ankle": ("left_calf", "left_foot"),
                "right_ankle": ("right_calf", "right_foot"),
            }
            regions = {
                name: {
                    "anchor": name,
                    "anchor_px": [50.0, 50.0],
                    "parent_role": pair[0],
                    "child_role": pair[1],
                    "blend_axis_joints": ["left_hip", "left_ankle"],
                    "minimum_pixels": 80,
                    "artist_source_polygon": [],
                    "artwork_status": "awaiting_artist_alignment",
                }
                for name, pair in pairs.items()
            }
            regions["left_knee"].update({
                "anchor": "left_knee",
                "anchor_px": [50.0, 50.0],
                "artist_source_polygon": [[35, 35], [65, 35], [65, 65], [35, 65]],
                "artwork_status": "artist_approved",
            })
            export = {
                "schema_version": 1,
                "coordinate_space": "absolute_source_pixels_top_left",
                "canvas": {"width": 100, "height": 100},
                "source_artwork": {
                    "filename": source_path.name,
                    "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
                },
                "joint_surfaces": {"schema_version": 1, "regions": regions},
            }
            export_path = root / "joint-artwork-template-reviewed.json"
            export_path.write_text(json.dumps(export), encoding="utf-8")

            report = validate_reviewed_joint_artwork_export(
                source_path, bundle, export_path
            )

            self.assertEqual(report["status"], "reviewed_export_validated")
            self.assertEqual(report["approved_polygon_count"], 1)
            self.assertEqual(report["draft_polygon_count"], 0)
            self.assertEqual(report["validated_source_pixels"], 961)
            self.assertFalse(report["bundle_modified"])
            knee = report["regions"]["left_knee"]
            self.assertEqual(knee["status"], "validated_for_rig_extraction")
            self.assertEqual(knee["parent_source_overlap_pixels"], 961)
            self.assertEqual(knee["child_source_overlap_pixels"], 961)
            self.assertEqual(knee["joint_pivot_px"], [50.0, 50.0])
            self.assertEqual(len(knee["source_rgb_sha256"]), 64)

            export["source_artwork"]["sha256"] = "0" * 64
            export_path.write_text(json.dumps(export), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                validate_reviewed_joint_artwork_export(
                    source_path, bundle, export_path
                )


if __name__ == "__main__":
    unittest.main()
