"""Tests for exact-token karaoke subtitle generation."""
import ast
import sys
import tempfile
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from voiceover import OwnVoiceRequiredError, require_approved_own_voice, synthesize_voiceover, write_karaoke_ass


class KaraokeCaptionTests(unittest.TestCase):
    def test_global_production_gate_is_closed_without_approved_own_voice(self):
        with self.assertRaisesRegex(
            OwnVoiceRequiredError,
            "research, visuals and rendering are stopped",
        ):
            require_approved_own_voice()

    def test_all_production_entrypoints_gate_before_research_or_work(self):
        cases = [
            (
                "run.py",
                "main",
                ("WORK.mkdir", "prepare_stage", "visuals_stage", "render_stage"),
            ),
            (
                "run_daily_plan.py",
                "run_daily_plan",
                ("Path", "validate_and_enrich_plan", "get_audio", "synthesize_voiceover"),
            ),
        ]
        for filename, function_name, later_calls in cases:
            source = (ENGINE / filename).read_text(encoding="utf-8")
            tree = ast.parse(source, filename=filename)
            function = next(
                node for node in ast.walk(tree)
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                and node.name == function_name
            )
            gate_lines = [
                node.lineno for node in ast.walk(function)
                if isinstance(node, ast.Call)
                and (
                    (isinstance(node.func, ast.Name) and node.func.id == "require_approved_own_voice")
                    or (isinstance(node.func, ast.Attribute) and node.func.attr == "require_approved_own_voice")
                )
            ]
            self.assertTrue(gate_lines, f"{filename}.{function_name} must call the own-voice gate.")
            gate_line = min(gate_lines)
            for label in later_calls:
                matching_lines = [
                    node.lineno for node in ast.walk(function)
                    if isinstance(node, ast.Call)
                    and (
                        (isinstance(node.func, ast.Name) and node.func.id == label)
                        or (isinstance(node.func, ast.Attribute) and node.func.attr == label)
                    )
                ]
                self.assertTrue(matching_lines, f"Expected {label} call in {filename}.{function_name}.")
                self.assertLess(
                    gate_line,
                    min(matching_lines),
                    f"{filename}.{function_name} must gate before {label}.",
                )

    def test_production_narration_fails_closed_without_approved_own_voice(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "must-not-be-created.wav"
            with self.assertRaisesRegex(
                OwnVoiceRequiredError,
                "own-voice model has not passed voice testing and approval",
            ):
                synthesize_voiceover(
                    "This narration must never be rendered by a fallback voice.",
                    output,
                )
            self.assertFalse(output.exists())

    def sample_cues(self):
        return [
            {"text": "The", "start": 0.00, "end": 0.22, "sentence_index": 0},
            {"text": "violin", "start": 0.23, "end": 0.68, "sentence_index": 0},
            {"text": "sings.", "start": 0.70, "end": 1.08, "sentence_index": 0},
            {"text": "Softly,", "start": 1.30, "end": 1.70, "sentence_index": 1},
            {"text": "and", "start": 1.72, "end": 1.85, "sentence_index": 1},
            {"text": "clearly.", "start": 1.88, "end": 2.24, "sentence_index": 1},
        ]

    def test_writes_short_word_timed_highlight_events(self):
        with tempfile.TemporaryDirectory() as folder:
            path = write_karaoke_ass(self.sample_cues(), Path(folder) / "captions.ass")
            source = path.read_text(encoding="utf-8")
            self.assertIn("PlayResX: 720", source)
            self.assertIn("PlayResY: 1280", source)
            self.assertIn("Style: Karaoke", source)
            self.assertEqual(source.count("Dialogue:"), 4)
            self.assertEqual(source.count(r"{\k"), 6)
            self.assertNotIn("The violin sings.", source)

    def test_rejects_missing_or_invalid_word_timestamps(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                write_karaoke_ass([], Path(folder) / "empty.ass")
            with self.assertRaises(ValueError):
                write_karaoke_ass(
                    [{"text": "word", "start": 1.0, "end": 0.5}],
                    Path(folder) / "bad.ass",
                )

    def test_limits_caption_group_to_maximum_three_words(self):
        cues = [
            {"text": str(i), "start": i * .2, "end": i * .2 + .1, "sentence_index": 0}
            for i in range(7)
        ]
        with tempfile.TemporaryDirectory() as folder:
            path = write_karaoke_ass(cues, Path(folder) / "captions.ass", words_per_caption=9)
            source = path.read_text(encoding="utf-8")
            self.assertEqual(source.count("Dialogue:"), 3)


if __name__ == "__main__":
    unittest.main()
