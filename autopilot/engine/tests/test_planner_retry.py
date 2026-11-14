"""Regression tests for sentence-by-sentence narration composition and repair."""
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


ORCHESTRA_SENTENCES = [
    "Can an orchestra define a region's musical identity?",
    "The Orchestre National de Metz Grand Est celebrates fifty years.",
    "International violinist Alena Baeva will perform Mozart's brilliant fifth concerto in Metz.",
    "Ravel's music also honours the orchestra's long, remarkable regional heritage and identity.",
]
ORCHESTRA_SCRIPT = " ".join(ORCHESTRA_SENTENCES)

RUN22_INITIAL_SENTENCES = [
    "Can a computer mimic a soul?",
    "MIT engineers have achieved something remarkable.",
    "Their virtual violin produces incredibly realistic sounds.",
    "This digital breakthrough changes how we experience music forever.",
]
RUN22_INITIAL_SCRIPT = " ".join(RUN22_INITIAL_SENTENCES)

RUN22_ATTEMPT_1 = (
    "Can a computer mimic a soul? MIT engineers created a virtual violin. "
    "This digital instrument produces incredibly realistic sounds. "
    "Such a breakthrough changes how we experience music forever."
)
RUN22_ATTEMPT_2 = (
    "Can a computer mimic a soul? MIT engineers built a virtual violin. "
    "This digital instrument produces incredibly realistic acoustic sounds. "
    "Such a breakthrough changes how we experience music forever."
)
RUN22_ATTEMPT_3 = (
    "Can a computer mimic a soul? MIT engineers built a virtual violin. "
    "This digital instrument produces incredibly realistic acoustic sounds. "
    "Such a breakthrough changes how we experience music forever and transforms our digital world."
)

RUN22_CORRECTED_FIELDS = {
    "sentence_2": "MIT engineers built a virtual violin through detailed computer-based sound modelling research.",
    "sentence_3": "Digital modelling reproduces realistic violin resonance, timbre, and subtle expressive details faithfully.",
    "sentence_4": "This achievement connects traditional violin artistry with new possibilities for musical creativity.",
}


def make_test_plan(sentences):
    url = "https://publisher.example/story-about-a-violin"
    return {
        "topic": "Virtual violin technology and musical expression",
        "title": "The Future of the Violin",
        "hook": "Can a computer mimic a soul?",
        "description": "A sourced story about a virtual violin.",
        "hashtags": ["#Violin", "#MusicTechnology"],
        "narration_sentences": list(sentences),
        "narrative_style": "cinematic_story",
        "scenes": [
            {"caption": "A virtual violin takes shape", "image_prompt": "A virtual violin interface"},
            {"caption": "Digital sound modelling", "image_prompt": "A clear sound-wave visualization"},
            {"caption": "Tradition meets digital creativity", "image_prompt": "A violin beside digital strings"},
        ],
        "sources": [{"source_id": "S0001"}],
        "timeline": [],
    }


class PlannerNarrationValidationTests(unittest.TestCase):
    def setUp(self):
        self.item = {
            "title": "MIT engineers develop a virtual violin",
            "summary": "The virtual violin produces realistic sounds.",
            "evidence_text": (
                "The publisher reports that MIT engineers developed a virtual violin "
                "and describes its realistic sound production."
            ),
            "publisher_domain": "publisher.example",
            "url": "https://publisher.example/story-about-a-violin",
            "source": "Test Publisher",
        }

    def test_variable_sentence_lengths_pass_without_fixed_quotas(self):
        self.assertEqual(pipeline.narration_validation_error(ORCHESTRA_SCRIPT), "")
        self.assertEqual(pipeline.narration_word_count(ORCHESTRA_SCRIPT), 42)
        self.assertEqual(
            [pipeline.narration_word_count(value) for value in ORCHESTRA_SENTENCES],
            [8, 10, 12, 12],
        )

    def test_validator_rejects_sentence_above_twelve_words(self):
        sentences = [
            "Can one orchestra shape regional musical identity?",
            "The Orchestre National de Metz Grand Est celebrates its fiftieth anniversary this November.",
            "International violinist Alena Baeva performs Mozart's fifth concerto in Metz this season.",
            "Ravel's music honours the orchestra's remarkable regional heritage and identity today.",
        ]
        issue = pipeline.narration_validation_error(" ".join(sentences))
        self.assertIn("sentence 2 has 13 words", issue)

    def test_validator_rejects_hook_outside_five_to_eight_words(self):
        sentences = [
            "Can music travel farther?",
            "The Orchestre National de Metz Grand Est marks fifty years this November.",
            "International violinist Alena Baeva performs Mozart's fifth concerto in Metz this season.",
            "Ravel's music honours the orchestra's remarkable regional heritage and identity across generations.",
        ]
        issue = pipeline.narration_validation_error(" ".join(sentences))
        self.assertIn("opening hook has 4 words", issue)

    def test_run22_exact_failed_outputs_are_detected(self):
        cases = (
            (RUN22_INITIAL_SCRIPT, 28, [6, 6, 7, 9]),
            (RUN22_ATTEMPT_1, 28, [6, 6, 7, 9]),
            (RUN22_ATTEMPT_2, 29, [6, 6, 8, 9]),
            (RUN22_ATTEMPT_3, 34, [6, 6, 8, 14]),
        )
        for script, total, sentence_counts in cases:
            with self.subTest(total=total, sentence_counts=sentence_counts):
                self.assertEqual(pipeline.narration_word_count(script), total)
                self.assertEqual(
                    [pipeline.narration_word_count(value) for value in pipeline.narration_sentences(script)],
                    sentence_counts,
                )
                self.assertTrue(pipeline.narration_validation_error(script))

    def test_run22_dynamic_budget_repairs_underlength_and_overlong_sentence(self):
        budgets = pipeline.narration_sentence_budget(pipeline.narration_sentences(RUN22_ATTEMPT_3))
        self.assertEqual(budgets[0], {"min_words": 6, "max_words": 8})
        self.assertEqual(budgets[1], {"min_words": 12, "max_words": 12})
        self.assertEqual(budgets[2], {"min_words": 12, "max_words": 12})
        self.assertEqual(budgets[3], {"min_words": 12, "max_words": 12})
        self.assertEqual(sum(value["min_words"] for value in budgets), 42)
        self.assertLessEqual(sum(value["max_words"] for value in budgets), 44)

    def test_run22_composer_repairs_only_sentences_two_to_four(self):
        plan = make_test_plan(RUN22_INITIAL_SENTENCES)
        scenes_before = json.loads(json.dumps(plan["scenes"]))
        tool_response = {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "type": "function",
                        "function": {
                            "name": "submit_narration_sentence_corrections",
                            "arguments": json.dumps(RUN22_CORRECTED_FIELDS),
                        },
                    }],
                },
            }],
        }

        with tempfile.TemporaryDirectory() as folder:
            original_work = pipeline.WORK
            try:
                pipeline.WORK = Path(folder)
                with patch.object(
                    pipeline,
                    "ai",
                    side_effect=[
                        {"response": plan},
                        tool_response,
                    ],
                ) as mock_ai:
                    result = pipeline.make_plan([self.item], recent=[])

                self.assertEqual(mock_ai.call_count, 2)
                self.assertEqual(result["narration_script"].split(". ")[0] + ".", RUN22_INITIAL_SENTENCES[0])
                self.assertEqual(result["narration_sentences"][0], RUN22_INITIAL_SENTENCES[0])
                self.assertEqual(result["narration_sentences"][1:], list(RUN22_CORRECTED_FIELDS.values()))
                self.assertEqual(pipeline.narration_word_count(result["narration_script"]), 42)
                self.assertEqual(pipeline.narration_validation_error(result["narration_script"]), "")
                correction_payload = mock_ai.call_args_list[1].args[1]
                self.assertEqual(correction_payload["tool_choice"]["function"]["name"],
                                 "submit_narration_sentence_corrections")
                self.assertEqual(
                    correction_payload["tools"][0]["function"]["parameters"]["required"],
                    ["sentence_2", "sentence_3", "sentence_4"],
                )
                locked = json.loads(correction_payload["messages"][1]["content"].split(
                    "Locked sentence fields (must remain unchanged): ", 1
                )[1].split("\nDynamic word budgets", 1)[0])
                self.assertEqual(locked, {"sentence_1": RUN22_INITIAL_SENTENCES[0]})
                self.assertEqual(
                    [(scene["caption"], scene["image_prompt"]) for scene in result["scenes"]],
                    [(scene["caption"], scene["image_prompt"]) for scene in scenes_before],
                )

                debug = json.loads((Path(folder) / "creative_plan_debug.json").read_text(encoding="utf-8"))
                self.assertEqual(debug["stage"], "narration_composer")
                self.assertEqual(debug["status"], "repaired")
                self.assertEqual(len(debug["correction_attempts"]), 1)
                self.assertEqual(debug["correction_attempts"][0]["corrected_sentence_numbers"], [2, 3, 4])
            finally:
                pipeline.WORK = original_work

    def test_valid_initial_narration_skips_correction_call(self):
        plan = make_test_plan(ORCHESTRA_SENTENCES)
        with patch.object(pipeline, "ai", return_value={"response": plan}) as mock_ai:
            result = pipeline.make_plan([self.item], recent=[])
        self.assertEqual(mock_ai.call_count, 1)
        self.assertEqual(result["narration_script"], ORCHESTRA_SCRIPT)
        self.assertEqual(result["narration_sentences"], ORCHESTRA_SENTENCES)

    def test_composer_allows_one_targeted_followup_then_fails_safely(self):
        plan = make_test_plan(RUN22_INITIAL_SENTENCES)
        invalid_fields = {
            "sentence_2": "MIT engineers created a virtual violin.",
            "sentence_3": "The virtual violin produces incredibly realistic sounds.",
            "sentence_4": "This digital breakthrough changes how people experience music.",
        }
        response = {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "type": "function",
                        "function": {
                            "name": "submit_narration_sentence_corrections",
                            "arguments": json.dumps(invalid_fields),
                        },
                    }],
                },
            }],
        }
        with tempfile.TemporaryDirectory() as folder:
            original_work = pipeline.WORK
            try:
                pipeline.WORK = Path(folder)
                with patch.object(
                    pipeline,
                    "ai",
                    side_effect=[
                        {"response": plan},
                        response,
                        response,
                    ],
                ) as mock_ai:
                    with self.assertRaisesRegex(
                        pipeline.PipelineError,
                        "stopped safely after two targeted correction cycles",
                    ):
                        pipeline.make_plan([self.item], recent=[])
                self.assertEqual(mock_ai.call_count, 3)
                debug = json.loads((Path(folder) / "creative_plan_debug.json").read_text(encoding="utf-8"))
                self.assertEqual(debug["status"], "failed")
                self.assertEqual(len(debug["correction_attempts"]), 2)
                self.assertTrue(all(
                    attempt["corrected_sentence_numbers"] == [2, 3, 4]
                    for attempt in debug["correction_attempts"]
                ))
            finally:
                pipeline.WORK = original_work


if __name__ == "__main__":
    unittest.main()
