"""Regression tests for custom violin audio and stable camera movement."""
import os
import sys
import tempfile
import unittest
import wave
from array import array
from pathlib import Path
from unittest.mock import patch

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import run as pipeline
import violin_sampler


class AudioStrategyTests(unittest.TestCase):
    def _write_pcm_wav(self, path, seconds):
        sample_rate = 22050
        samples = array("h", [0] * (sample_rate * seconds))
        with wave.open(str(path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(sample_rate)
            output.writeframes(samples.tobytes())

    def test_creator_recorded_violin_is_preferred_when_present(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            recording = folder / "violin-performance.wav"
            self._write_pcm_wav(recording, 24)
            with patch.object(pipeline, "API", ""), patch.dict(
                os.environ, {"VIOLIN_RECORDING_PATH": str(recording)}
            ):
                metadata, audio = pipeline.get_audio()
            self.assertEqual(metadata["audio_source"], "creator_recorded_violin")
            self.assertEqual(metadata["duration_seconds"], 24.0)
            self.assertEqual(audio, recording.read_bytes())

    def test_short_violin_recording_fails_clearly_instead_of_looping_badly(self):
        with tempfile.TemporaryDirectory() as folder:
            recording = Path(folder) / "short.wav"
            self._write_pcm_wav(recording, 6)
            with patch.object(pipeline, "API", ""), patch.dict(
                os.environ, {"VIOLIN_RECORDING_PATH": str(recording)}
            ):
                with self.assertRaisesRegex(pipeline.PipelineError, "at least 24 seconds"):
                    pipeline.get_audio()

    def test_missing_recording_uses_non_violin_ambient_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            missing = Path(folder) / "not-present.wav"
            original_work = pipeline.WORK
            pipeline.WORK = Path(folder) / "work"
            try:
                with patch.object(pipeline, "API", ""), patch.object(
                    violin_sampler, "create_sampled_violin_bed",
                    side_effect=RuntimeError("offline test: sample pack unavailable")
                ), patch.dict(os.environ, {"VIOLIN_RECORDING_PATH": str(missing)}):
                    metadata, audio = pipeline.get_audio()
                self.assertEqual(metadata["audio_source"], "generated_ambient_fallback")
                self.assertGreater(len(audio), 100000)
                import io
                with wave.open(io.BytesIO(audio), "rb") as source:
                    self.assertEqual(source.getnchannels(), 2)
                    self.assertEqual(source.getframerate(), 24000)
                    self.assertEqual(source.getnframes() / source.getframerate(), 24.0)
            finally:
                pipeline.WORK = original_work

    def test_camera_motion_uses_stable_framing_without_repeated_zoom(self):
        expressions = [pipeline.camera_motion_filter(600, index) for index in range(3)]
        self.assertTrue(all("zoompan" not in expression for expression in expressions))
        self.assertEqual(expressions[0], expressions[1])
        self.assertEqual(expressions[1], expressions[2])
        self.assertTrue(all("fps=" in expression and "setsar=1" in expression for expression in expressions))


if __name__ == "__main__":
    unittest.main()
