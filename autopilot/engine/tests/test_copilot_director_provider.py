"""Offline tests for the isolated GitHub Copilot Master Director adapter."""
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

from copilot_director_provider import (  # noqa: E402
    CopilotDirectorError,
    _decode_director_json,
    generate_director_plan,
    write_director_plan,
)
from master_creative_director import validate_director_plan  # noqa: E402


def valid_plan():
    purposes = ["hook", "context", "reveal", "explanation", "contrast", "reveal", "payoff", "ending"]
    sizes = ["extreme_wide", "wide", "medium", "close_up", "macro", "overhead", "point_of_view", "close_up"]
    movements = ["dolly_in", "truck_left", "orbit", "pan", "crane_up", "tracking", "whip_pan", "dolly_out"]
    transitions = ["match_cut", "whip_pan", "dissolve", "cut", "foreground_wipe", "speed_ramp", "light_transition", "none"]
    shots = []
    for index in range(8):
        start = index * 4
        shots.append({
            "id": f"shot-{index + 1:02d}",
            "start_seconds": start,
            "end_seconds": start + 4,
            "purpose": purposes[index],
            "visual_subject": f"Distinct subject {index + 1}",
            "setting": f"Specific setting {index + 1}",
            "visual_description": f"Original cinematic shot showing visual detail {index + 1}",
            "composition": f"Layered composition and focal hierarchy {index + 1}",
            "camera": {
                "shot_size": sizes[index],
                "angle": f"Purposeful camera angle {index + 1}",
                "movement": movements[index],
                "focus": f"Focus follows detail {index + 1}",
            },
            "animation": {
                "subject_action": f"Meaningful subject movement {index + 1}",
                "environment_motion": f"Environment responds {index + 1}",
                "graphic_action": "",
                "depth_motion": f"Foreground and background shift {index + 1}",
                "motion_rationale": f"Movement supports the story beat {index + 1}",
            },
            "transition_to_next": transitions[index],
            "narration_cue": f"Narration beat {index + 1}",
            "music_cue": f"Music cue {index + 1}",
            "sound_effects": [],
        })
    return {
        "schema_version": 1,
        "story_understanding": {
            "central_truth": "One grounded music fact.",
            "viewer_question": "Why does this sound happen?",
            "emotional_arc": ["curiosity", "discovery", "understanding"],
            "key_revelations": ["The first supported detail.", "The second supported detail."],
        },
        "visual_concept": {
            "concept_name": "Resonance in motion",
            "visual_metaphor": "A visible wave travelling through the instrument.",
            "creative_rationale": "The metaphor makes an acoustic process visible.",
            "art_direction": "Tactile, cinematic macro photography language.",
            "palette": {
                "dominant": "#19324A",
                "secondary": "#D6E0E8",
                "accent": "#D95D39",
                "harmony": "temperature_contrast",
                "reasoning": "Cool structure contrasts with the warm energy of vibration.",
                "contrast_strategy": "Use the dark dominant behind light type and reserve accent for the focal event.",
            },
            "lighting_plan": "Directional rim light reveals surface texture.",
            "composition_language": "Foreground and background separate the instrument from the visual explanation.",
        },
        "storyboard": {"duration_seconds": 32, "shots": shots},
        "edit_direction": {
            "pacing": "Accelerate into the reveal and settle on the payoff.",
            "transition_language": "Use match movement early, then a clean cut into the ending.",
            "typography": "Short phone-readable labels outside the main focal region.",
            "sound_design": "Small restrained accents reinforce factual reveals.",
            "music_mood": "Build from restrained curiosity to a resolved musical payoff.",
            "music_sync_cues": [
                {"time_seconds": 4, "event": "First visual reveal", "reason": "Align with the first major musical accent."},
                {"time_seconds": 20, "event": "Payoff transition", "reason": "Give the final musical phrase room to land."},
            ],
            "final_payoff": "The visual metaphor resolves into the instrument's musical result.",
        },
    }


def story_context():
    return {
        "topic": "How violin strings vibrate",
        "title": "What Makes a Violin String Move?",
        "narration_script": "A verified narration script about string vibration.",
        "verified_sources": [
            {"source_id": "S1", "title": "Publisher A", "url": "https://example.com/a", "evidence_text": "Evidence A"},
            {"source_id": "S2", "title": "Publisher B", "url": "https://example.org/b", "evidence_text": "Evidence B"},
        ],
    }


class CopilotDirectorProviderTests(unittest.TestCase):
    def test_rejects_missing_token(self):
        with patch.dict(os.environ, {}, clear=True):
            with self.assertRaisesRegex(CopilotDirectorError, "COPILOT_GITHUB_TOKEN"):
                generate_director_plan(story_context())

    def test_rejects_missing_cli(self):
        with patch.dict(os.environ, {"COPILOT_GITHUB_TOKEN": "test-token"}, clear=True):
            with patch("copilot_director_provider.shutil.which", return_value=None):
                with self.assertRaisesRegex(CopilotDirectorError, "CLI is not installed"):
                    generate_director_plan(story_context())

    def test_calls_copilot_with_limited_tool_surface_and_validates_response(self):
        response = json.dumps(valid_plan())
        completed = SimpleNamespace(returncode=0, stdout=response, stderr="")
        with patch.dict(os.environ, {"COPILOT_GITHUB_TOKEN": "test-token", "GITHUB_TOKEN": "repo-token"}, clear=True):
            with patch("copilot_director_provider.shutil.which", return_value="/usr/bin/copilot"):
                with patch("copilot_director_provider.subprocess.run", return_value=completed) as mocked:
                    result = generate_director_plan(story_context())

        self.assertEqual(validate_director_plan({k: v for k, v in result.items() if k != "_director_provider"}), [])
        command = mocked.call_args.args[0]
        child_env = mocked.call_args.kwargs["env"]
        self.assertIn("--model=auto", command)
        self.assertIn("--available-tools=view", command)
        self.assertIn("--deny-tool=read,shell,write,url,memory", command)
        self.assertIn("--disable-builtin-mcps", command)
        self.assertIn("--disable-client-telemetry", command)
        self.assertIn("--max-ai-credits=8", command)
        self.assertEqual(child_env["COPILOT_GITHUB_TOKEN"], "test-token")
        self.assertNotIn("GITHUB_TOKEN", child_env)
        self.assertNotIn("GH_TOKEN", child_env)
        self.assertEqual(result["_director_provider"]["provider"], "github-copilot-cli")
        self.assertNotIn("test-token", " ".join(command))

    def test_reports_provider_failure_without_exposing_token(self):
        completed = SimpleNamespace(returncode=1, stdout="", stderr="bad token test-token")
        with patch.dict(os.environ, {"COPILOT_GITHUB_TOKEN": "test-token"}, clear=True):
            with patch("copilot_director_provider.shutil.which", return_value="/usr/bin/copilot"):
                with patch("copilot_director_provider.subprocess.run", return_value=completed):
                    with self.assertRaises(CopilotDirectorError) as caught:
                        generate_director_plan(story_context())
        self.assertNotIn("test-token", str(caught.exception))
        self.assertIn("[REDACTED]", str(caught.exception))

    def test_rejects_non_json_and_invalid_director_plan(self):
        with self.assertRaises(CopilotDirectorError):
            _decode_director_json("Here is your storyboard.")
        invalid = valid_plan()
        invalid["storyboard"]["shots"] = invalid["storyboard"]["shots"][:3]
        with self.assertRaises(CopilotDirectorError):
            _decode_director_json(json.dumps(invalid))

    def test_accepts_one_json_code_fence(self):
        parsed = _decode_director_json("```json\n" + json.dumps(valid_plan()) + "\n```")
        self.assertEqual(len(parsed["storyboard"]["shots"]), 8)

    def test_writes_validated_plan_atomically(self):
        plan = valid_plan()
        plan["_director_provider"] = {"provider": "github-copilot-cli", "model_selection": "auto"}
        with tempfile.TemporaryDirectory() as directory:
            destination = Path(directory) / "package" / "master-director-plan.json"
            written = write_director_plan(plan, destination)
            self.assertEqual(written, destination)
            saved = json.loads(destination.read_text(encoding="utf-8"))
            self.assertEqual(saved["_director_provider"]["provider"], "github-copilot-cli")
            self.assertFalse(destination.with_suffix(".json.tmp").exists())


if __name__ == "__main__":
    unittest.main()
