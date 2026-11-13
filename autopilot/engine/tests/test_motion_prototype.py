"""Offline checks for the V3 motion renderer inputs and second-story fixture."""
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image
import numpy as np
import soundfile as sf

ENGINE = Path(__file__).resolve().parents[1]
import sys
sys.path.insert(0, str(ENGINE))

from motion_prototype import _build_second_story_package, _music_energy_samples


class MotionPrototypeInputTests(unittest.TestCase):
    def test_music_energy_is_normalised_and_time_sampled(self):
        sample_rate = 24000
        silence = np.zeros(sample_rate // 2, dtype=np.float32)
        active_time = np.arange(sample_rate // 2, dtype=np.float32) / sample_rate
        active = 0.45 * np.sin(2 * np.pi * 440 * active_time).astype(np.float32)
        waveform = np.concatenate([silence, active])
        with tempfile.TemporaryDirectory() as folder:
            audio_path = Path(folder) / "music.wav"
            sf.write(audio_path, waveform, sample_rate)
            envelope = _music_energy_samples(audio_path, step_ms=50)

        self.assertGreaterEqual(len(envelope), 18)
        self.assertTrue(all(0.0 <= value <= 1.0 for value in envelope))
        self.assertGreater(max(envelope), 0.65)
        self.assertLess(min(envelope), 0.20)

    def test_second_story_package_is_distinct_and_has_three_visuals(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source"
            source.mkdir()
            (source / "stage.json").write_text(
                json.dumps({"asset": {"audio_source": "sampled_violin_cc0"}}),
                encoding="utf-8",
            )
            (source / "soundtrack.wav").write_bytes(b"fixture-audio")
            package = _build_second_story_package(source, root / "output")

            plan = json.loads((package / "creative_plan.json").read_text(encoding="utf-8"))
            self.assertEqual(plan["title"], "How a Violin Turns Motion into Music")
            self.assertIn("sticking and slipping", plan["narration_script"])
            self.assertEqual(len(plan["scenes"]), 3)
            self.assertEqual(
                json.loads((package / "stage.json").read_text(encoding="utf-8"))
                ["asset"]["audio_source"],
                "sampled_violin_cc0",
            )
            for index in range(1, 4):
                image_path = package / f"scene-{index}.jpg"
                self.assertTrue(image_path.is_file())
                self.assertGreater(image_path.stat().st_size, 10000)
                with Image.open(image_path) as image:
                    self.assertEqual(image.size, (720, 1280))

            words = plan["narration_script"].split()
            self.assertGreaterEqual(len(words), 30)
            self.assertLessEqual(len(words), 48)


if __name__ == "__main__":
    unittest.main()
