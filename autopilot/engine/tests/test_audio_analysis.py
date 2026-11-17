from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

from audio_analysis import analyse_audio_file


class AudioAnalysisTests(unittest.TestCase):
    def _write_click_track(self, path: Path, *, bpm: int = 120, seconds: float = 12.0):
        sample_rate = 22050
        samples = np.zeros(int(sample_rate * seconds), dtype=np.float32)
        period = 60.0 / bpm
        for beat in np.arange(0.15, seconds, period):
            start = int(beat * sample_rate)
            length = min(int(0.035 * sample_rate), len(samples) - start)
            if length > 0:
                samples[start:start + length] += np.hanning(max(2, length)).astype(np.float32)[:length] * 0.8
        sf.write(path, samples, sample_rate)

    def test_analyser_detects_tempo_from_decoded_click_track(self):
        with tempfile.TemporaryDirectory() as temporary:
            audio = Path(temporary) / "clicks.wav"
            self._write_click_track(audio, bpm=120)
            result = analyse_audio_file(audio)
        self.assertEqual(result["source"], "decoded_audio_spectral_flux_autocorrelation")
        self.assertIsNotNone(result["bpm"])
        self.assertLessEqual(abs(result["bpm"] - 120), 3.0)
        self.assertGreaterEqual(len(result["beat_times"]), 10)

    def test_silence_returns_low_confidence_and_no_fake_beats(self):
        with tempfile.TemporaryDirectory() as temporary:
            audio = Path(temporary) / "silence.wav"
            sf.write(audio, np.zeros(22050 * 5, dtype=np.float32), 22050)
            result = analyse_audio_file(audio)
        self.assertEqual(result["status"], "low_confidence")
        self.assertEqual(result["beat_times"], [])
        self.assertIsNone(result["bpm"])

    def test_declared_tempo_is_used_only_when_explicitly_supplied(self):
        with tempfile.TemporaryDirectory() as temporary:
            audio = Path(temporary) / "music.wav"
            self._write_click_track(audio, bpm=80)
            result = analyse_audio_file(audio, known_bpm=80)
        self.assertEqual(result["status"], "metadata_guided")
        self.assertEqual(result["bpm"], 80)
        self.assertEqual(result["confidence"], 1.0)


if __name__ == "__main__":
    unittest.main()
