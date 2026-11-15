"""Unit tests for the private creator-performance video intake."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import run as pipeline


class PerformanceVideoAssetTests(unittest.TestCase):
    def test_accepts_supported_private_video_asset(self):
        media = b"x" * (20 * 1024)
        checked = pipeline._validate_performance_video_asset("my-violin-take.mp4", media)
        self.assertTrue(checked["available"])
        self.assertEqual(checked["filename"], "my-violin-take.mp4")
        self.assertEqual(checked["size_bytes"], len(media))

    def test_rejects_audio_file_as_performance_video(self):
        with self.assertRaisesRegex(pipeline.PipelineError, "MP4, MOV or WebM"):
            pipeline._validate_performance_video_asset("music-bed.wav", b"x" * 20_000)

    def test_rejects_oversized_asset(self):
        with patch.object(pipeline, "MAX_PERFORMANCE_VIDEO_BYTES", 1024):
            with self.assertRaisesRegex(pipeline.PipelineError, "90 MB"):
                pipeline._validate_performance_video_asset("take.mp4", b"x" * 1025)

    def test_missing_optional_video_is_reported_as_unavailable(self):
        with patch.dict(os.environ, {"VIOLIN_PERFORMANCE_VIDEO_PATH": ""}):
            metadata, media = pipeline.get_creator_performance_video()
        self.assertFalse(metadata["available"])
        self.assertEqual(metadata["source"], "none")
        self.assertEqual(media, b"")


if __name__ == "__main__":
    unittest.main()
