"""Offline tests for the CC0 sampled-violin renderer."""
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import violin_sampler


class SampledViolinTests(unittest.TestCase):
    def test_phrase_is_24_seconds_and_uses_only_supported_midi_notes(self):
        events = violin_sampler._events("music-test")
        self.assertEqual(sum(item[3] for item in events), 32)
        self.assertEqual(events[0][2], 0)
        self.assertEqual(events[-1][2] + events[-1][3], 32)
        self.assertTrue(all(55 <= item[0] <= 84 for item in events))

    def test_real_sample_arrays_render_to_stereo_24_second_wav(self):
        sample_rate = 48000
        seconds = 2.5
        t = np.arange(int(sample_rate * seconds), dtype=np.float32) / sample_rate
        recorded_note = (0.2 * np.sin(2 * np.pi * 440 * t)).astype(np.float32)
        manifest = {
            "instrument": "violin",
            "license": "CC0-1.0",
            "zones": [{
                "file": "samples/violin.wav",
                "rootPitch": 69,
                "lowPitch": 55,
                "highPitch": 84,
                "lowVelocity": 0,
                "highVelocity": 127,
            }],
        }
        samples = {"samples/violin.wav": (recorded_note, sample_rate)}

        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "sampled-violin.wav"
            violin_sampler.render_from_sample_arrays(target, manifest, samples, "music-test")
            audio, rate = sf.read(str(target), dtype="float32", always_2d=True)
            self.assertEqual(rate, 24000)
            self.assertEqual(audio.shape, (24 * 24000, 2))
            self.assertGreater(float(np.max(np.abs(audio))), 0.01)
            self.assertLessEqual(float(np.max(np.abs(audio))), 1.0)

    def test_unmapped_note_fails_clearly(self):
        with self.assertRaisesRegex(RuntimeError, "No violin sample zone covers"):
            violin_sampler._choose_zone([], 69, 80)


if __name__ == "__main__":
    unittest.main()
