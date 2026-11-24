import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

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
            parent_before = (bundle / "parent.png").read_bytes()
            child_before = (bundle / "child.png").read_bytes()
            character = {
                "canvas": {"width": 64, "height": 80},
                "joints": {"left_knee": {"x": 0.5, "y": 0.5}},
                "layers": [
                    {"role": "parent", "src": "parent.png", "x": 20, "y": 26, "width": 24, "height": 24},
                    {"role": "child", "src": "child.png", "x": 20, "y": 30, "width": 24, "height": 24},
                ],
            }
            (bundle / "character.json").write_text(json.dumps(character), encoding="utf-8")
            regions = {
                "joint_surfaces": {
                    "regions": {
                        "left_knee": {
                            "anchor": "left_knee",
                            "parent_role": "parent",
                            "child_role": "child",
                            "minimum_pixels": 20,
                            "blend_axis_joints": ["left_knee", "left_knee"],
                        }
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

            self.assertEqual(result["status"], "review_pack_created")
            self.assertEqual(result["joint_count"], 1)
            self.assertEqual(result["production_art_assets_created"], 0)
            self.assertTrue((output / "joint-artwork-contact-sheet.jpg").is_file())
            self.assertEqual(template["joint_surfaces"]["regions"]["left_knee"]["artist_source_polygon"], [])
            self.assertEqual(template["joint_surfaces"]["regions"]["left_knee"]["artwork_status"], "awaiting_artist_alignment")
            self.assertEqual((bundle / "parent.png").read_bytes(), parent_before)
            self.assertEqual((bundle / "child.png").read_bytes(), child_before)


if __name__ == "__main__":
    unittest.main()
