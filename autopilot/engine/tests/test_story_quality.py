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


if __name__ == "__main__":
    unittest.main()
