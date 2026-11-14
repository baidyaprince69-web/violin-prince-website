"""Offline tests for ChatGPT-prepared daily production evidence gates."""
import sys
import unittest
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

import run_daily_plan as daily  # noqa: E402


class DailyPlanEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.sources = [
            {
                "source_id": "S001",
                "publisher_domain": "publisher-one.example",
                "evidence_text": "Researchers measured the violin string vibration at several frequencies in a controlled acoustic experiment. This exact passage supports the claim.",
            },
            {
                "source_id": "S002",
                "publisher_domain": "publisher-two.example",
                "evidence_text": "The bridge transfers the string motion into the instrument body, producing resonant sound. This exact passage supports a second claim.",
            },
        ]
        self.sentences = [
            "Why does a violin sound so alive?",
            "Researchers measured the violin string vibration at several frequencies.",
            "The bridge transfers the string motion into the instrument body.",
            "That resonance shapes the sound heard in the room.",
        ]

    def test_exact_article_quotes_cover_each_body_sentence(self):
        evidence = [
            {"sentence_number": 2, "source_id": "S001", "quote": "Researchers measured the violin string vibration at several frequencies in a controlled acoustic experiment."},
            {"sentence_number": 3, "source_id": "S002", "quote": "The bridge transfers the string motion into the instrument body, producing resonant sound."},
            {"sentence_number": 4, "source_id": "S001", "quote": "This exact passage supports the claim."},
        ]
        checked = daily.validate_claim_evidence(evidence, self.sources, self.sentences)
        self.assertEqual([item["sentence_number"] for item in checked], [2, 3, 4])

    def test_rejects_quote_not_present_in_article_body(self):
        evidence = [
            {"sentence_number": 2, "source_id": "S001", "quote": "The violin bridge creates an entirely different sound with this mechanism."},
            {"sentence_number": 3, "source_id": "S002", "quote": "The bridge transfers the string motion into the instrument body, producing resonant sound."},
            {"sentence_number": 4, "source_id": "S001", "quote": "This exact passage supports the claim."},
        ]
        with self.assertRaisesRegex(Exception, "does not appear"):
            daily.validate_claim_evidence(evidence, self.sources, self.sentences)

    def test_rejects_missing_sentence_evidence(self):
        evidence = [
            {"sentence_number": 2, "source_id": "S001", "quote": "Researchers measured the violin string vibration at several frequencies in a controlled acoustic experiment."},
            {"sentence_number": 3, "source_id": "S002", "quote": "The bridge transfers the string motion into the instrument body, producing resonant sound."},
        ]
        with self.assertRaisesRegex(Exception, "Missing exact publisher evidence"):
            daily.validate_claim_evidence(evidence, self.sources, self.sentences)

    def test_rejects_unselected_source(self):
        evidence = [
            {"sentence_number": 2, "source_id": "S999", "quote": "Researchers measured the violin string vibration at several frequencies in a controlled acoustic experiment."},
            {"sentence_number": 3, "source_id": "S002", "quote": "The bridge transfers the string motion into the instrument body, producing resonant sound."},
            {"sentence_number": 4, "source_id": "S001", "quote": "This exact passage supports the claim."},
        ]
        with self.assertRaisesRegex(Exception, "unselected source"):
            daily.validate_claim_evidence(evidence, self.sources, self.sentences)


if __name__ == "__main__":
    unittest.main()
