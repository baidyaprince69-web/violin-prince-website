from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from violin_note_analysis import analyse_violin_note_events


class ViolinNoteAnalysisTests(unittest.TestCase):
    def test_extracts_two_sustained_notes_from_synthetic_monophonic_pcm(self):
        sample_rate = 22050
        duration = 2.2
        samples = np.zeros(int(sample_rate * duration), dtype=np.float32)
        for start, end, frequency in (
            (0.08, 0.43, 440.0),
            (0.55, 0.90, 493.883),
            (1.02, 1.37, 587.330),
            (1.49, 1.84, 659.255),
        ):
            left = int(start * sample_rate)
            right = int(end * sample_rate)
            time = np.arange(right - left, dtype=np.float32) / sample_rate
            envelope = np.minimum(1.0, np.minimum(time / 0.08, (end - start - time) / 0.08))
            samples[left:right] = 0.22 * envelope * (
                np.sin(2 * np.pi * frequency * time)
                + 0.20 * np.sin(2 * np.pi * frequency * 2 * time)
            )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "synthetic-violin.wav"
            sf.write(path, samples, sample_rate, subtype="PCM_16")
            report = analyse_violin_note_events(path)
        self.assertEqual(report["source"], "creator_uploaded_pcm_autocorrelation")
        self.assertEqual(report["status"], "passed")
        self.assertGreaterEqual(report["note_event_count"], 4)
        notes = [event["note"] for event in report["note_events"]]
        self.assertIn(69, notes)
        self.assertIn(76, notes)
        self.assertTrue(all(event["duration_seconds"] > 0 for event in report["note_events"]))
        self.assertTrue(all(event["confidence"] >= 0.70 for event in report["note_events"]))

    def test_silence_returns_no_invented_note_events(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "silence.wav"
            sf.write(path, np.zeros(22050 * 3, dtype=np.float32), 22050)
            report = analyse_violin_note_events(path)
        self.assertEqual(report["status"], "low_confidence")
        self.assertEqual(report["note_events"], [])
        self.assertEqual(report["note_event_count"], 0)


if __name__ == "__main__":
    unittest.main()
