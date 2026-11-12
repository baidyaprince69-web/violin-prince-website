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
    "A determined scientist sent one tiny piece into orbit. "
    "It became part of a story no concert hall could ever contain. "
    "Now its music connects that distant journey with listeners across the world."
)
FIRST_DRAFT_SCRIPT = (
    "Can this music really travel through space? "
    "A violin part travelled into orbit. "
    "It returned with a remarkable story. "
    "Now that journey connects distant listeners."
)
SHORT_SCRIPT = (
    "Can this music travel through space? "
    "A violin part travelled into orbit. "
    "It returned with a remarkable story. "
    "Now that journey connects distant listeners."
)


SCRIPT_33_WORDS = (
    "Can music travel beyond the concert hall? "
    "A small violin component has unexpectedly reached orbit. "
    "Its journey began with one unusual scientific idea. "
    "Now this remarkable story connects distant music and space listeners."
)
SCRIPT_34_WORDS = (
    "Can music travel beyond the concert hall? "
    "A small violin component has unexpectedly reached orbit. "
    "Its journey began with one unusual scientific idea. "
    "Now this remarkable story connects distant music and space listeners worldwide."
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
    def test_narration_validator_accepts_40_to_44_word_four_beat_script(self):
        self.assertEqual(pipeline.narration_validation_error(VALID_SCRIPT), "")
        self.assertEqual(len(pipeline.re.findall(r"\b[\w’'-]+\b", VALID_SCRIPT)), 41)

    def test_narration_validator_reports_actual_short_word_count(self):
        issue = pipeline.narration_validation_error(SHORT_SCRIPT)
        self.assertIn("24 spoken words", issue)
        self.assertIn("40–44", issue)

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
                self.assertIn("24 spoken words", repair_messages[1]["content"])
            finally:
                pipeline.WORK = original_work

    def test_make_plan_uses_final_word_budgeted_repair_without_research_repeat(self):
        original_plan = make_test_plan(SCRIPT_33_WORDS)
        first_repair = make_test_plan(SCRIPT_34_WORDS)
        final_repair = make_test_plan(VALID_SCRIPT)
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
                    side_effect=[
                        {"response": original_plan},
                        {"response": first_repair},
                        {"response": final_repair},
                    ],
                ) as mock_ai:
                    result = pipeline.make_plan([item], recent=[])

                self.assertEqual(mock_ai.call_count, 3)
                self.assertEqual(result["narration_script"], VALID_SCRIPT)
                self.assertEqual(pipeline.narration_validation_error(result["narration_script"]), "")
                self.assertEqual(result["sources"], [item["url"]])
                self.assertEqual(result["scenes"], original_plan["scenes"])
                final_system = mock_ai.call_args_list[2].args[1]["messages"][0]["content"]
                final_user = mock_ai.call_args_list[2].args[1]["messages"][1]["content"]
                self.assertIn("exactly these spoken-word counts", final_system)
                self.assertIn("8 words in sentence 1, 9 words in sentence 2", final_system)
                self.assertIn("no filler", final_system.lower())
                self.assertIn("34 spoken words", final_user)
                self.assertIn("Verified research evidence", final_user)
            finally:
                pipeline.WORK = original_work

    def test_make_plan_fails_safely_after_bounded_repairs_instead_of_padding(self):
        original_plan = make_test_plan(SCRIPT_33_WORDS)
        still_invalid = make_test_plan(SCRIPT_34_WORDS)
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
                    side_effect=[
                        {"response": original_plan},
                        {"response": still_invalid},
                        {"response": still_invalid},
                    ],
                ) as mock_ai:
                    with self.assertRaisesRegex(
                        pipeline.PipelineError,
                        "No filler or unsupported facts were inserted",
                    ):
                        pipeline.make_plan([item], recent=[])
                self.assertEqual(mock_ai.call_count, 3)
            finally:
                pipeline.WORK = original_work


if __name__ == "__main__":
    unittest.main()
