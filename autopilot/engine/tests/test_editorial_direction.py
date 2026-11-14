"""Offline tests for the approved music-facts editorial direction."""
import sys
import tempfile
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from PIL import Image, ImageChops
from creative_direction import (
    BIOGRAPHY_PATTERNS,
    CHANNEL_BRIEF,
    STORY_TYPES,
    VISUAL_MODES,
    channel_fit_report,
    validate_creative_plan,
)
from motion_graphics import make_motion_graphic_frames


def valid_plan():
    return {
        "topic": "Why a violin can sound almost like a human voice",
        "title": "Why Does the Violin Sound Human?",
        "hook": "Why can strings sound human?",
        "story_type": "sound_and_perception",
        "cover_payoff": (
            "Use an original Violin Prince phrase with a long connected bow line "
            "to demonstrate how continuous tone shaping creates the vocal effect."
        ),
        "scenes": [
            {"caption": "A voice-like violin tone", "image_prompt": "3D violin macro", "visual_mode": "macro_3d"},
            {"caption": "How the sound is shaped", "image_prompt": "3D bow and string mechanism", "visual_mode": "mechanism_3d"},
            {"caption": "Hear the musical effect", "image_prompt": "Violin performance close-up", "visual_mode": "cover_performance"},
        ],
    }


class CreativeDirectionTests(unittest.TestCase):
    def test_approved_channel_format_is_machine_readable(self):
        self.assertIn("curiosity-driven music channel", CHANNEL_BRIEF)
        self.assertIn("violin_physics", STORY_TYPES)
        self.assertIn("cover_performance", VISUAL_MODES)

    def test_valid_music_facts_plan_passes(self):
        self.assertEqual(validate_creative_plan(valid_plan()), [])
        self.assertEqual(channel_fit_report(valid_plan())["status"], "passed")

    def test_individual_musician_biography_is_rejected(self):
        plan = valid_plan()
        plan["title"] = "The Life of a Young Violin Prodigy"
        plan["topic"] = "The personal journey of a famous violinist"
        issues = validate_creative_plan(plan)
        self.assertTrue(any("biographies" in item for item in issues))

    def test_competition_winner_story_is_rejected(self):
        plan = valid_plan()
        plan["title"] = "A Violinist Wins the Young Musician Competition"
        plan["topic"] = "A young violinist crowned winner of a competition"
        issues = validate_creative_plan(plan)
        self.assertTrue(any("competition-result" in item for item in issues))

    def test_missing_cover_payoff_is_rejected(self):
        plan = valid_plan()
        plan["cover_payoff"] = ""
        self.assertTrue(any("cover_payoff" in item for item in validate_creative_plan(plan)))

    def test_scene_three_must_be_the_performance_payoff(self):
        plan = valid_plan()
        plan["scenes"][2]["visual_mode"] = "waveform"
        self.assertTrue(any("Scene 3" in item for item in validate_creative_plan(plan)))

    def test_unknown_visual_mode_is_rejected(self):
        plan = valid_plan()
        plan["scenes"][1]["visual_mode"] = "celebrity_portrait"
        self.assertTrue(any("visual_mode" in item for item in validate_creative_plan(plan)))

    def test_animated_panel_has_transparent_background_and_changes_over_time(self):
        def test_font(size):
            from PIL import ImageFont
            return ImageFont.load_default()

        with tempfile.TemporaryDirectory() as folder:
            pattern = make_motion_graphic_frames(
                valid_plan()["scenes"][1],
                1,
                valid_plan(),
                Path(folder),
                frame_count=12,
                fps=8,
                font=test_font,
            )
            self.assertEqual(pattern.name, "frame-%05d.png")
            self.assertTrue((Path(folder) / "frame-00001.png").is_file())
            frame_paths = sorted(Path(folder).glob("frame-*.png"))
            self.assertEqual(len(frame_paths), 12)
            with Image.open(frame_paths[0]) as first:
                self.assertEqual(first.size, (620, 300))
                self.assertEqual(first.mode, "RGBA")
                self.assertEqual(first.getpixel((0, 0))[3], 0)
                first_copy = first.copy()
            with Image.open(frame_paths[-1]) as last:
                self.assertIsNotNone(ImageChops.difference(first_copy, last.convert("RGBA")).getbbox())


if __name__ == "__main__":
    unittest.main()
