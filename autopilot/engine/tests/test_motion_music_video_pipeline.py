"""Regression tests for the researched Kokoro + Motion explainer pipeline."""
import os
import sys
import unittest
from unittest.mock import patch

ENGINE = __import__("pathlib").Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import run as pipeline


class MotionExplainerPipelineTests(unittest.TestCase):
    def test_full_motion_route_keeps_research_and_kokoro_prepare_stage(self):
        with patch.dict(os.environ, {
            "MOTION_HYPERFRAMES_RENDER_ENABLED": "true",
            "BLENDER_RENDER_ENABLED": "false",
            "PUBLISH_ENABLED": "false",
        }), patch.object(pipeline, "prepare_stage", return_value=0) as prepare, patch.object(
            pipeline, "visuals_stage", return_value=0
        ) as visuals, patch.object(pipeline, "render_stage", return_value=0) as render, patch.object(
            pipeline, "prepare_motion_music_video_stage",
            side_effect=AssertionError("the retired music-only route must not run"),
        ):
            result = pipeline.main(stage="full")

        self.assertEqual(result, 0)
        prepare.assert_called_once()
        visuals.assert_called_once_with("")
        render.assert_called_once()

    def test_motion_prepare_uses_the_same_researched_prepare_stage(self):
        with patch.dict(os.environ, {"MOTION_HYPERFRAMES_RENDER_ENABLED": "true"}), patch.object(
            pipeline, "prepare_stage", return_value=0
        ) as prepare, patch.object(
            pipeline, "prepare_motion_music_video_stage",
            side_effect=AssertionError("the retired music-only route must not run"),
        ):
            result = pipeline.main(stage="prepare")

        self.assertEqual(result, 0)
        prepare.assert_called_once()

    def test_music_only_entry_point_fails_closed(self):
        with self.assertRaisesRegex(pipeline.PipelineError, "retired"):
            pipeline.prepare_motion_music_video_stage()


if __name__ == "__main__":
    unittest.main()
