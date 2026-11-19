"""Regression tests for Motion + HyperFrames project-path resolution."""
import ast
import inspect
import json
import os
import subprocess
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

import hyperframes_pipeline as pipeline  # noqa: E402


class HyperFramesProjectPathTests(unittest.TestCase):
    def test_production_renderer_assigns_project_dir_before_use(self):
        source = inspect.getsource(pipeline.render_daily_plan)
        function = next(
            node for node in ast.parse(source).body
            if isinstance(node, ast.FunctionDef) and node.name == "render_daily_plan"
        )
        stores = [
            node.lineno for node in ast.walk(function)
            if isinstance(node, ast.Name)
            and node.id == "project_dir"
            and isinstance(node.ctx, ast.Store)
        ]
        loads = [
            node.lineno for node in ast.walk(function)
            if isinstance(node, ast.Name)
            and node.id == "project_dir"
            and isinstance(node.ctx, ast.Load)
        ]
        self.assertTrue(stores, "render_daily_plan must assign project_dir")
        self.assertTrue(loads, "render_daily_plan must use project_dir")
        self.assertLess(min(stores), min(loads))

    def test_scene_project_directory_is_absolute(self):
        project_dir = pipeline._absolute_scene_project_directory(Path("work"))
        self.assertTrue(project_dir.is_absolute())
        self.assertEqual(project_dir, Path("work").resolve() / "animation2d")

    def test_daily_renderer_smoke_uses_real_scene_projects_without_remote_services(self):
        from types import SimpleNamespace

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            work = Path("work")
            output = work / "output"
            work_absolute = root / "work"
            output_absolute = work_absolute / "output"
            output_absolute.mkdir(parents=True)
            images = []
            for index in range(3):
                image = root / f"scene-{index + 1}.png"
                image.write_bytes(f"synthetic-scene-{index + 1}".encode("utf-8"))
                images.append(image)

            audio = root / "audio.wav"
            narration = root / "narration.wav"
            audio.write_bytes(b"synthetic-audio")
            narration.write_bytes(b"synthetic-narration")
            font = root / "test-font.ttf"
            font.write_bytes(b"synthetic-font")

            scenes = [
                {
                    "id": scene_id,
                    "caption": caption,
                    "title": caption,
                    "narration_sentence_indexes": [index],
                }
                for index, (scene_id, caption) in enumerate(
                    (("hook", "The hook"), ("detail", "The detail"), ("payoff", "The payoff"))
                )
            ]
            plan = {"title": "Offline renderer smoke test", "scenes": scenes}
            narration_info = {
                "subtitle_cues": [],
                "word_cues": [
                    {"text": "First", "start": 0.4, "end": 1.2, "sentence_index": 0},
                    {"text": "Second", "start": 6.5, "end": 7.4, "sentence_index": 1},
                    {"text": "Third", "start": 13.0, "end": 13.9, "sentence_index": 2},
                ],
            }
            engine = SimpleNamespace(
                W=720,
                H=1280,
                FPS=25,
                WORK=work,
                OUT=output,
                transition_duration=lambda _plan: 0.32,
                scene_transition=lambda _plan, _index: "fade",
                write_kinetic_ass=lambda _cues, path, _words: Path(path).write_text(
                    "[Script Info]\n", encoding="utf-8"
                ),
                _ensure_brand_fonts=lambda: {"serif": str(font)},
                validate_final_video=lambda _path: {"status": "passed"},
                make_render_contact_sheet=lambda _video, path, _points: (
                    Path(path).write_bytes(b"synthetic-contact-sheet") and Path(path)
                ),
            )

            build_calls = []

            def fake_run(command, *, cwd, timeout=900):
                name = Path(command[0]).name
                if name == "node" and len(command) > 1 and command[1] == "--version":
                    return subprocess.CompletedProcess(command, 0, stdout="v22.0.0", stderr="")
                if name == "npm":
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                if name == "node" and str(command[1]).endswith("build.mjs"):
                    project = Path(command[command.index("--project") + 1])
                    out_dir = Path(command[command.index("--out-dir") + 1])
                    self.assertTrue(project.is_absolute())
                    self.assertTrue(project.is_file())
                    self.assertTrue(out_dir.is_absolute())
                    self.assertEqual(Path(cwd), pipeline.ANIMATION2D_DIR)
                    build_calls.append((project, out_dir))
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                if name == "hyperframes":
                    if "render" in command:
                        target = Path(command[command.index("--output") + 1])
                        target.write_bytes(b"R" * 8192)
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                if name == "ffprobe":
                    stream = {
                        "streams": [{
                            "codec_name": "h264",
                            "width": 720,
                            "height": 1280,
                            "r_frame_rate": "25/1",
                        }]
                    }
                    return subprocess.CompletedProcess(
                        command, 0, stdout=json.dumps(stream), stderr=""
                    )
                if name == "ffmpeg":
                    command_cwd = Path(cwd)
                    if not command_cwd.is_absolute():
                        command_cwd = Path.cwd() / command_cwd
                    for index, argument in enumerate(command[:-1]):
                        if argument == "-i":
                            source_path = Path(command[index + 1])
                            if not source_path.is_absolute():
                                source_path = command_cwd / source_path
                            self.assertTrue(
                                source_path.is_file(),
                                f"FFmpeg input must exist from its working directory: {source_path}",
                            )
                    target = Path(command[-1])
                    if not target.is_absolute():
                        target = command_cwd / target
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"F" * 8192)
                    return subprocess.CompletedProcess(command, 0, stdout="", stderr="")
                raise AssertionError(f"Unexpected renderer command: {command}")

            audio_analysis = types.ModuleType("audio_analysis")
            audio_analysis.analyse_audio_file = lambda *_args, **_kwargs: {"confidence": 0.0}
            media_verification = types.ModuleType("media_verification")
            media_verification.verify_scene_assets = lambda *_args, **_kwargs: {
                "status": "passed", "errors": [], "warnings": []
            }
            character_validation = types.ModuleType("character_visual_validation")
            character_validation.verify_character_visuals = lambda *_args, **_kwargs: {
                "status": "passed", "errors": [], "warnings": []
            }

            original_cwd = Path.cwd()
            try:
                os.chdir(root)
                with (
                    patch.dict(sys.modules, {
                        "audio_analysis": audio_analysis,
                        "media_verification": media_verification,
                        "character_visual_validation": character_validation,
                    }),
                    patch.object(pipeline, "_run", side_effect=fake_run),
                    patch.object(pipeline.shutil, "which", side_effect=lambda name: f"/usr/bin/{name}"),
                ):
                    quality = pipeline.render_daily_plan(
                        engine, plan, images, audio, narration, narration_info, characters=[]
                    )
            finally:
                os.chdir(original_cwd)

            expected_project_root = (work_absolute / "animation2d").resolve()
            self.assertEqual(len(build_calls), 3)
            self.assertTrue(all(path.is_relative_to(expected_project_root) for path, _ in build_calls))
            self.assertTrue(all(out.is_absolute() for _, out in build_calls))
            self.assertTrue(all(path.is_file() for path, _ in build_calls))
            self.assertTrue((output_absolute / "violin-prince-short.mp4").is_file())
            self.assertEqual(quality["visual_engine"], "Motion + HyperFrames 2D scene renderer")
            self.assertEqual(quality["scene_render_checkpoints"]["rendered_scene_count"], 3)

    def test_node_builder_receives_absolute_project_and_output_paths(self):
        # Production's Python process runs from the repository root, while
        # build.mjs runs with autopilot/engine/animation2d as its cwd.
        project = Path("work/animation2d/render-scenes/scene-one/project.json")
        output_dir = Path("work/animation2d/render-scenes/scene-one")

        with patch.object(pipeline, "_run") as run:
            pipeline._build_motion_project("node", project, output_dir)

        command = run.call_args.args[0]
        self.assertEqual(command[2], "--project")
        self.assertEqual(command[3], str(project.resolve()))
        self.assertEqual(command[4], "--out-dir")
        self.assertEqual(command[5], str(output_dir.resolve()))
        self.assertTrue(Path(command[3]).is_absolute())
        self.assertTrue(Path(command[5]).is_absolute())
        self.assertEqual(run.call_args.kwargs["cwd"], pipeline.ANIMATION2D_DIR)
        self.assertEqual(run.call_args.kwargs["timeout"], 180)


if __name__ == "__main__":
    unittest.main()
