"""Offline tests for the simplified ChatGPT-plan-to-2D production entry point."""
import sys
import unittest
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

import run_daily_plan as daily  # noqa: E402


def plan_fixture(script=None):
    return {
        "title": "How Sound Travels Through a Violin",
        "topic": "Violin acoustics",
        "narration_script": script or "A supplied explanation of how sound moves through a violin.",
        "sources": [{"url": "https://example.invalid/research"}],
        "narration_evidence": [{"sentence_number": 2, "quote": "Old quote check"}],
        "model_asset": {"provider": "old-3d-source"},
        "frame_by_plane_backgrounds": [{"layers": []}],
        "scenes": [
            {"caption": "The question"},
            {"caption": "The string"},
            {"caption": "The bridge"},
            {"caption": "The body"},
            {"caption": "The musical payoff"},
        ],
    }


class DailyPlanTests(unittest.TestCase):
    def test_plan_needs_no_research_or_quote_evidence(self):
        plan = daily.normalize_production_plan(plan_fixture())
        self.assertEqual(len(plan["scenes"]), 5)
        self.assertNotIn("sources", plan)
        self.assertNotIn("narration_evidence", plan)
        self.assertNotIn("model_asset", plan)
        self.assertNotIn("frame_by_plane_backgrounds", plan)

    def test_long_narration_is_not_rejected_by_a_fixed_word_count_gate(self):
        script = " ".join(["The violin creates a rich range of sounds."] * 20)
        plan = daily.normalize_production_plan(plan_fixture(script))
        self.assertGreater(len(plan["narration_script"].split()), 60)

    def test_plan_requires_non_empty_narration(self):
        with self.assertRaisesRegex(ValueError, "narration_script"):
            daily.normalize_production_plan(plan_fixture("   "))

    def test_plan_requires_five_2d_scenes(self):
        value = plan_fixture()
        value["scenes"] = value["scenes"][:3]
        with self.assertRaisesRegex(ValueError, "exactly five 2D scenes"):
            daily.normalize_production_plan(value)

    def test_scene_labels_are_filled_without_external_asset_prompts(self):
        plan = daily.normalize_production_plan(plan_fixture())
        self.assertEqual(plan["scenes"][0]["graphic_label"], "THE HOOK")
        self.assertEqual(plan["scenes"][4]["graphic_label"], "THE MUSICAL PAYOFF")
        self.assertEqual(plan["scenes"][2]["graphic_detail"], "The bridge")


if __name__ == "__main__":
    unittest.main()
