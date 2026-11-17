from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

from media_verification import verify_audio_samples, verify_image_asset, verify_scene_assets


class MediaVerificationTests(unittest.TestCase):
    def test_image_asset_reports_dimensions_alpha_and_hash(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "scene.png"
            image = Image.new("RGBA", (640, 640), (20, 40, 80, 255))
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, 160, 640), fill=(220, 180, 70, 255))
            draw.rectangle((160, 0, 320, 320), fill=(40, 180, 140, 255))
            draw.ellipse((350, 120, 590, 580), fill=(210, 80, 100, 255))
            image.save(path)
            report = verify_image_asset(path)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["width"], 640)
        self.assertEqual(len(report["sha256"]), 64)

    def test_blank_audio_fails_and_clean_audio_passes(self):
        self.assertEqual(verify_audio_samples(np.zeros((1000, 2)), 22050)["status"], "failed")
        clean = np.zeros((22050, 2), dtype=np.float32)
        clean[:, 0] = 0.2
        clean[:, 1] = 0.18
        self.assertEqual(verify_audio_samples(clean, 22050)["status"], "passed")

    def test_scene_set_flags_duplicate_visuals_without_silent_acceptance(self):
        with tempfile.TemporaryDirectory() as temporary:
            one = Path(temporary) / "one.png"
            two = Path(temporary) / "two.png"
            image = Image.new("RGBA", (600, 600), (80, 40, 20, 255))
            draw = ImageDraw.Draw(image)
            draw.rectangle((0, 0, 250, 600), fill=(200, 140, 40, 255))
            draw.ellipse((300, 100, 550, 500), fill=(30, 150, 190, 255))
            image.save(one)
            image.save(two)
            scenes = [
                {"id": "one", "narration_sentence_indexes": [0]},
                {"id": "two", "narration_sentence_indexes": [1]},
            ]
            report = verify_scene_assets(scenes, [one, two], total_seconds=24, narration_info={})
        self.assertEqual(report["status"], "warning")
        self.assertIn("duplicate_scene_image_content", report["warnings"])

    def test_word_cues_must_match_approved_script_and_scene_map(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            one = root / "one.png"
            two = root / "two.png"
            for path in (one, two):
                image = Image.new("RGBA", (600, 600), (80, 40, 20, 255))
                ImageDraw.Draw(image).rectangle((0, 0, 250, 600), fill=(200, 140, 40, 255))
                image.save(path)
            scenes = [
                {"id": "one", "narration_sentence_indexes": [0]},
                {"id": "two", "narration_sentence_indexes": [1]},
            ]
            cues = [
                {"text": "We", "start": 0.0, "end": 0.2, "sentence_index": 0},
                {"text": "play", "start": 0.2, "end": 0.4, "sentence_index": 1},
            ]
            report = verify_scene_assets(
                scenes,
                [one, two],
                total_seconds=24,
                narration_info={"word_cues": cues},
                expected_narration_script="We play violin.",
            )
        self.assertEqual(report["status"], "failed")
        self.assertIn("word_cues_do_not_match_approved_narration_script", report["errors"])


if __name__ == "__main__":
    unittest.main()
