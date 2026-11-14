"""Regression tests for keeping all daily story evidence on one subject."""
import sys
import unittest
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

import run_daily_plan as daily  # noqa: E402


class StoryCoherenceTests(unittest.TestCase):
    def setUp(self):
        self.plan = {
            "title": "Why a Violin's Back Shape Matters",
            "core_claim": "Changing violin back arch height shifts body resonance patterns",
        }
        self.good_source = {
            "source_id": "S001",
            "title": "Investigating acoustic effects of violin back arch height changes",
            "evidence_text": (
                "Six violins were constructed with different back arch heights. "
                "The signature body modes of the instruments shifted in frequency "
                "when the back arch height changed."
            ),
        }
        self.good_second_source = {
            "source_id": "S002",
            "title": "How violin arch geometry affects body resonance",
            "evidence_text": (
                "The violin back arch changes the instrument's body resonance. "
                "Independent measurements describe the effects of arch geometry."
            ),
        }

    def test_two_independent_articles_about_the_same_claim_pass(self):
        result = daily.validate_story_coherence(
            self.plan,
            [self.good_source, self.good_second_source],
            [
                {"sentence_number": 2, "source_id": "S001"},
                {"sentence_number": 3, "source_id": "S001"},
                {"sentence_number": 4, "source_id": "S002"},
            ],
        )
        self.assertEqual(result["status"], "passed")
        self.assertEqual(len(result["cited_sources"]), 2)

    def test_unrelated_second_study_is_rejected(self):
        unrelated = {
            "source_id": "S002",
            "title": "Neural integration of acoustic statistics enables mice to detect targets in noise",
            "evidence_text": (
                "Mice can detect vocalizations better after sampling background "
                "sound textures for a longer time."
            ),
        }
        with self.assertRaisesRegex(Exception, "unrelated source"):
            daily.validate_story_coherence(
                self.plan,
                [self.good_source, unrelated],
                [
                    {"sentence_number": 2, "source_id": "S001"},
                    {"sentence_number": 3, "source_id": "S001"},
                    {"sentence_number": 4, "source_id": "S002"},
                ],
            )

    def test_rejects_story_without_two_cited_sources(self):
        with self.assertRaisesRegex(Exception, "at least two cited"):
            daily.validate_story_coherence(
                self.plan,
                [self.good_source],
                [{"sentence_number": 2, "source_id": "S001"}],
            )


if __name__ == "__main__":
    unittest.main()
