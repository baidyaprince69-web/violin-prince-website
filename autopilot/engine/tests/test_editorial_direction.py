"""Tests for the approved five-scene 2D Violin Prince editorial direction."""
import sys
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from creative_direction import (
    BIOGRAPHY_PATTERNS,
    CHANNEL_BRIEF,
    STORY_TYPES,
    VISUAL_MODES,
    channel_fit_report,
    validate_creative_plan,
)


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
            {"caption": "A voice-like violin tone", "image_prompt": "Layered violin illustration", "visual_mode": "macro_illustration"},
            {"caption": "How the sound is shaped", "image_prompt": "Animated string mechanism", "visual_mode": "mechanism_diagram"},
            {"caption": "See the waveform", "image_prompt": "Animated waveform", "visual_mode": "waveform"},
            {"caption": "Map the melody", "image_prompt": "Animated melody map", "visual_mode": "melody_map"},
            {"caption": "Hear the musical effect", "image_prompt": "Illustrated violin performance", "visual_mode": "cover_performance"},
        ],
    }


class CreativeDirectionTests(unittest.TestCase):
    def test_approved_channel_format_is_machine_readable(self):
        self.assertIn("curiosity-driven music channel", CHANNEL_BRIEF)
        self.assertIn("violin_physics", STORY_TYPES)
        self.assertIn("cover_performance", VISUAL_MODES)
        self.assertIn("full_screen_2d", VISUAL_MODES)
        self.assertTrue(all("3d" not in mode for mode in VISUAL_MODES))

    def test_valid_music_facts_plan_passes(self):
        self.assertEqual(validate_creative_plan(valid_plan()), [])
        self.assertEqual(channel_fit_report(valid_plan())["status"], "passed")

    def test_five_scene_2d_format_is_required(self):
        plan = valid_plan()
        plan["scenes"] = plan["scenes"][:3]
        issues = validate_creative_plan(plan)
        self.assertTrue(any("exactly five visual story beats" in item for item in issues))

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

    def test_fifth_scene_must_be_the_performance_payoff(self):
        plan = valid_plan()
        plan["scenes"][4]["visual_mode"] = "waveform"
        self.assertTrue(any("Scene 5" in item for item in validate_creative_plan(plan)))

    def test_unknown_visual_mode_is_rejected(self):
        plan = valid_plan()
        plan["scenes"][1]["visual_mode"] = "celebrity_portrait"
        issues = validate_creative_plan(plan)
        self.assertTrue(any("visual_mode" in item for item in issues))


if __name__ == "__main__":
    unittest.main()
