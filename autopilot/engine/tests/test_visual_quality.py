"""Tests for the Violin Prince pre-render visual quality gate."""
from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import local_vector_illustrator as illustrator
from visual_quality import build_visual_quality_report


class VisualQualityTests(unittest.TestCase):
    def _make_assets(self, root: Path):
        scenes = [
            {"id": "hook", "visual_mode": "macro_illustration", "caption": "The violin's shape"},
            {"id": "mechanism", "visual_mode": "waveform", "caption": "Sound travels as waves"},
            {"id": "payoff", "visual_mode": "cover_performance", "caption": "Hear the violin"},
        ]
        paths = []
        for index, scene in enumerate(scenes):
            path = root / f"{scene['id']}.jpg"
            illustrator.render_scene(scene, index, {"title": "Test"}, path)
            paths.append(path)
        return scenes, paths

    def test_valid_story_package_passes_with_visual_style_and_instrument_contract(self):
        with tempfile.TemporaryDirectory() as folder:
            scenes, paths = self._make_assets(Path(folder))
            report = build_visual_quality_report(
                scenes, paths, story_profile="violin"
            )
            self.assertEqual(report["status"], "passed", report["errors"])
            self.assertTrue(report["passed"])
            self.assertEqual(report["instrument_specification"]["string_count"], 4)
            self.assertEqual(report["instrument_specification"]["tuning_peg_count"], 4)
            self.assertEqual(report["metrics"]["checks_passed"], report["metrics"]["checks_total"])
            self.assertIn("typography", report["visual_style_bible"])
            self.assertEqual(report["scenes"][0]["width"], 1024)

    def test_reused_image_content_is_blocked_even_when_scene_ids_differ(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scenes, paths = self._make_assets(root)
            duplicate = root / "duplicate.jpg"
            shutil.copy2(paths[0], duplicate)
            paths[1] = duplicate
            report = build_visual_quality_report(scenes, paths)
            self.assertEqual(report["status"], "failed")
            self.assertTrue(any("duplicates hook" in issue for issue in report["errors"]))

    def test_non_portrait_asset_is_blocked(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scenes = [
                {"id": "hook", "visual_mode": "macro_illustration", "caption": "A hook"},
                {"id": "payoff", "visual_mode": "cover_performance", "caption": "A payoff"},
            ]
            good = illustrator.render_scene(scenes[0], 0, {}, root / "good.jpg")
            bad = root / "bad.jpg"
            Image.new("RGB", (900, 900), (12, 20, 30)).save(bad, "JPEG")
            report = build_visual_quality_report(scenes, [good, bad])
            self.assertEqual(report["status"], "failed")
            self.assertTrue(any("portrait_framing" in issue for issue in report["errors"]))
            self.assertTrue(any("portrait_dimensions" in issue for issue in report["errors"]))

    def test_last_scene_must_be_the_musical_payoff(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scenes, paths = self._make_assets(root)
            scenes[-1]["visual_mode"] = "waveform"
            report = build_visual_quality_report(scenes, paths)
            self.assertEqual(report["status"], "failed")
            self.assertTrue(any("performance_payoff" in issue for issue in report["errors"]))


if __name__ == "__main__":
    unittest.main()
