"""Offline tests for the local sampled-violin Motion music-video path."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import run as pipeline


class MotionMusicVideoPipelineTests(unittest.TestCase):
    def test_full_stage_uses_local_sampler_package_not_legacy_story_ai(self):
        asset = {
            "filename": "sampled-violin-background.wav",
            "audio_source": "sampled_violin_cc0",
            "kind": "generated_sampled_instrument",
            "duration_seconds": 180.0,
            "sample_rate": 24000,
            "license": "CC0-1.0",
            "source_library": "VSCO 2 Community Edition",
            "sample_bank_revision": "test-revision",
        }
        audio = b"sampled violin fixture bytes " * 300

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old_work, old_out, old_package, old_api = (
                pipeline.WORK, pipeline.OUT, pipeline.PACKAGE, pipeline.API
            )
            pipeline.WORK = root / "work"
            pipeline.OUT = root / "work" / "output"
            pipeline.PACKAGE = root / "work" / "package"
            pipeline.API = ""
            try:
                with patch.object(pipeline, "get_audio", return_value=(asset, audio)), patch.object(
                    pipeline, "prepare_stage",
                    side_effect=AssertionError("legacy story/news preparation must not run"),
                ), patch.object(pipeline, "render_stage", return_value=0) as render, patch.dict(
                    os.environ,
                    {
                        "MOTION_HYPERFRAMES_RENDER_ENABLED": "true",
                        "BLENDER_RENDER_ENABLED": "false",
                        "PUBLISH_ENABLED": "false",
                    },
                ):
                    result = pipeline.main(stage="full")

                self.assertEqual(result, 0)
                render.assert_called_once()

                paths = pipeline._package_paths()
                metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
                plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
                quality = json.loads(paths["quality_control"].read_text(encoding="utf-8"))

                self.assertEqual(metadata["production_type"], "motion_music_video")
                self.assertEqual(metadata["asset"]["audio_source"], "sampled_violin_cc0")
                self.assertEqual(metadata["narration_info"], {})
                self.assertEqual(plan["story_type"], "music_production")
                self.assertEqual(len(plan["scenes"]), 3)
                self.assertEqual(quality["status"], "passed")
                self.assertEqual(quality["production_type"], "motion_music_video")
                self.assertFalse(paths["narration"].exists())
                self.assertEqual(json.loads(paths["research"].read_text(encoding="utf-8")), [])

                prepared_plan, prepared_metadata, narration, _, _ = pipeline._read_package(
                    require_images=False
                )
                self.assertEqual(prepared_metadata["production_type"], "motion_music_video")
                self.assertEqual(prepared_plan["topic"], "Original Solo Violin Composition")
                self.assertEqual(narration, {})
            finally:
                pipeline.WORK, pipeline.OUT, pipeline.PACKAGE, pipeline.API = (
                    old_work, old_out, old_package, old_api
                )


if __name__ == "__main__":
    unittest.main()
