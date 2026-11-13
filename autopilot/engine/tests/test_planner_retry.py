"""Offline tests for sentence-level planner narration correction."""
import json
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


def sentence_result(sentence):
    return {"response": {"sentence": sentence}}


class PlannerNarrationRetryTests(unittest.TestCase):
    def setUp(self):
        self.item = {
            "title": "A violin component travelled to orbit",
            "summary": "A publisher reports an instrument component travelled to orbit.",
            "evidence_text": "A publisher's article reports this instrument component travelled to orbit.",
            "publisher_domain": "publisher.example",
            "url": "https://publisher.example/story-about-a-violin",
            "source": "Test Publisher",
        }

    def test_narration_validator_accepts_exact_four_sentence_budget(self):
        self.assertEqual(pipeline.narration_validation_error(VALID_SCRIPT), "")
        self.assertEqual(pipeline.narration_sentence_budget_error(VALID_SCRIPT), "")
        self.assertEqual(pipeline.narration_word_count(VALID_SCRIPT), 41)
        self.assertEqual(
            [pipeline.narration_word_count(s) for s in pipeline.narration_sentences(VALID_SCRIPT)],
            [8, 9, 12, 12],
        )

    def test_narration_validator_reports_actual_short_word_count(self):
        issue = pipeline.narration_validation_error(SHORT_SCRIPT)
        self.assertIn("24 spoken words", issue)
        self.assertIn("40–44", issue)

    def test_make_plan_repairs_each_sentence_independently_without_research_repeat(self):
        original_plan = make_test_plan(SCRIPT_33_WORDS)
        valid_sentences = pipeline.narration_sentences(VALID_SCRIPT)
        ai_results = [{"response": original_plan}] + [sentence_result(sentence) for sentence in valid_sentences]
        original_scenes = original_plan["scenes"]

        with tempfile.TemporaryDirectory() as folder:
            original_work = pipeline.WORK
            try:
                pipeline.WORK = Path(folder)
                with patch.object(pipeline, "ai", side_effect=ai_results) as mock_ai:
                    result = pipeline.make_plan([self.item], recent=[])

                self.assertEqual(mock_ai.call_count, 5)
                self.assertEqual(result["narration_script"], VALID_SCRIPT)
                self.assertEqual(pipeline.narration_sentence_budget_error(result["narration_script"]), "")
                self.assertEqual(result["sources"], [self.item["url"]])
                self.assertEqual(result["scenes"], original_scenes)

                for index, call in enumerate(mock_ai.call_args_list[1:]):
                    payload = call.args[1]
                    system_message = payload["messages"][0]["content"]
                    user_message = payload["messages"][1]["content"]
                    self.assertIn(f"exactly {8 if index == 0 else 9 if index == 1 else 12} spoken words", system_message)
                    self.assertIn(f"sentence {index + 1} of 4", user_message)
                    self.assertIn("Verified research evidence", user_message)

                debug = json.loads((Path(folder) / "creative_plan_debug.json").read_text(encoding="utf-8"))
                self.assertEqual(debug["status"], "repaired")
                self.assertEqual(debug["current_script"], VALID_SCRIPT)
                self.assertEqual(len(debug["repair_attempts"]), 4)
            finally:
                pipeline.WORK = original_work

    def test_make_plan_retries_only_the_sentence_that_misses_its_target(self):
        valid_sentences = pipeline.narration_sentences(VALID_SCRIPT)
        seven_word_hook = "Can music move across the universe today?"
        ai_results = [
            {"response": make_test_plan(SCRIPT_33_WORDS)},
            sentence_result(seven_word_hook),
            sentence_result(valid_sentences[0]),
            *[sentence_result(sentence) for sentence in valid_sentences[1:]],
        ]

        with tempfile.TemporaryDirectory() as folder:
            original_work = pipeline.WORK
            try:
                pipeline.WORK = Path(folder)
                with patch.object(pipeline, "ai", side_effect=ai_results) as mock_ai:
                    result = pipeline.make_plan([self.item], recent=[])

                self.assertEqual(mock_ai.call_count, 6)
                self.assertEqual(result["narration_script"], VALID_SCRIPT)
                retry_payload = mock_ai.call_args_list[2].args[1]
                self.assertIn("add exactly ONE useful", retry_payload["messages"][1]["content"])
                self.assertIn("7 words", retry_payload["messages"][1]["content"])
            finally:
                pipeline.WORK = original_work

    def test_make_plan_preserves_failure_diagnostics_after_bounded_sentence_retries(self):
        original_plan = make_test_plan(SCRIPT_33_WORDS)
        invalid_hook = "Can music move across the universe today?"

        with tempfile.TemporaryDirectory() as folder:
            original_work = pipeline.WORK
            try:
                pipeline.WORK = Path(folder)
                with patch.object(
                    pipeline,
                    "ai",
                    side_effect=[
                        {"response": make_test_plan(SCRIPT_33_WORDS)},
                        sentence_result(invalid_hook),
                        sentence_result(invalid_hook),
                    ],
                ) as mock_ai:
                    with self.assertRaisesRegex(
                        pipeline.PipelineError,
                        "Narration sentence 1 could not be repaired",
                    ):
                        pipeline.make_plan([self.item], recent=[])

                self.assertEqual(mock_ai.call_count, 3)
                debug_path = Path(folder) / "creative_plan_debug.json"
                self.assertTrue(debug_path.is_file())
                debug = json.loads(debug_path.read_text(encoding="utf-8"))
                self.assertEqual(debug["status"], "failed")
                self.assertEqual(len(debug["repair_attempts"]), 2)
                self.assertEqual(debug["initial_script"], SCRIPT_33_WORDS)
                self.assertEqual(debug["initial_plan"]["scenes"], original_plan["scenes"])
            finally:
                pipeline.WORK = original_work

    def test_missing_terminal_punctuation_is_normalized_without_an_extra_ai_call(self):
        initial_script = (
            "Can a violinist master the most difficult pieces? "
            "Hiu Sing Fan recently tackled the intense Paganiniana. "
            "This work demands incredible speed and flawless technical precision. "
            "Such mastery brings the legendary spirit of Paganini alive."
        )
        repaired_sentences = [
            "Hiu Sing Fan plays the difficult Milstein Paganiniana piece",
            "The work demands incredible speed, control, and flawless technical precision from violinists.",
            "Its demanding passages bring the legendary spirit of Paganini alive for audiences.",
        ]
        original_plan = make_test_plan(initial_script)
        responses = [
            {"response": original_plan},
            sentence_result(repaired_sentences[0]),  # Correct 9 words; model omitted final punctuation.
            sentence_result(repaired_sentences[1]),
            sentence_result(repaired_sentences[2]),
        ]

        with tempfile.TemporaryDirectory() as folder:
            original_work = pipeline.WORK
            try:
                pipeline.WORK = Path(folder)
                with patch.object(pipeline, "ai", side_effect=responses) as mock_ai:
                    result = pipeline.make_plan([self.item], recent=[])

                self.assertEqual(mock_ai.call_count, 4)
                final_sentences = pipeline.narration_sentences(result["narration_script"])
                self.assertEqual(final_sentences[1], repaired_sentences[0] + ".")
                self.assertEqual(pipeline.narration_word_count(result["narration_script"]), 41)
                debug = json.loads((Path(folder) / "creative_plan_debug.json").read_text(encoding="utf-8"))
                self.assertTrue(debug["repair_attempts"][0]["punctuation_added"])
                self.assertEqual(debug["repair_attempts"][0]["attempt"], 1)
            finally:
                pipeline.WORK = original_work

    def test_one_word_short_retry_uses_add_one_word_instruction(self):
        production_script = (
            "Can a single violinist master such complexity? "
            "Hiu Sing Fan performs Milstein's Paganiniana with incredible skill. "
            "This demanding piece requires immense technical precision and passion. "
            "Watch as the music transforms into a breathtaking display."
        )
        completed = pipeline.narration_sentences(VALID_SCRIPT)
        expected_script = " ".join([
            completed[0],
            pipeline.narration_sentences(production_script)[1],
            "This difficult piece requires great technical precision and much deep artistic passion.",
            completed[3],
        ])
        responses = [
            {"response": make_test_plan(production_script)},
            sentence_result(completed[0]),
            sentence_result("This difficult piece requires great technical precision and much deep passion."),
            sentence_result("This difficult piece requires great technical precision and much deep artistic passion."),
            sentence_result(completed[3]),
        ]

        with tempfile.TemporaryDirectory() as folder:
            original_work = pipeline.WORK
            try:
                pipeline.WORK = Path(folder)
                with patch.object(pipeline, "ai", side_effect=responses) as mock_ai:
                    result = pipeline.make_plan([self.item], recent=[])

                self.assertEqual(result["narration_script"], expected_script)
                self.assertEqual(pipeline.narration_sentence_budget_error(result["narration_script"]), "")
                self.assertEqual(mock_ai.call_count, 5)
                retry_prompt = mock_ai.call_args_list[3].args[1]["messages"][1]["content"]
                self.assertIn("add exactly ONE useful", retry_prompt)
                self.assertIn("11 words", retry_prompt)
            finally:
                pipeline.WORK = original_work

    def test_valid_initial_script_does_not_trigger_sentence_repair_calls(self):
        with tempfile.TemporaryDirectory() as folder:
            original_work = pipeline.WORK
            try:
                pipeline.WORK = Path(folder)
                with patch.object(
                    pipeline, "ai", return_value={"response": make_test_plan(VALID_SCRIPT)}
                ) as mock_ai:
                    result = pipeline.make_plan([self.item], recent=[])
                self.assertEqual(mock_ai.call_count, 1)
                self.assertEqual(result["narration_script"], VALID_SCRIPT)
            finally:
                pipeline.WORK = original_work


if __name__ == "__main__":
    unittest.main()
