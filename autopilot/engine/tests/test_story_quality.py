"""Regression tests for event-date and future-wording checks."""
import os
import sys
import unittest
from datetime import date
from pathlib import Path

os.environ.setdefault("CF_ACCOUNT_ID", "test-account")
os.environ.setdefault("CF_AI_TOKEN", "test-ai-token")
ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import run as pipeline


class StoryDateQualityTests(unittest.TestCase):
    AS_OF = date(2026, 11, 14)


    def test_timeline_year_conflicting_with_publisher_article_is_blocked(self):
        sources = [
            {
                "source_id": "SRC_A",
                "evidence_text": (
                    "The World Soundtrack Awards will take place in Ghent from "
                    "October 8–10, 2026, during Film Fest Gent."
                ),
            },
            {
                "source_id": "SRC_B",
                "evidence_text": (
                    "The 2026 World Soundtrack Awards programme runs from October 8 to 10, 2026."
                ),
            },
        ]
        with self.assertRaisesRegex(pipeline.PipelineError, "conflicts with publisher date evidence"):
            pipeline.validate_timeline_date_against_sources("2025-10-10", sources, "World Soundtrack Awards")

    def test_timeline_year_matching_publisher_article_is_allowed(self):
        sources = [
            {
                "source_id": "SRC_A",
                "evidence_text": "The World Soundtrack Awards take place October 8–10, 2026, in Ghent.",
            }
        ]
        self.assertIsNone(
            pipeline.validate_timeline_date_against_sources(
                "2026-10-10", sources, "World Soundtrack Awards"
            )
        )

    def test_past_event_described_as_upcoming_is_blocked(self):
        plan = {
            "narration_script": "She will perform at the final on October 15, 2026.",
            "timeline": [
                {
                    "event": "BBC Young Musician final",
                    "date": "2026-10-15",
                    "status": "upcoming",
                    "source_ids": ["S0001", "S0002"],
                }
            ],
        }
        result = pipeline.validate_story_dates(plan, as_of=self.AS_OF)
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("has passed" in issue for issue in result["issues"]))
        self.assertTrue(any("future wording" in issue for issue in result["issues"]))

    def test_future_event_wording_without_a_verified_future_timeline_is_blocked(self):
        plan = {"narration_script": "She will perform at the national final."}
        result = pipeline.validate_story_dates(plan, as_of=self.AS_OF)
        self.assertEqual(result["status"], "blocked")
        self.assertTrue(any("verified future-dated timeline" in issue for issue in result["issues"]))

    def test_past_event_described_as_completed_passes(self):
        plan = {
            "narration_script": "She performed at the final on October 15, 2026.",
            "timeline": [
                {
                    "event": "BBC Young Musician final",
                    "date": "2026-10-15",
                    "status": "completed",
                    "source_ids": ["S0001", "S0002"],
                }
            ],
        }
        result = pipeline.validate_story_dates(plan, as_of=self.AS_OF)
        self.assertEqual(result["status"], "passed")
        self.assertEqual(result["dates_found_in_story"][0]["date"], "2026-10-15")

    def test_correctly_dated_future_event_passes(self):
        plan = {
            "narration_script": "She will perform at the final on December 15, 2026.",
            "timeline": [
                {
                    "event": "National final",
                    "date": "2026-12-15",
                    "status": "upcoming",
                    "source_ids": ["S0001"],
                }
            ],
        }
        result = pipeline.validate_story_dates(plan, as_of=self.AS_OF)
        self.assertEqual(result["status"], "passed")

    def test_english_month_date_parser_supports_ordinal_suffixes(self):
        self.assertEqual(
            pipeline.parse_story_date("October 15th, 2026"),
            date(2026, 10, 15),
        )


class NarrationEvidenceQualityTests(unittest.TestCase):
    def test_evidence_gate_reports_all_unsupported_body_sentences(self):
        plan = {
            "narration_script": (
                "Can computers truly feel music? "
                "New AI models can identify emotions in instrumental music with precision. "
                "Researchers use convolutional neural networks for classification tasks. "
                "Technology is learning the deep soul of each note."
            )
        }
        with self.assertRaises(pipeline.PipelineError) as raised:
            pipeline.validate_narration_against_sources(plan, self.sources)
        message = str(raised.exception)
        self.assertIn("narration sentence 2", message)
        self.assertIn("narration sentence 3", message)
        self.assertIn("narration sentence 4", message)

    def setUp(self):
        self.sources = [
            {
                "source_id": "SRC_MIT_VIOLIN",
                "title": "MIT engineers' virtual violin produces realistic sounds",
                "publisher_name": "MIT News",
                "publisher_domain": "news.mit.edu",
                "evidence_text": (
                    "MIT engineers developed a physics-based computational violin model. "
                    "It produces realistic sounds when strings are plucked. The model simulates "
                    "how the instrument structure and surrounding air interact. Bowing is a more "
                    "complicated interaction to model. Luthiers can adjust wood type and body "
                    "thickness to compare predicted sound before carving a physical instrument."
                ),
            }
        ]

    def test_unsupported_transformative_narration_claim_is_blocked(self):
        plan = {
            "narration_script": (
                "Can computers model violin sounds? "
                "MIT engineers developed a computational violin model. "
                "It produces realistic sounds when strings are plucked. "
                "These digital strings are fundamentally transforming the entire future of music."
            )
        }
        with self.assertRaisesRegex(pipeline.PipelineError, "narration sentence 4"):
            pipeline.validate_narration_against_sources(plan, self.sources)

    def test_each_factual_sentence_records_a_direct_article_evidence_match(self):
        plan = {
            "narration_script": (
                "Can computers model violin sounds? "
                "MIT engineers developed a computational violin model. "
                "It produces realistic sounds when strings are plucked. "
                "Bowing is a more complicated interaction to model."
            )
        }
        evidence = pipeline.validate_narration_against_sources(plan, self.sources)
        self.assertEqual(len(evidence), 3)
        self.assertEqual([item["sentence_number"] for item in evidence], [2, 3, 4])
        self.assertTrue(all(item["source_id"] == "SRC_MIT_VIOLIN" for item in evidence))
        self.assertTrue(all(item["matched_terms"] for item in evidence))


if __name__ == "__main__":
    unittest.main()
