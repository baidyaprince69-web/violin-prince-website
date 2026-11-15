"""Unit tests for the full-frame animated Blender rendering adapter."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

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

    def test_all_existing_visual_modes_have_full_3d_templates(self):
        expected = {
            "macro_3d": "string_vibration",
            "mechanism_3d": "bridge_cutaway",
            "waveform": "wave_field",
            "melody_map": "melody_path",
            "comparison": "comparison",
            "cover_performance": "violin_performance",
        }
        for mode, scene_type in expected.items():
            with self.subTest(mode=mode):
                self.assertEqual(
                    blender_renderer.scene_type_for({"visual_mode": mode}),
                    scene_type,
                )

    def test_disabled_renderer_does_not_start_blender(self):
        with patch.object(blender_renderer, "_find_blender") as find_blender:
            self.assertIsNone(
                blender_renderer.render_scene_video(
                    {"visual_mode": "macro_3d"}, "unused.mp4",
                    enabled=False,
                )
            )
            find_blender.assert_not_called()

    def test_unsupported_visual_mode_fails_closed(self):
        with patch.object(blender_renderer, "_find_blender", return_value="/usr/bin/blender"):
            with self.assertRaises(blender_renderer.BlenderRenderError):
                blender_renderer.render_scene_video(
                    {"visual_mode": "unknown_mode"}, "unused.mp4", enabled=True
                )

    def test_enabled_renderer_fails_closed_when_blender_is_missing(self):
        with patch.object(blender_renderer, "_find_blender", return_value=None):
            with self.assertRaises(blender_renderer.BlenderRenderError):
                blender_renderer.render_scene_video(
                    {"visual_mode": "macro_3d"}, "unused.mp4", enabled=True
                )

    def test_performance_scene_requires_a_real_imported_model_file(self):
        with patch.dict(os.environ, {}, clear=True), patch.object(
            blender_renderer, "_find_blender"
        ) as find_blender:
            with self.assertRaisesRegex(
                blender_renderer.BlenderRenderError, "verified downloaded"
            ):
                blender_renderer.render_scene_video(
                    {"visual_mode": "cover_performance"},
                    "unused.mp4",
                    enabled=True,
                )
            find_blender.assert_not_called()

    def test_performance_scene_rejects_non_gltf_asset_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            image = Path(tmp) / "not-a-model.png"
            image.write_bytes(b"not a model")
            with patch.dict(
                os.environ, {"BLENDER_VIOLIN_MODEL_PATH": str(image)}, clear=True
            ):
                with self.assertRaisesRegex(
                    blender_renderer.BlenderRenderError, "must be a .gltf or .glb"
                ):
                    blender_renderer.render_scene_video(
                        {"visual_mode": "cover_performance"},
                        "unused.mp4",
                        enabled=True,
                    )


if __name__ == "__main__":
    unittest.main()
