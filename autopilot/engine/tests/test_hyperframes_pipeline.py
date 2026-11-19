"""Regression tests for Motion + HyperFrames project-path resolution."""
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

import hyperframes_pipeline as pipeline  # noqa: E402


class HyperFramesProjectPathTests(unittest.TestCase):
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
