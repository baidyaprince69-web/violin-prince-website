"""Offline tests for Phase 1 creative quality and resilient rendering."""
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("CF_ACCOUNT_ID", "test-account")
os.environ.setdefault("CF_AI_TOKEN", "test-ai-token")
ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from PIL import Image
import run as pipeline


class CreativeQualityTests(unittest.TestCase):
    def test_scene_timing_follows_narration_beats_and_fills_24_seconds(self):
        info = {
            "subtitle_cues": [
                {"start": 0.0, "end": 3.1, "text": "Hook"},
                {"start": 3.25, "end": 8.0, "text": "Context"},
                {"start": 8.15, "end": 14.4, "text": "Distinctive detail"},
                {"start": 14.55, "end": 20.1, "text": "Payoff"},
            ]
        }
        durations = pipeline.scene_durations_from_narration(info)
        self.assertEqual(len(durations), 3)
        self.assertTrue(all(value >= 4.8 for value in durations))
        self.assertAlmostEqual(sum(durations), 24.0, places=2)
        self.assertNotEqual(durations, (8.0, 8.0, 8.0))


    def test_motion_graphic_card_is_transparent_and_contains_scene_detail(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "motion-graphic.png"
            scene = {
                "caption": "A remarkable detail emerges",
                "graphic_label": "THE KEY DETAIL",
                "graphic_detail": "The original source confirms this detail",
            }
            pipeline.make_motion_graphic_card(scene, 1, {"title": "Test"}, target)
            with Image.open(target) as graphic:
                self.assertEqual(graphic.size, (620, 245))
                self.assertEqual(graphic.mode, "RGBA")
                self.assertEqual(graphic.getpixel((0, 0))[3], 0)
                self.assertGreater(graphic.getchannel("A").getbbox()[2], 500)

    def test_kinetic_captions_keep_measured_sentence_times_and_animation(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "narration.ass"
            pipeline.write_kinetic_ass(
                [{"start": 0.2, "end": 2.4, "text": "A remarkable detail emerges today."}],
                target,
            )
            content = target.read_text(encoding="utf-8")
            self.assertIn("Dialogue: 0,0:00:00.20,0:00:02.40,VP", content)
            self.assertIn("fad(180,220)", content)
            self.assertIn("008BCEEA", content)
            self.assertIn("remarkable", content)

    def test_camera_motion_varies_by_scene_but_keeps_smooth_easing(self):
        first = pipeline.camera_motion_filter(120, 0)
        second = pipeline.camera_motion_filter(120, 1)
        third = pipeline.camera_motion_filter(120, 2)
        self.assertNotEqual(first, second)
        self.assertNotEqual(second, third)
        self.assertIn("3-2*", first)

    def test_scene_timing_has_safe_equal_duration_fallback(self):
        self.assertEqual(
            pipeline.scene_durations_from_narration({"subtitle_cues": []}),
            (8.0, 8.0, 8.0),
        )

    def test_all_scenes_share_brand_art_direction_but_have_distinct_roles(self):
        plan = {"topic": "A violin component travelled into orbit"}
        scene = {"image_prompt": "A small violin bridge near an orbital satellite"}
        prompts = [
            pipeline._scene_visual_prompt(scene, index=i, plan=plan)
            for i in range(3)
        ]
        self.assertIn("SHOT 1 — HOOK", prompts[0])
        self.assertIn("SHOT 2 — MECHANISM", prompts[1])
        self.assertIn("SHOT 3 — PERFORMANCE PAYOFF", prompts[2])
        for prompt in prompts:
            self.assertIn("deep midnight navy", prompt)
            self.assertIn("original high-end photorealistic 3D CGI", prompt)
            self.assertIn("physically based rendering", prompt)
            self.assertNotIn("recreation of another creator", prompt)
            self.assertIn("Portrait 9:16 composition", prompt)
            self.assertLessEqual(len(prompt), 1800)
        self.assertEqual(len(set(prompts)), 3)

    def test_storyboard_preview_wraps_captions_without_overlapping_columns(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for index, colour in enumerate(((20, 40, 60), (60, 40, 20), (30, 60, 45))):
                path = Path(folder) / f"scene-{index + 1}.jpg"
                Image.new("RGB", (320, 480), colour).save(path)
                paths.append(path)
            plan = {
                "title": "A Violin With an Extraordinary Journey",
                "scenes": [
                    {"caption": "A violin component travels into orbit"},
                    {"caption": "A unique instrument is revealed on stage"},
                    {"caption": "Music connects the distant journey to Earth"},
                ],
            }
            target = Path(folder) / "storyboard.png"
            pipeline.make_storyboard_preview(plan, paths, target)
            self.assertTrue(target.is_file())
            with Image.open(target) as preview:
                self.assertEqual(preview.size, (1280, 900))


if __name__ == "__main__":
    unittest.main()
