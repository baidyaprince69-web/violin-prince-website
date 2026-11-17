from __future__ import annotations

import unittest

from creative_direction import validate_creative_plan
from visual_reference import normalize_visual_reference


class FlexibleScenePlanTests(unittest.TestCase):
    def _plan(self, count: int):
        modes = [
            "macro_illustration",
            "waveform",
            "comparison",
            "cover_performance",
            "melody_map",
        ][:count]
        if count == 2:
            modes = ["macro_illustration", "cover_performance"]
        return {
            "story_type": "violin_physics",
            "topic": "How a violin string creates changing sound",
            "title": "The Hidden Motion of a Violin String",
            "cover_payoff": "An original violin phrase demonstrates the difference between steady and changing string vibration.",
            "scenes": [
                {
                    "visual_mode": mode,
                    "caption": f"Scene {index + 1}",
                    "image_prompt": f"Original illustration for {mode}",
                }
                for index, mode in enumerate(modes)
            ],
        }

    def test_creative_validation_accepts_two_scenes(self):
        self.assertEqual(validate_creative_plan(self._plan(2)), [])

    def test_creative_validation_accepts_four_scenes(self):
        self.assertEqual(validate_creative_plan(self._plan(4)), [])

    def test_creative_validation_rejects_one_or_five_scenes(self):
        for count in (1, 5):
            with self.subTest(count=count):
                self.assertTrue(validate_creative_plan(self._plan(count)))

    def test_visual_reference_guidance_expands_and_contracts_with_scene_count(self):
        four_scenes = self._plan(4)["scenes"]
        profile = normalize_visual_reference(
            {
                "motion_profile": "mixed",
                "scene_guidance": [
                    {"camera_move": "pan_left"},
                    {"camera_move": "pan_right"},
                    {"camera_move": "pan_up"},
                ],
            },
            four_scenes,
        )
        self.assertEqual(len(profile["scene_guidance"]), 4)
        self.assertEqual(profile["scene_guidance"][0]["camera_move"], "pan_left")
        self.assertEqual(profile["scene_guidance"][3]["camera_move"], "locked")

        two_scenes = self._plan(2)["scenes"]
        contracted = normalize_visual_reference(
            {
                "motion_profile": "mixed",
                "scene_guidance": [
                    {"camera_move": "pan_left"},
                    {"camera_move": "pan_right"},
                    {"camera_move": "pan_up"},
                ],
            },
            two_scenes,
        )
        self.assertEqual(len(contracted["scene_guidance"]), 2)
        self.assertEqual(contracted["scene_guidance"][1]["camera_move"], "pan_right")


if __name__ == "__main__":
    unittest.main()
