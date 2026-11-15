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

    def test_parallel_worker_count_is_bounded_to_scene_count_and_three(self):
        with patch.dict(os.environ, {"BLENDER_RENDER_WORKERS": "9"}, clear=True):
            self.assertEqual(blender_renderer.blender_render_worker_count(8), 3)
            self.assertEqual(blender_renderer.blender_render_worker_count(2), 2)
        with patch.dict(os.environ, {"BLENDER_RENDER_WORKERS": "0"}, clear=True):
            self.assertEqual(blender_renderer.blender_render_worker_count(8), 1)
        with patch.dict(os.environ, {"BLENDER_RENDER_WORKERS": "bad"}, clear=True):
            self.assertEqual(blender_renderer.blender_render_worker_count(8), 1)

    def test_parallel_blender_processes_default_to_one_cpu_thread_each(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertEqual(blender_renderer.blender_threads_per_worker(), 1)
        with patch.dict(os.environ, {"BLENDER_THREADS_PER_WORKER": "3"}, clear=True):
            self.assertEqual(blender_renderer.blender_threads_per_worker(), 3)
        with patch.dict(os.environ, {"BLENDER_THREADS_PER_WORKER": "99"}, clear=True):
            self.assertEqual(blender_renderer.blender_threads_per_worker(), 4)

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


    def test_daily_frame_by_plane_scene_fails_closed_without_manifest(self):
        with patch.object(blender_renderer, "_find_blender") as find_blender:
            with self.assertRaisesRegex(
                blender_renderer.BlenderRenderError, "requires a Frame By Plane"
            ):
                blender_renderer.render_scene_video(
                    {
                        "visual_mode": "macro_3d",
                        "frame_by_plane_required": True,
                    },
                    "unused.mp4",
                    enabled=True,
                )
            find_blender.assert_not_called()

    def test_daily_frame_by_plane_scene_rejects_missing_manifest_file(self):
        with tempfile.TemporaryDirectory() as temp:
            missing = Path(temp) / "missing-background-manifest.json"
            with patch.object(blender_renderer, "_find_blender") as find_blender:
                with self.assertRaisesRegex(
                    blender_renderer.BlenderRenderError, "manifest does not exist"
                ):
                    blender_renderer.render_scene_video(
                        {
                            "visual_mode": "macro_3d",
                            "frame_by_plane_required": True,
                            "frame_by_plane_manifest": str(missing),
                        },
                        "unused.mp4",
                        enabled=True,
                    )
                find_blender.assert_not_called()

    def test_failed_blender_process_preserves_complete_stdout_and_stderr(self):
        import subprocess

        with tempfile.TemporaryDirectory() as temp:
            diagnostics = Path(temp) / "blender-diagnostics" / "scene-1.log"
            completed = subprocess.CompletedProcess(
                ["blender"], 1, stdout="stdout traceback tail", stderr="stderr exception detail"
            )
            with patch.object(blender_renderer.subprocess, "run", return_value=completed):
                with self.assertRaisesRegex(
                    blender_renderer.BlenderRenderError, "Full diagnostics"
                ):
                    blender_renderer._run(
                        ["blender"], 60, "Blender scene render",
                        diagnostics_path=diagnostics,
                    )
            saved = diagnostics.read_text(encoding="utf-8")
            self.assertIn("stdout traceback tail", saved)
            self.assertIn("stderr exception detail", saved)
            self.assertIn("returncode: 1", saved)

    def test_missing_mp4_preserves_child_process_output_when_blender_returns_zero(self):
        import subprocess

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "scene-1.mp4"
            child_output = subprocess.CompletedProcess(
                ["blender"], 0,
                stdout="BLENDER_FULL_FRAME_3D_RENDERED=/tmp/scene-1.mp4",
                stderr="renderer warning detail",
            )

            def fake_blender_run(command, timeout, label, diagnostics_path=None):
                return child_output

            with patch.object(
                blender_renderer, "_find_blender", return_value="/usr/bin/blender"
            ), patch.object(blender_renderer, "_run", side_effect=fake_blender_run):
                with self.assertRaisesRegex(
                    blender_renderer.BlenderRenderError, "full Blender diagnostics saved"
                ):
                    blender_renderer.render_scene_video(
                        {"visual_mode": "macro_3d"}, output, enabled=True
                    )

            diagnostics = root / "blender-diagnostics" / "scene-1.log"
            saved = diagnostics.read_text(encoding="utf-8")
            self.assertIn("BLENDER_FULL_FRAME_3D_RENDERED=", saved)
            self.assertIn("renderer warning detail", saved)
            self.assertIn("returncode: 0", saved)

    def test_daily_frame_by_plane_manifest_is_passed_to_blender_and_reported(self):
        import json
        import subprocess

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            manifest = root / "background-manifest.json"
            manifest.write_text('{"schema_version":1,"layers":[]}', encoding="utf-8")
            output = root / "scene.mp4"
            captured = {}

            def fake_blender_run(command, timeout, label, diagnostics_path=None):
                captured["command"] = command
                config_path = Path(command[command.index("--config") + 1])
                captured["config"] = json.loads(config_path.read_text(encoding="utf-8"))
                Path(command[command.index("--output") + 1]).write_bytes(b"V" * 5000)
                report = {"enabled": True, "layer_count": 3, "extension_version": "8.0.1"}
                return subprocess.CompletedProcess(
                    command, 0,
                    stdout="FRAME_BY_PLANE_REPORT=" + json.dumps(report) + "\n",
                    stderr="",
                )

            with patch.object(blender_renderer, "_find_blender", return_value="/usr/bin/blender"), \
                 patch.object(blender_renderer, "_run", side_effect=fake_blender_run), \
                 patch.object(
                     blender_renderer, "_probe_video",
                     return_value={
                         "duration_seconds": 8.0, "width": 720, "height": 1280,
                         "codec": "h264", "frame_rate": "25/1",
                     },
                 ), \
                 patch.object(
                     blender_renderer.subprocess, "run",
                     return_value=subprocess.CompletedProcess(
                         ["blender", "--version"], 0, stdout="Blender 5.2.4\n", stderr=""
                     ),
                 ):
                result = blender_renderer.render_scene_video(
                    {
                        "visual_mode": "macro_3d",
                        "frame_by_plane_required": True,
                        "frame_by_plane_manifest": str(manifest),
                    },
                    output,
                    enabled=True,
                    resolution=(720, 1280),
                    fps=25,
                    duration_seconds=8.0,
                )

            self.assertEqual(
                captured["config"]["frame_by_plane_manifest"], str(manifest)
            )
            self.assertTrue(captured["config"]["frame_by_plane_required"])
            self.assertNotIn("--factory-startup", captured["command"])
            self.assertEqual(result["frame_by_plane"]["layer_count"], 3)
            self.assertIn("Frame By Plane 2.5D", result["rendered_as"])



if __name__ == "__main__":
    unittest.main()
