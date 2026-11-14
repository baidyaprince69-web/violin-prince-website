"""Regression tests for flexible whole-script narration validation and repair."""
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


# The orchestra's multi-part name creates a 10-word sentence. The complete
# narration is valid, even though it does not follow the former 8/9/12/12 split.
ORCHESTRA_SCRIPT = (
    "Can an orchestra define a region's musical identity? "
    "The Orchestre National de Metz Grand Est celebrates fifty years. "
    "International violinist Alena Baeva will perform Mozart's brilliant fifth concerto in Metz. "
    "Ravel's music also honours the orchestra's long, remarkable regional heritage and identity."
)

ORIGINAL_FAILED_SCRIPT = (
    "Can a single orchestra define a region's soul? "
    "The Orchestre National de Metz Grand Est celebrates fifty years. "
    "International violinist Alena Baeva will perform Mozart's brilliant fifth concerto. "
    "This historic anniversary event honors decades of incredible symphonic mastery."
)

SHORT_SCRIPT = (
    "Can this music travel through space? "
    "A violin part travelled into orbit. "
    "It returned with a remarkable story. "
    "Now that journey connects distant listeners."
)


def make_test_plan(script):
    url = "https://publisher.example/story-about-a-violin"
    return {
        "topic": "Orchestral anniversary and violin virtuosity",
        "title": "A Golden Anniversary of Symphonic Sound",
        "hook": "Can an orchestra define a region's musical identity?",
        "description": "A sourced human-interest story.",
        "hashtags": ["#Music", "#Violin"],
        "narration_script": script,
        "narrative_style": "documentary",
        "scenes": [
            {"caption": "A grand concert hall", "image_prompt": "A concert hall in golden light"},
            {"caption": "A virtuoso violinist", "image_prompt": "A violinist performing on stage"},
            {"caption": "A symphonic celebration", "image_prompt": "An orchestra performing together"},
        ],
        "sources": [url],
    }


class PlannerNarrationValidationTests(unittest.TestCase):
    def setUp(self):
        self.item = {
            "title": "Orchestre National de Metz celebrates fifty years",
            "summary": "The orchestra marks its fiftieth anniversary and presents Mozart and Ravel.",
            "evidence_text": "The publisher reports the anniversary concerts and the programme featuring Mozart and Ravel.",
            "publisher_domain": "publisher.example",
            "url": "https://publisher.example/story-about-a-violin",
            "source": "Test Publisher",
        }

    def test_variable_sentence_lengths_pass_without_a_fixed_word_budget(self):
        self.assertEqual(pipeline.narration_validation_error(ORCHESTRA_SCRIPT), "")
        sentences = pipeline.narration_sentences(ORCHESTRA_SCRIPT)
        counts = [pipeline.narration_word_count(sentence) for sentence in sentences]
        self.assertEqual(pipeline.narration_word_count(ORCHESTRA_SCRIPT), 42)
        self.assertEqual(counts, [8, 10, 12, 12])
        self.assertNotEqual(counts, [8, 9, 12, 12])
        self.assertTrue(all(count <= 12 for count in counts))

    def test_original_failed_script_only_fails_total_word_range(self):
        issue = pipeline.narration_validation_error(ORIGINAL_FAILED_SCRIPT)
        self.assertIn("38 spoken words", issue)
        sentence_two = pipeline.narration_sentences(ORIGINAL_FAILED_SCRIPT)[1]
        self.assertEqual(pipeline.narration_word_count(sentence_two), 10)
        self.assertLessEqual(pipeline.narration_word_count(sentence_two), 12)

    def test_validator_rejects_a_sentence_over_twelve_words(self):
        script = (
            "Can one orchestra shape regional musical identity? "
            "The Orchestre National de Metz Grand Est celebrates its fiftieth anniversary this November. "
            "International violinist Alena Baeva will perform Mozart's concerto in Metz this November. "
            "Ravel's music also honours the orchestra's remarkable fifty-year regional heritage and identity."
        )
        self.assertEqual(pipeline.narration_word_count(script), 44)
        issue = pipeline.narration_validation_error(script)
        self.assertIn("sentence 2 has 13 words", issue)

    def test_validator_rejects_a_hook_that_is_too_short(self):
        script = (
            "Can music travel farther? "
            "The Orchestre National de Metz Grand Est celebrates fifty years with a major concert. "
            "International violinist Alena Baeva will perform Mozart's brilliant fifth concerto in Metz. "
            "Ravel's music also honours the orchestra's long, remarkable regional heritage and identity."
        )
        issue = pipeline.narration_validation_error(script)
        self.assertIn("opening hook has 4 words", issue)

    def test_make_plan_repairs_full_narration_and_preserves_story_and_scenes(self):
        original_plan = make_test_plan(ORIGINAL_FAILED_SCRIPT)
        original_scenes = original_plan["scenes"]

        with tempfile.TemporaryDirectory() as folder:
            original_work = pipeline.WORK
            try:
                pipeline.WORK = Path(folder)
                with patch.object(
                    pipeline,
                    "ai",
                    side_effect=[
                        {"response": original_plan},
                        {"response": {"narration_script": ORCHESTRA_SCRIPT}},
                    ],
                ) as mock_ai:
                    result = pipeline.make_plan([self.item], recent=[])

                self.assertEqual(mock_ai.call_count, 2)
                self.assertEqual(result["narration_script"], ORCHESTRA_SCRIPT)
                self.assertEqual(result["scenes"], original_scenes)
                self.assertEqual(pipeline.narration_validation_error(result["narration_script"]), "")
                repair_payload = mock_ai.call_args_list[1].args[1]
                system_message = repair_payload["messages"][0]["content"]
                user_message = repair_payload["messages"][1]["content"]
                self.assertIn("no fixed word count for any individual sentence", system_message)
                self.assertIn("Twelve is a maximum, not a target", system_message)
                self.assertIn("Verified research evidence", user_message)

                debug = json.loads(
                    (Path(folder) / "creative_plan_debug.json").read_text(encoding="utf-8")
                )
                self.assertEqual(debug["status"], "repaired")
                self.assertEqual(debug["current_script"], ORCHESTRA_SCRIPT)
                self.assertEqual(len(debug["repair_attempts"]), 1)
                self.assertEqual(debug["repair_attempts"][0]["sentence_word_counts"], [8, 10, 12, 12])
            finally:
                pipeline.WORK = original_work

    def test_make_plan_stops_after_three_invalid_full_script_revisions(self):
        original_plan = make_test_plan(SHORT_SCRIPT)

        with tempfile.TemporaryDirectory() as folder:
            original_work = pipeline.WORK
            try:
                pipeline.WORK = Path(folder)
                with patch.object(
                    pipeline,
                    "ai",
                    side_effect=[
                        {"response": original_plan},
                        {"response": {"narration_script": SHORT_SCRIPT}},
                        {"response": {"narration_script": SHORT_SCRIPT}},
                        {"response": {"narration_script": SHORT_SCRIPT}},
                    ],
                ) as mock_ai:
                    with self.assertRaisesRegex(
                        pipeline.PipelineError,
                        "Narration could not be corrected.*three full-script attempts",
                    ):
                        pipeline.make_plan([self.item], recent=[])

                self.assertEqual(mock_ai.call_count, 4)
                debug = json.loads(
                    (Path(folder) / "creative_plan_debug.json").read_text(encoding="utf-8")
                )
                self.assertEqual(debug["status"], "failed")
                self.assertEqual(len(debug["repair_attempts"]), 3)
                self.assertEqual(debug["initial_script"], SHORT_SCRIPT)
            finally:
                pipeline.WORK = original_work

    def test_valid_initial_script_does_not_trigger_a_repair_call(self):
        with tempfile.TemporaryDirectory() as folder:
            original_work = pipeline.WORK
            try:
                pipeline.WORK = Path(folder)
                with patch.object(
                    pipeline, "ai", return_value={"response": make_test_plan(ORCHESTRA_SCRIPT)}
                ) as mock_ai:
                    result = pipeline.make_plan([self.item], recent=[])
                self.assertEqual(mock_ai.call_count, 1)
                self.assertEqual(result["narration_script"], ORCHESTRA_SCRIPT)
            finally:
                pipeline.WORK = original_work


if __name__ == "__main__":
    unittest.main()
