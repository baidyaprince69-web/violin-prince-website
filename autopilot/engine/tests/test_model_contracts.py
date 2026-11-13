"""Offline contract tests for the Cloudflare Workers AI model requests."""
import base64
import os
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from PIL import Image

os.environ.setdefault("CF_ACCOUNT_ID", "test-account")
os.environ.setdefault("CF_AI_TOKEN", "test-ai-token")
ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import run as pipeline


class FluxRequestContractTests(unittest.TestCase):
    def test_payload_contains_only_supported_flux_fields(self):
        payload = pipeline.image_request_payload("a cinematic portrait illustration")
        self.assertEqual(set(payload), {"prompt", "steps"})
        self.assertEqual(payload["prompt"], "a cinematic portrait illustration")
        self.assertEqual(payload["steps"], 4)

    def test_overlong_prompt_is_rejected_instead_of_silently_truncated(self):
        with self.assertRaisesRegex(pipeline.PipelineError, "safe model limit"):
            pipeline.image_request_payload("x" * 1801)

    def test_prompt_at_model_limit_is_sent_without_modification(self):
        prompt = "x" * pipeline.MAX_IMAGE_PROMPT_CHARS
        payload = pipeline.image_request_payload(prompt)
        self.assertEqual(payload["prompt"], prompt)
        self.assertEqual(len(payload["prompt"]), pipeline.MAX_IMAGE_PROMPT_CHARS)

    def test_empty_prompt_is_rejected_before_api_call(self):
        with self.assertRaises(pipeline.PipelineError):
            pipeline.image_request_payload("   ")

    def test_make_image_uses_validated_payload_and_checks_image_bytes(self):
        buffer = BytesIO()
        Image.new("RGB", (32, 32), (30, 60, 90)).save(buffer, format="JPEG")
        encoded = base64.b64encode(buffer.getvalue()).decode("ascii")

        with tempfile.TemporaryDirectory() as folder:
            calls = []

            def fake_ai(model, payload, timeout):
                calls.append((model, payload, timeout))
                return {"image": encoded}

            with patch.object(pipeline, "IMAGES", Path(folder)), patch.object(pipeline, "ai", side_effect=fake_ai):
                output = pipeline.make_image("a cinematic illustration", 0)

            self.assertTrue(output.exists())
            with Image.open(output) as generated:
                self.assertEqual(generated.size, (32, 32))
            self.assertEqual(len(calls), 1)
            model, payload, timeout = calls[0]
            self.assertEqual(model, pipeline.IMAGE_MODEL)
            self.assertEqual(set(payload), {"prompt", "steps"})
            self.assertEqual(timeout, 240)

    def test_invalid_image_bytes_fail_with_clear_error(self):
        invalid = base64.b64encode(b"not-an-image").decode("ascii")
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(pipeline, "IMAGES", Path(folder)), patch.object(
                pipeline, "ai", return_value={"image": invalid}
            ):
                with self.assertRaisesRegex(pipeline.PipelineError, "invalid or undecodable"):
                    pipeline.make_image("a cinematic illustration", 0)


if __name__ == "__main__":
    unittest.main()
