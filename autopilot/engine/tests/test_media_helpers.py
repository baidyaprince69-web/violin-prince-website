"""Offline tests for the free Violin Prince media helpers."""
import sys
import tempfile
import unittest
import wave
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from synth_audio import create_original_soundtrack
from voiceover import split_sentences, write_srt


class SyntheticSoundtrackTests(unittest.TestCase):
    def test_original_bed_is_stereo_24_seconds_and_non_silent(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "bed.wav"
            create_original_soundtrack(target, seed_text="unit-test")
            with wave.open(str(target), "rb") as audio:
                self.assertEqual(audio.getnchannels(), 2)
                self.assertEqual(audio.getframerate(), 24000)
                self.assertEqual(audio.getnframes(), 24000 * 24)
                self.assertEqual(audio.getsampwidth(), 2)
                frames = audio.readframes(4000)
                self.assertNotEqual(frames, bytes(len(frames)))


class NarrationHelperTests(unittest.TestCase):
    def test_sentence_splitter_keeps_sentence_boundaries(self):
        result = split_sentences("First fact. A second idea! A final thought?")
        self.assertEqual(result, ["First fact.", "A second idea!", "A final thought?"])

    def test_srt_uses_real_sentence_timestamps(self):
        cues = [
            {"start": 0.25, "end": 1.85, "text": "The first sentence is spoken."},
            {"start": 2.10, "end": 3.90, "text": "The second sentence follows."},
        ]
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "narration.srt"
            write_srt(cues, target)
            text = target.read_text(encoding="utf-8")
            self.assertIn("00:00:00,250 --> 00:00:01,850", text)
            self.assertIn("00:00:02,100 --> 00:00:03,900", text)
            self.assertIn("The first sentence is spoken.", text.replace("\n", " "))
            self.assertIn("The second sentence follows.", text.replace("\n", " "))

    def test_empty_subtitle_cues_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                write_srt([], Path(folder) / "empty.srt")


if __name__ == "__main__":
    unittest.main()
