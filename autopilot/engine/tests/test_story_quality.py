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



    def test_narration_evidence_blocks_unsupported_hype_and_impact_claims(self):
        plan = {
            "narration_script": (
                "Can a machine play the violin? "
                "MIT engineers have now developed a highly advanced and sophisticated virtual violin. "
                "This new technology generates exceptionally realistic and authentic musical string sounds. "
                "These digital strings are fundamentally transforming the entire future of music."
            )
        }
        sources = [
            {
                "source_id": "SRC_MIT_VIOLIN",
                "title": "MIT engineers' computational violin produces realistic sounds",
                "evidence_text": (
                    "MIT engineers developed a computational violin, a computer simulation that captures "
                    "the physics of the instrument and realistically produces sound when strings are plucked. "
                    "The model helps luthiers test design changes before carving wood. Researchers demonstrated "
                    "two short musical excerpts using plucked strings. Bowing is planned for future development."
                ),
            },
            {
                "source_id": "SRC_ARS_VIOLIN",
                "title": "MIT's virtual violin offers luthiers a new design tool",
                "evidence_text": (
                    "The computational model is a design tool for violin makers. It estimates the sound of "
                    "a physical instrument through a model of strings and surrounding air, rather than sampled "
                    "recordings. The current demonstration is limited to plucked strings."
                ),
            },
        ]

        report = pipeline.narration_evidence_report(plan, sources)
        self.assertEqual(report["status"], "blocked")
        self.assertTrue(any("Sentence 4" in issue for issue in report["issues"]))
        self.assertTrue(any("transforming" in issue.casefold() for issue in report["issues"]))
        self.assertTrue(any(
            item["unsupported_emphasis_terms"]
            for item in report["sentences"]
            if item["sentence_number"] > 1
        ))

    def test_evidence_grounded_narration_passes_sentence_level_check(self):
        plan = {
            "narration_script": (
                "Can a physics model recreate a violin's sound? "
                "MIT engineers developed a computational violin to help luthiers test designs. "
                "It models string vibrations and surrounding air to reproduce realistic plucked notes. "
                "Bowing is still planned as future work beyond plucked-string demonstrations."
            )
        }
        evidence = (
            "MIT engineers developed a computational violin model to help luthiers test instrument designs. "
            "It models string vibrations and the surrounding air to reproduce realistic plucked notes. "
            "Researchers demonstrated two short musical excerpts using plucked strings. "
            "Bowing is still planned as future work beyond plucked-string demonstrations."
        )
        sources = [
            {
                "source_id": "SRC_MIT_VIOLIN",
                "title": "MIT engineers' computational violin produces realistic sounds",
                "evidence_text": evidence,
            },
            {
                "source_id": "SRC_ARS_VIOLIN",
                "title": "MIT's computational violin is a design tool",
                "evidence_text": evidence + " The simulation is intended to support instrument design.",
            },
        ]

        report = pipeline.narration_evidence_report(plan, sources)
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["checked_sentence_count"], 4)
        self.assertEqual(report["issues"], [])
        self.assertTrue(all(
            item["support_coverage"] >= 0.60
            for item in report["sentences"][1:]
        ))

if __name__ == "__main__":
    unittest.main()
