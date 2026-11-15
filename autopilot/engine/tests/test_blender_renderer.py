"""Unit tests for optional Blender integration and transparent compositing."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from PIL import Image
import blender_renderer


class BlenderRendererTests(unittest.TestCase):
    def test_blender_is_disabled_without_explicit_opt_in(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(blender_renderer.is_blender_render_enabled())

    def test_blender_environment_switch_is_explicit(self):
        self.assertTrue(blender_renderer.is_blender_render_enabled("true"))
        self.assertTrue(blender_renderer.is_blender_render_enabled("1"))
        self.assertFalse(blender_renderer.is_blender_render_enabled("false"))
        self.assertFalse(blender_renderer.is_blender_render_enabled(""))

    def test_only_actual_3d_visual_modes_are_mapped(self):
        self.assertEqual(
            blender_renderer.scene_type_for({"visual_mode": "macro_3d"}),
            "string_vibration",
        )
        self.assertEqual(
            blender_renderer.scene_type_for({"visual_mode": "mechanism_3d"}),
            "bridge_cutaway",
        )
        self.assertIsNone(blender_renderer.scene_type_for({"visual_mode": "waveform"}))
        self.assertIsNone(blender_renderer.scene_type_for({"visual_mode": "cover_performance"}))

    def test_disabled_or_unsupported_scene_does_not_start_blender(self):
        with patch.object(blender_renderer, "_find_blender") as find_blender:
            self.assertIsNone(
                blender_renderer.render_scene_overlay(
                    {"visual_mode": "macro_3d"}, "unused.png", enabled=False
                )
            )
            self.assertIsNone(
                blender_renderer.render_scene_overlay(
                    {"visual_mode": "waveform"}, "unused.png", enabled=True
                )
            )
            find_blender.assert_not_called()

    def test_enabled_supported_scene_fails_closed_when_blender_is_missing(self):
        with patch.object(blender_renderer, "_find_blender", return_value=None):
            with self.assertRaises(blender_renderer.BlenderRenderError):
                blender_renderer.render_scene_overlay(
                    {"visual_mode": "macro_3d"},
                    "unused.png",
                    enabled=True,
                )

    def test_transparent_overlay_is_composited_to_final_vertical_size(self):
        with tempfile.TemporaryDirectory() as folder:
            base_path = Path(folder) / "base.png"
            overlay_path = Path(folder) / "overlay.png"
            output_path = Path(folder) / "composite.png"
            Image.new("RGB", (320, 480), (8, 16, 30)).save(base_path)
            overlay = Image.new("RGBA", (120, 200), (0, 0, 0, 0))
            ImageDraw = __import__("PIL.ImageDraw", fromlist=["ImageDraw"]).Draw
            draw = ImageDraw(overlay)
            draw.ellipse((15, 35, 105, 125), fill=(230, 170, 80, 210))
            overlay.save(overlay_path)

            result = blender_renderer.composite_scene_overlay(
                base_path, overlay_path, output_path, size=(720, 1280)
            )
            self.assertEqual(result, output_path)
            with Image.open(output_path) as composite:
                self.assertEqual(composite.size, (720, 1280))
                self.assertEqual(composite.mode, "RGB")
                self.assertNotEqual(composite.getpixel((360, 640)), (8, 16, 30))


if __name__ == "__main__":
    unittest.main()
