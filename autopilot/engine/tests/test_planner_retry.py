"""Offline tests for automatic planner narration correction."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("CF_ACCOUNT_ID", "test-account")
os.environ.setdefault("CF_AI_TOKEN", "test-ai-token")
ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import run as pipeline


VALID_SCRIPT = (
    "Can one small violin part travel through space? "
    "A scientist sent a piece of it into orbit. "
    "It returned with a story no concert hall could contain. "
    "Now its music connects that distant journey with listeners here."
)
SHORT_SCRIPT = (
    "Can a violin part travel through space? "
    "A scientist sent it into orbit. "
    "It returned with a remarkable story. "
    "Now its music connects that journey with listeners."
)


def make_test_plan(script):
    url = "https://publisher.example/story-about-a-violin"
    return {
        "topic": "A violin component's journey",
        "title": "The Violin That Reached Orbit",
        "hook": "Can one small violin part travel through space?",
        "description": "A sourced human-interest story.",
        "hashtags": ["#Music", "#Discovery"],
        "narration_script": script,
        "narrative_style": "cinematic_story",
        "scenes": [
            {"caption": "A violin begins its journey", "image_prompt": "A violin in a concert hall"},
            {"caption": "A remarkable detail", "image_prompt": "A small violin component among stars"},
            {"caption": "A journey comes full circle", "image_prompt": "A violin under warm stage lights"},
        ],
        "sources": [url],
    }


class PlannerNarrationRetryTests(unittest.TestCase):
    def test_narration_validator_accepts_32_to_40_word_four_beat_script(self):
        self.assertEqual(pipeline.narration_validation_error(VALID_SCRIPT), "")
        self.assertEqual(len(pipeline.re.findall(r"\b[\w’'-]+\b", VALID_SCRIPT)), 37)

    def test_narration_validator_reports_actual_short_word_count(self):
        issue = pipeline.narration_validation_error(SHORT_SCRIPT)
        self.assertIn("27 spoken words", issue)
        self.assertIn("32–40", issue)

    def test_make_plan_repairs_short_narration_without_repeating_research(self):
        original_plan = make_test_plan(SHORT_SCRIPT)
        corrected_plan = make_test_plan(VALID_SCRIPT)
        ai_results = [
            {"response": original_plan},
            {"response": corrected_plan},
        ]
        item = {
            "title": "A violin component travelled to orbit",
            "summary": "A publisher reports an instrument component travelled to orbit.",
            "evidence_text": "A publisher's article reports this instrument component travelled to orbit.",
            "publisher_domain": "publisher.example",
            "url": "https://publisher.example/story-about-a-violin",
            "source": "Test Publisher",
        }

        with tempfile.TemporaryDirectory() as folder:
            original_work = pipeline.WORK
            try:
                pipeline.WORK = Path(folder)
                with patch.object(pipeline, "ai", side_effect=ai_results) as mock_ai:
                    result = pipeline.make_plan([item], recent=[])

                self.assertEqual(mock_ai.call_count, 2)
                self.assertEqual(result["narration_script"], VALID_SCRIPT)
                self.assertEqual(result["sources"], [item["url"]])
                self.assertTrue((Path(folder) / "creative_plan.json").is_file())
                repair_messages = mock_ai.call_args_list[1].args[1]["messages"]
                self.assertIn("Change only narration_script", repair_messages[0]["content"])
                self.assertIn("27 spoken words", repair_messages[1]["content"])
            finally:
                pipeline.WORK = original_work

    def test_make_plan_pads_short_second_response_without_another_ai_call(self):
        original_plan = make_test_plan(SHORT_SCRIPT)
        still_invalid = make_test_plan(SHORT_SCRIPT)
        item = {
            "title": "A violin component travelled to orbit",
            "summary": "A publisher reports an instrument component travelled to orbit.",
            "evidence_text": "A publisher's article reports this instrument component travelled to orbit.",
            "publisher_domain": "publisher.example",
            "url": "https://publisher.example/story-about-a-violin",
            "source": "Test Publisher",
        }
        with tempfile.TemporaryDirectory() as folder:
            original_work = pipeline.WORK
            try:
                pipeline.WORK = Path(folder)
                with patch.object(
                    pipeline, "ai",
                    side_effect=[{"response": original_plan}, {"response": still_invalid}]
                ) as mock_ai:
                    result = pipeline.make_plan([item], recent=[])
                self.assertEqual(mock_ai.call_count, 2)
                self.assertEqual(pipeline.narration_validation_error(result["narration_script"]), "")
                self.assertEqual(len(pipeline.re.findall(r"\\b[\\w’'-]+\\b", result["narration_script"])), 32)
                self.assertEqual(result["sources"], [item["url"]])
                self.assertEqual(result["scenes"], original_plan["scenes"])
            finally:
                pipeline.WORK = original_work

    def test_pad_short_narration_adds_only_reflective_words(self):
        padded = pipeline.pad_short_narration(SHORT_SCRIPT)
        self.assertTrue(padded)
        self.assertEqual(pipeline.narration_validation_error(padded), "")
        self.assertIn("A scientist sent it into orbit", padded)
        self.assertEqual(len(padded.split(". ")), 4)


if __name__ == "__main__":
    unittest.main()
