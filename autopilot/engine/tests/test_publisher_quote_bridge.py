"""Exact publisher-quote handoff tests for the live research pipeline."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import run as pipeline  # noqa: E402


class PublisherQuoteBridgeTests(unittest.TestCase):
    def test_returns_a_verbatim_source_quote_for_a_supported_claim(self):
        body = (
            "Researchers developed a computational violin model. "
            "The model simulates string vibration and the interaction between the "
            "instrument structure and surrounding air. "
            "The current model handles plucked strings more completely than bowing."
        )
        source = {"evidence_text": body, "title": "A computational violin model"}
        sentence = "The model simulates string vibration and the interaction between the instrument structure."
        quote = pipeline._exact_publisher_quote_for_claim(sentence, source)
        self.assertTrue(quote)
        self.assertIn(quote, body)
        self.assertGreaterEqual(len(quote), 28)

    def test_rejects_a_claim_without_matching_publisher_evidence(self):
        source = {
            "evidence_text": "Researchers developed a computational violin model that simulates string vibration.",
            "title": "A computational violin model",
        }
        sentence = "The instrument creates a mysterious emotional colour through magic."
        self.assertEqual(pipeline._exact_publisher_quote_for_claim(sentence, source), "")


if __name__ == "__main__":
    unittest.main()
