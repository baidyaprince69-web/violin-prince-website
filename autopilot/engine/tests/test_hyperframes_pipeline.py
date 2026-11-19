"""Regression tests for Motion + HyperFrames project-path resolution."""
import ast
import inspect
import sys
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
