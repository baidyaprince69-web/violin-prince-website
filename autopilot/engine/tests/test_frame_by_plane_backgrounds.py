"""Tests for deterministic Frame By Plane scene-background generation."""
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from frame_by_plane_adapter import load_background_manifest
from frame_by_plane_backgrounds import create_frame_by_plane_backgrounds


class FrameByPlaneBackgroundGenerationTests(unittest.TestCase):
    def plan(self):
        return {
            "title": "Can Your Room Trick Your Violin Mix?",
            "scenes": [
                {
                    "caption": "Your room shapes what you hear",
                    "graphic_label": "ROOM ACOUSTICS",
                    "image_prompt": "dark cinematic music studio acoustic panels and monitor speakers",
                    "visual_mode": "macro_3d",
                },
                {
                    "caption": "Measure the room and adjust monitors",
                    "graphic_label": "ROOMTUNE",
                    "image_prompt": "audio technology signal path in an acoustic studio",
                    "visual_mode": "waveform",
                },
                {
                    "caption": "Hear the violin and trust the mix",
                    "graphic_label": "THE MUSICAL PAYOFF",
                    "image_prompt": "amber violin in a midnight recording studio",
                    "visual_mode": "cover_performance",
                },
            ],
        }

    def test_creates_three_real_image_planes_for_each_scene(self):
        with tempfile.TemporaryDirectory() as temp:
            bundles = create_frame_by_plane_backgrounds(
                self.plan(), Path(temp), size=(540, 960)
            )
            self.assertEqual(len(bundles), 3)
            for bundle in bundles:
                manifest_path = Path(bundle["manifest_path"])
                self.assertTrue(manifest_path.is_file())
                manifest = load_background_manifest(manifest_path)
                self.assertEqual(len(manifest["layers"]), 3)
                self.assertEqual(
                    [layer["name"] for layer in manifest["layers"]],
                    ["FarAtmosphere", "StudioEnvironment", "ForegroundDepth"],
                )
                for layer in manifest["layers"]:
                    self.assertTrue(layer["files"][0].is_file())
                    with Image.open(layer["files"][0]) as image:
                        self.assertEqual(image.size, (540, 960))
                        self.assertIn(image.mode, ("RGBA", "RGB"))

    def test_each_scene_gets_a_deterministic_but_distinct_layer_pack(self):
        plan = self.plan()
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            a = create_frame_by_plane_backgrounds(plan, Path(first), size=(540, 960))
            b = create_frame_by_plane_backgrounds(plan, Path(second), size=(540, 960))
            for left, right in zip(a, b):
                left_manifest = load_background_manifest(left["manifest_path"])
                right_manifest = load_background_manifest(right["manifest_path"])
                self.assertEqual(
                    [layer["bytes"] for layer in left_manifest["layers"]],
                    [layer["bytes"] for layer in right_manifest["layers"]],
                )
            first_bytes = Path(a[0]["layers"][0]).read_bytes()
            second_bytes = Path(a[1]["layers"][0]).read_bytes()
            self.assertNotEqual(first_bytes, second_bytes)

    def test_requires_exactly_three_authored_scenes(self):
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(ValueError, "exactly three"):
                create_frame_by_plane_backgrounds({"scenes": []}, Path(temp))


if __name__ == "__main__":
    unittest.main()
