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

    def test_full_track_events_cover_three_minutes_with_section_variation(self):
        events = violin_sampler._events("music-test", duration_seconds=180)
        self.assertEqual(events[0][2], 0)
        self.assertEqual(events[-1][2] + events[-1][3], 240)
        self.assertEqual(sum(item[3] for item in events), 240)
        self.assertTrue(all(55 <= item[0] <= 84 for item in events))
        first_section = [item[0] for item in events if item[2] < 32]
        second_section = [item[0] for item in events if 32 <= item[2] < 64]
        self.assertNotEqual(first_section, second_section)

    def test_duration_limits_reject_too_short_or_too_long_tracks(self):
        with self.assertRaisesRegex(ValueError, "between 24 and 600 seconds"):
            violin_sampler._events("music-test", duration_seconds=10)
        with self.assertRaisesRegex(ValueError, "between 24 and 600 seconds"):
            violin_sampler._events("music-test", duration_seconds=601)

    def test_real_sample_arrays_render_to_variable_duration_stereo_wav(self):
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
            target = Path(folder) / "sampled-violin-full-track.wav"
            violin_sampler.render_from_sample_arrays(
                target, manifest, samples, "music-test", duration_seconds=48
            )
            audio, rate = sf.read(str(target), dtype="float32", always_2d=True)
            self.assertEqual(rate, 24000)
            self.assertEqual(audio.shape, (48 * 24000, 2))
            self.assertGreater(float(np.max(np.abs(audio))), 0.01)
            self.assertLessEqual(float(np.max(np.abs(audio))), 1.0)

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
