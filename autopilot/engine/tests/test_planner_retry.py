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
    "sentence_3": "Digital modelling reproduces realistic violin resonance, timbre, and expressive details faithfully.",
    "sentence_4": "This achievement connects traditional violin artistry with possibilities for musical creativity.",
}

RUN23_INITIAL_SENTENCES = [
    "Can a computer mimic a violin?",
    "MIT engineers developed new technology to simulate the sound of violins.",
    "This virtual instrument produces realistic tones through advanced digital modeling techniques.",
    "These digital strings now sing with a very authentic musical soul.",
]
RUN23_CORRECTED_SENTENCE = (
    "MIT engineers developed technology to simulate violin sounds with remarkable acoustic realism."
)


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
        corrected_word_arrays = {
            field + "_words": sentence.split()
            for field, sentence in RUN22_CORRECTED_FIELDS.items()
        }
        tool_response = {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "type": "function",
                        "function": {
                            "name": "submit_narration_sentence_corrections",
                            "arguments": json.dumps(corrected_word_arrays),
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
                self.assertEqual(result["narration_sentences"][0], RUN22_INITIAL_SENTENCES[0])
                self.assertEqual(result["narration_sentences"][1:], list(RUN22_CORRECTED_FIELDS.values()))
                self.assertEqual(pipeline.narration_word_count(result["narration_script"]), 40)
                self.assertEqual(pipeline.narration_validation_error(result["narration_script"]), "")
                correction_payload = mock_ai.call_args_list[1].args[1]
                self.assertEqual(correction_payload["tool_choice"]["function"]["name"],
                                 "submit_narration_sentence_corrections")
                self.assertEqual(
                    correction_payload["tools"][0]["function"]["parameters"]["required"],
                    ["sentence_2_words", "sentence_3_words", "sentence_4_words"],
                )
                array_properties = correction_payload["tools"][0]["function"]["parameters"]["properties"]
                self.assertEqual(
                    [array_properties[field]["minItems"] for field in (
                        "sentence_2_words", "sentence_3_words", "sentence_4_words"
                    )],
                    [12, 11, 11],
                )
                self.assertEqual(
                    [array_properties[field]["maxItems"] for field in (
                        "sentence_2_words", "sentence_3_words", "sentence_4_words"
                    )],
                    [12, 11, 11],
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


    def test_word_array_splits_multiword_item_when_spoken_count_is_within_budget(self):
        words = [
            "Digital", "music", "has", "truly", "never", "sounded",
            "quite", "this", "vivid", "or", "so real."
        ]
        sentence, issue = pipeline._assemble_narration_sentence_words(
            words,
            expected_count=11,
            field="sentence_4_words",
            max_count=12,
        )
        self.assertEqual(issue, "")
        self.assertEqual(
            sentence,
            "Digital music has truly never sounded quite this vivid or so real.",
        )
        self.assertEqual(pipeline.narration_word_count(sentence), 12)
        self.assertEqual(len(pipeline.narration_sentences(sentence)), 1)

    def test_word_array_still_rejects_spoken_count_above_sentence_maximum(self):
        words = [
            "Digital", "music", "has", "truly", "never", "sounded",
            "quite", "this", "vivid", "or", "so very real."
        ]
        sentence, issue = pipeline._assemble_narration_sentence_words(
            words,
            expected_count=11,
            field="sentence_4_words",
            max_count=12,
        )
        self.assertEqual(sentence, "")
        self.assertIn("normalizes to 13 spoken words", issue)
        self.assertIn("allowed range is 11–12", issue)

    def test_run23_exact_39_word_failure_repairs_only_one_word(self):
        plan = make_test_plan(RUN23_INITIAL_SENTENCES)
        initial_script = " ".join(RUN23_INITIAL_SENTENCES)
        self.assertEqual(pipeline.narration_word_count(initial_script), 39)
        self.assertIn(
            "it has 39 spoken words; the required range is 40–44",
            pipeline.narration_validation_error(initial_script),
        )
        self.assertEqual(
            [pipeline.narration_word_count(value) for value in RUN23_INITIAL_SENTENCES],
            [6, 11, 11, 11],
        )

        tool_response = {
            "choices": [{
                "message": {
                    "tool_calls": [{
                        "type": "function",
                        "function": {
                            "name": "submit_narration_sentence_corrections",
                            "arguments": json.dumps({
                                "sentence_2_words": RUN23_CORRECTED_SENTENCE.split()
                            }),
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
                self.assertEqual(pipeline.narration_word_count(result["narration_script"]), 40)
                self.assertEqual(pipeline.narration_validation_error(result["narration_script"]), "")
                self.assertEqual(result["narration_sentences"][0], RUN23_INITIAL_SENTENCES[0])
                self.assertEqual(result["narration_sentences"][1], RUN23_CORRECTED_SENTENCE)
                self.assertEqual(result["narration_sentences"][2:], RUN23_INITIAL_SENTENCES[2:])

                correction_payload = mock_ai.call_args_list[1].args[1]
                parameters = correction_payload["tools"][0]["function"]["parameters"]
                self.assertEqual(parameters["required"], ["sentence_2_words"])
                self.assertEqual(parameters["properties"]["sentence_2_words"]["minItems"], 12)
                self.assertEqual(parameters["properties"]["sentence_2_words"]["maxItems"], 12)
                locked = json.loads(correction_payload["messages"][1]["content"].split(
                    "Locked sentence fields (must remain unchanged): ", 1
                )[1].split("\nDynamic word budgets", 1)[0])
                self.assertEqual(
                    locked,
                    {
                        "sentence_1": RUN23_INITIAL_SENTENCES[0],
                        "sentence_3": RUN23_INITIAL_SENTENCES[2],
                        "sentence_4": RUN23_INITIAL_SENTENCES[3],
                    },
                )

                debug = json.loads((Path(folder) / "creative_plan_debug.json").read_text(encoding="utf-8"))
                self.assertEqual(debug["status"], "repaired")
                self.assertEqual(debug["final_diagnostics"]["word_count"], 40)
                self.assertEqual(debug["correction_attempts"][0]["corrected_sentence_numbers"], [2])
                self.assertEqual(
                    debug["correction_attempts"][0]["required_word_counts"],
                    {"sentence_2_words": 12},
                )
            finally:
                pipeline.WORK = original_work


    def test_source_ids_remain_stable_when_research_results_are_reordered(self):
        items = [
            {
                "title": "MIT engineers develop a virtual violin",
                "url": "https://news.mit.edu/2026/virtual-violin",
                "publisher_domain": "news.mit.edu",
                "publisher_name": "MIT News",
                "evidence_text": "A" * 100,
            },
            {
                "title": "A separate report about violin design",
                "url": "https://example.org/science/violin-design",
                "publisher_domain": "example.org",
                "publisher_name": "Example Science",
                "evidence_text": "B" * 100,
            },
        ]
        first = {item["url"]: item["source_id"] for item in pipeline.planner_research_items(items)}
        second = {item["url"]: item["source_id"] for item in pipeline.planner_research_items(list(reversed(items)))}
        self.assertEqual(first, second)

    def test_source_resolver_uses_publisher_domain_hint_for_subdomain(self):
        item = {
            "title": "MIT engineers virtual violin research",
            "url": "https://news.mit.edu/2026/virtual-violin",
            "publisher_domain": "news.mit.edu",
            "publisher_name": "MIT News",
            "evidence_text": "MIT engineers developed a computational violin model. " * 4,
        }
        compact = pipeline.planner_research_items([item])
        resolved = pipeline.resolve_plan_sources(
            {"topic": "MIT virtual violin", "title": "Virtual Violin", "sources": [
                {"source_id": "S0060", "publisher_domain": "mit.edu"}
            ]},
            compact,
        )
        self.assertEqual(len(resolved), 1)
        self.assertEqual(resolved[0]["url"], item["url"])

    def test_run24_discovery_only_reference_defers_to_targeted_source_research(self):
        discovery_item = {
            "title": "MIT engineers’ virtual violin produces realistic sounds",
            "url": "https://news.google.com/rss/articles/discovery-only",
            "publisher_name": "MIT News",
            "publisher_domain": "news.mit.edu",
            "summary": "A discovery headline only.",
        }
        plan = make_test_plan(ORCHESTRA_SENTENCES)
        plan["topic"] = "MIT Virtual Violin Technology"
        plan["title"] = "The Digital Soul of the Violin"
        plan["narrative_style"] = "documentary"
        planner_reference = {"source_id": "S0060", "publisher_domain": "mit.edu"}
        plan["sources"] = [planner_reference]

        with tempfile.TemporaryDirectory() as folder:
            original_work = pipeline.WORK
            try:
                pipeline.WORK = Path(folder)
                with patch.object(pipeline, "ai", return_value={"response": plan}):
                    result = pipeline.make_plan([discovery_item], recent=[])

                self.assertEqual(result["sources"], [])
                self.assertEqual(result["source_resolution"]["status"], "pending_targeted_verification")
                self.assertEqual(result["source_reference_hints"], [planner_reference])
                self.assertEqual(result["narrative_style"], "documentary")
            finally:
                pipeline.WORK = original_work

    def test_story_source_recovery_tries_one_alternative_candidate(self):
        first_plan = make_test_plan(ORCHESTRA_SENTENCES)
        first_plan["topic"] = "Unverifiable first story"
        second_plan = make_test_plan(ORCHESTRA_SENTENCES)
        second_plan["topic"] = "Second story with publisher coverage"
        second_plan["narration_script"] = ORCHESTRA_SCRIPT
        verified = [
            {
                "source_id": "SRC_ORCHESTRA",
                "publisher_domain": "a.example",
                "publisher_name": "Orchestra Journal",
                "title": "Orchestre National de Metz Grand Est celebrates fifty years",
                "url": "https://a.example/orchestre-fifty-years",
                "evidence_text": (
                    "The Orchestre National de Metz Grand Est celebrates fifty years. "
                    "The orchestra honours regional heritage and identity through its programme."
                ),
            },
            {
                "source_id": "SRC_BAEVA",
                "publisher_domain": "b.example",
                "publisher_name": "Classical Review",
                "title": "International violinist Alena Baeva performs Mozart's fifth concerto in Metz",
                "url": "https://b.example/baeva-mozart-metz",
                "evidence_text": (
                    "International violinist Alena Baeva will perform Mozart's brilliant fifth concerto "
                    "in Metz. Ravel's music also honours the orchestra's long, remarkable regional "
                    "heritage and identity."
                ),
            },
        ]

        with (
            patch.object(pipeline, "make_plan", side_effect=[first_plan, second_plan]) as planner,
            patch.object(pipeline, "research_story_sources", side_effect=[[], ["source-a", "source-b"]]) as researcher,
            patch.object(
                pipeline,
                "select_verified_story_sources",
                side_effect=[
                    pipeline.PipelineError("Story quality gate blocked: only 0 relevant direct publisher sources."),
                    verified,
                ],
            ) as verifier,
        ):
            result_plan, story_items, result_sources = pipeline.prepare_story_with_source_recovery(
                [{"title": "seed", "url": "https://seed.example/story"}],
                recent=["recent topic"],
                seo_context={"status": "ok"},
                max_candidates=2,
            )

        self.assertEqual(result_plan["topic"], "Second story with publisher coverage")
        self.assertEqual(story_items, ["source-a", "source-b"])
        self.assertEqual(result_sources, verified)
        self.assertEqual(planner.call_count, 2)
        self.assertIn("Unverifiable first story", planner.call_args_list[1].kwargs["recent"])
        self.assertEqual(researcher.call_count, 2)
        self.assertEqual(verifier.call_count, 2)

    def test_valid_initial_narration_skips_correction_call(self):
        plan = make_test_plan(ORCHESTRA_SENTENCES)
        with tempfile.TemporaryDirectory() as folder:
            original_work = pipeline.WORK
            try:
                pipeline.WORK = Path(folder)
                with patch.object(pipeline, "ai", return_value={"response": plan}) as mock_ai:
                    result = pipeline.make_plan([self.item], recent=[])
                self.assertEqual(mock_ai.call_count, 1)
                self.assertEqual(result["narration_script"], ORCHESTRA_SCRIPT)
                self.assertEqual(result["narration_sentences"], ORCHESTRA_SENTENCES)
            finally:
                pipeline.WORK = original_work

    def test_composer_allows_one_targeted_followup_then_fails_safely(self):
        plan = make_test_plan(RUN22_INITIAL_SENTENCES)
        invalid_fields = {
            "sentence_2_words": ["MIT"],
            "sentence_3_words": ["The"],
            "sentence_4_words": ["This"],
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
