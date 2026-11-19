"""Tests for narration-aware visual composition and presenter direction."""

import sys
import unittest
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

from scene_director import SceneDirectionError, direct_scene_composition  # noqa: E402


class SceneDirectorTests(unittest.TestCase):
    def _plan(self):
        return {
            "use_violin_prince_presenter": True,
            "scenes": [
                {"id": "hook", "caption": "Could your room change your mix?"},
                {
                    "id": "explain",
                    "caption": "Measure and correct the room",
                    "graphic_data": {
                        "type": "process_flow",
                        "title": "ROOMTUNE SIGNAL PATH",
                        "items": [
                            "MEASURE THE ROOM",
                            "APPLY DSP CORRECTION",
                            "ADJUST MONITOR OUTPUT",
                        ],
                    },
                },
                {"id": "payoff", "caption": "Hear the violin. Trust the mix."},
            ],
        }

    def _timeline(self):
        return {
            "scenes": [
                {
                    "scene_id": "hook", "start": 0.0, "duration": 5.0,
                    "narration_sentence_indexes": [0],
                },
                {
                    "scene_id": "explain", "start": 4.7, "duration": 9.0,
                    "narration_sentence_indexes": [1, 2],
                },
                {
                    "scene_id": "payoff", "start": 13.4, "duration": 10.0,
                    "narration_sentence_indexes": [3],
                },
            ],
        }

    def _narration(self):
        return {
            "word_cues": [
                {"text": "Measure", "start": 5.2, "sentence_index": 1},
                {"text": "room", "start": 5.6, "sentence_index": 1},
                {"text": "DSP", "start": 7.0, "sentence_index": 2},
                {"text": "correction", "start": 7.4, "sentence_index": 2},
                {"text": "monitor", "start": 9.2, "sentence_index": 2},
                {"text": "output", "start": 9.6, "sentence_index": 2},
            ],
        }

    def test_presenter_is_reserved_for_the_explainer_scene_and_points_to_the_diagram(self):
        plan = self._plan()
        report = direct_scene_composition(plan, self._timeline(), self._narration())

        self.assertEqual(report["presenter_scene_id"], "explain")
        self.assertFalse(plan["scenes"][0]["character_actions"]["violin-prince"]["visible"])
        self.assertTrue(plan["scenes"][1]["character_actions"]["violin-prince"]["visible"])
        self.assertFalse(plan["scenes"][2]["character_actions"]["violin-prince"]["visible"])

        action = plan["scenes"][1]["character_actions"]["violin-prince"]
        self.assertEqual(action["gesture"], "point_left")
        self.assertGreater(action["scale"], 0.4)
        self.assertGreaterEqual(action["x"], 360)
        self.assertLess(action["x"] + (720 * action["scale"]), 720)
        self.assertEqual(
            plan["scenes"][1]["visual_composition"]["layout"],
            "graphic_left_presenter_right",
        )

    def test_graphic_steps_follow_matching_narration_words(self):
        plan = self._plan()
        direct_scene_composition(plan, self._timeline(), self._narration())
        items = plan["scenes"][1]["graphic_data"]["items"]
        self.assertEqual([item["reveal_at"] for item in items], [0.5, 2.3, 4.5])
        self.assertEqual(items[0]["reveal_duration"], 0.52)

    def test_presenter_is_hidden_when_not_enabled(self):
        plan = self._plan()
        plan["use_violin_prince_presenter"] = False
        report = direct_scene_composition(plan, self._timeline(), self._narration())
        self.assertEqual(report["presenter_scene_id"], "")
        self.assertTrue(all(
            scene["character_actions"]["violin-prince"]["visible"] is False
            for scene in plan["scenes"]
        ))

    def test_unsupported_graphic_is_rejected_instead_of_silently_dropped(self):
        plan = self._plan()
        plan["scenes"][1]["graphic_data"]["type"] = "unknown_chart"
        with self.assertRaises(SceneDirectionError):
            direct_scene_composition(plan, self._timeline(), self._narration())


if __name__ == "__main__":
    unittest.main()
