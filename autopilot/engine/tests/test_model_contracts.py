"""Offline tests for provider-neutral prompt validation and fail-closed AI calls."""
import sys
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import run as pipeline


class ProviderBoundaryTests(unittest.TestCase):
    def test_image_prompt_is_bounded_and_provider_neutral(self):
        payload = pipeline.image_request_payload("a cinematic portrait illustration")
        self.assertEqual(set(payload), {"prompt"})
        self.assertEqual(payload["prompt"], "a cinematic portrait illustration")

    def test_long_prompt_is_bounded_to_1800_characters(self):
        payload = pipeline.image_request_payload("x" * 3000)
        self.assertEqual(len(payload["prompt"]), 1800)

    def test_empty_prompt_is_rejected_before_provider_selection(self):
        with self.assertRaises(pipeline.PipelineError):
            pipeline.image_request_payload("   ")

    def test_image_generation_stops_until_non_cloudflare_provider_is_configured(self):
        with self.assertRaisesRegex(
            pipeline.PipelineError,
            "Scene illustration generation is disabled until an approved provider is configured",
        ):
            pipeline.make_image("a cinematic illustration", 0)

    def test_text_generation_stops_until_non_cloudflare_provider_is_configured(self):
        with self.assertRaisesRegex(
            pipeline.PipelineError,
            "No approved text-generation provider is configured",
        ):
            pipeline.ai("text-generation", {"prompt": "synthetic test"})

    def test_image_generation_stops_until_non_cloudflare_provider_is_configured(self):
        with self.assertRaisesRegex(
            pipeline.PipelineError,
            "No approved illustration-generation provider is configured",
        ):
            pipeline.ai("image-generation", {"prompt": "synthetic test"})


if __name__ == "__main__":
    unittest.main()
