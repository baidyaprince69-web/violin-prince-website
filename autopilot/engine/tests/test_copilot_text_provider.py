"""Offline tests for the isolated Copilot text-planning provider."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from copilot_text_provider import (  # noqa: E402
    CopilotTextProviderError,
    build_prompt,
    generate_text_completion,
)


class CopilotTextProviderTests(unittest.TestCase):
    def test_builds_prompt_from_verified_messages(self):
        prompt = build_prompt({
            "messages": [
                {"role": "system", "content": "Use only the supplied articles."},
                {"role": "user", "content": "Create one sourced story."},
            ],
        })
        self.assertIn("Use only the supplied articles.", prompt)
        self.assertIn("USER:", prompt)
        self.assertIn("Create one sourced story.", prompt)
        self.assertIn("Do not use tools, browse, access files", prompt)

    def test_includes_strict_function_schema_for_narration_repair(self):
        schema = {
            "type": "object",
            "properties": {"sentence_2_words": {"type": "array", "items": {"type": "string"}}},
            "required": ["sentence_2_words"],
            "additionalProperties": False,
        }
        prompt = build_prompt({
            "messages": [
                {"role": "system", "content": "Correct a sentence."},
                {"role": "user", "content": "Use the article evidence."},
            ],
            "tools": [{
                "type": "function",
                "function": {
                    "name": "submit_narration_sentence_corrections",
                    "parameters": schema,
                },
            }],
        })
        self.assertIn("submit_narration_sentence_corrections", prompt)
        self.assertIn('"sentence_2_words"', prompt)
        self.assertIn('"additionalProperties":false', prompt)

    def test_rejects_malformed_payload(self):
        with self.assertRaises(CopilotTextProviderError):
            build_prompt({"messages": []})

    def test_rejects_missing_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(CopilotTextProviderError, "COPILOT_GITHUB_TOKEN"):
                generate_text_completion({"messages": [{"role": "user", "content": "Hi"}]})

    def test_rejects_missing_cli(self):
        with patch.dict(os.environ, {"COPILOT_GITHUB_TOKEN": "test-token"}, clear=True):
            with patch("copilot_text_provider.shutil.which", return_value=None):
                with self.assertRaisesRegex(CopilotTextProviderError, "CLI is not installed"):
                    generate_text_completion({"messages": [{"role": "user", "content": "Hi"}]})

    def test_runs_copilot_isolated_and_returns_strict_json(self):
        completed = SimpleNamespace(
            returncode=0,
            stdout='{"topic":"A verified music fact"}',
            stderr="",
        )
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {
                "COPILOT_GITHUB_TOKEN": "test-token",
                "GITHUB_TOKEN": "repo-token",
                "GH_TOKEN": "gh-token",
            }, clear=True):
                with patch("copilot_text_provider.shutil.which", return_value="/usr/bin/copilot"):
                    with patch("copilot_text_provider.subprocess.run", return_value=completed) as mocked:
                        response = generate_text_completion({
                            "messages": [{"role": "user", "content": "Return JSON."}]
                        })
        self.assertEqual(json.loads(response)["topic"], "A verified music fact")
        command = mocked.call_args.args[0]
        child_env = mocked.call_args.kwargs["env"]
        self.assertIn("--model=auto", command)
        self.assertIn("--disable-builtin-mcps", command)
        self.assertIn("--deny-tool=read,shell,write,url,memory", command)
        self.assertEqual(child_env["COPILOT_GITHUB_TOKEN"], "test-token")
        self.assertNotIn("GITHUB_TOKEN", child_env)
        self.assertNotIn("GH_TOKEN", child_env)
        self.assertNotIn("test-token", " ".join(command))

    def test_redacts_token_from_cli_error(self):
        completed = SimpleNamespace(
            returncode=1,
            stdout="",
            stderr="token test-token was rejected",
        )
        with patch.dict(os.environ, {"COPILOT_GITHUB_TOKEN": "test-token"}, clear=True):
            with patch("copilot_text_provider.shutil.which", return_value="/usr/bin/copilot"):
                with patch("copilot_text_provider.subprocess.run", return_value=completed):
                    with self.assertRaises(CopilotTextProviderError) as caught:
                        generate_text_completion({
                            "messages": [{"role": "user", "content": "Return JSON."}]
                        })
        self.assertNotIn("test-token", str(caught.exception))
        self.assertIn("[REDACTED]", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
