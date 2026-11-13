"""Offline tests for native Kokoro word-level timestamp extraction."""
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from voiceover import word_cues_from_tokens


class WordTimingTests(unittest.TestCase):
    def test_uses_native_token_times_and_adds_chunk_offset(self):
        tokens = [
            SimpleNamespace(text="Hello,", start_ts=0.10, end_ts=0.42),
            SimpleNamespace(text=" ", start_ts=0.42, end_ts=0.42),
            SimpleNamespace(text="world", start_ts=0.48, end_ts=0.91),
        ]
        cues = word_cues_from_tokens(tokens, offset_seconds=2.0, chunk_duration=1.0)
        self.assertEqual(cues, [
            {"start": 2.1, "end": 2.42, "text": "Hello,"},
            {"start": 2.48, "end": 2.91, "text": "world"},
        ])

    def test_clamps_word_end_to_audio_chunk_duration(self):
        token = SimpleNamespace(text="edge", start_ts=0.8, end_ts=1.4)
        cues = word_cues_from_tokens([token], offset_seconds=0.5, chunk_duration=1.0)
        self.assertEqual(cues, [{"start": 1.3, "end": 1.5, "text": "edge"}])

    def test_skips_missing_invalid_and_zero_length_token_times(self):
        tokens = [
            SimpleNamespace(text="missing", start_ts=None, end_ts=None),
            SimpleNamespace(text="backwards", start_ts=0.7, end_ts=0.2),
            SimpleNamespace(text="tiny", start_ts=0.2, end_ts=0.21),
            SimpleNamespace(text="valid", start_ts=0.3, end_ts=0.5),
        ]
        cues = word_cues_from_tokens(tokens, chunk_duration=1.0)
        self.assertEqual(cues, [{"start": 0.3, "end": 0.5, "text": "valid"}])

    def test_empty_token_list_returns_no_cues(self):
        self.assertEqual(word_cues_from_tokens([], offset_seconds=3.0), [])


if __name__ == "__main__":
    unittest.main()
