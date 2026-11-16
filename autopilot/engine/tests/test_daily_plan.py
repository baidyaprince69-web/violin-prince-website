"""Offline tests for ChatGPT-prepared daily production evidence gates."""
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

import run_daily_plan as daily  # noqa: E402


class DailyPlanEvidenceTests(unittest.TestCase):
    def setUp(self):
        self.legacy_motion_env = patch.dict(os.environ, {"MOTION_HYPERFRAMES_RENDER_ENABLED": "false"})
        self.legacy_motion_env.start()
        self.addCleanup(self.legacy_motion_env.stop)
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

    def test_motion_narration_uses_five_sentences_with_forty_to_forty_four_words(self):
        script = (
            "Your room can quietly mislead your mix. "
            "Audient's iD interfaces pair console-style preamps with onboard DSP. "
            "RoomTune measures room acoustics and corrects monitor playback. "
            "EQ, compression and reverb shape tone, dynamics and space. "
            "Now hear your violin through a clearer, trusted mix."
        )
        with patch.dict(os.environ, {"MOTION_HYPERFRAMES_RENDER_ENABLED": "true"}):
            self.assertEqual(daily.engine.narration_word_count(script), 42)
            self.assertEqual(daily.engine.narration_validation_error(script), "")
            parts = daily.engine.narration_sentences(script)
            budgets = daily.engine.narration_sentence_budget(parts, target_total=42)
            self.assertEqual(len(budgets), 5)
            self.assertEqual(daily.engine._plan_sentence_fields({"narration_sentences": parts}), parts)

        with patch.dict(os.environ, {"MOTION_HYPERFRAMES_RENDER_ENABLED": "false"}):
            issue = daily.engine.narration_validation_error(script)
        self.assertIn("exactly 4 are required", issue)

    def test_motion_evidence_requires_only_the_three_technical_claims(self):
        five_sentences = list(self.sentences) + [
            "Now hear your violin through a clearer, trusted mix."
        ]
        evidence = [
            {"sentence_number": 2, "source_id": "S001", "quote": "Researchers measured the violin string vibration at several frequencies in a controlled acoustic experiment."},
            {"sentence_number": 3, "source_id": "S002", "quote": "The bridge transfers the string motion into the instrument body, producing resonant sound."},
            {"sentence_number": 4, "source_id": "S001", "quote": "This exact passage supports the claim."},
        ]
        with patch.dict(os.environ, {"MOTION_HYPERFRAMES_RENDER_ENABLED": "true"}):
            checked = daily.validate_claim_evidence(evidence, self.sources, five_sentences)
        self.assertEqual([item["sentence_number"] for item in checked], [2, 3, 4])

    def test_motion_quality_report_excludes_music_payoff_from_claim_evidence_count(self):
        plan = {
            "narration_script": (
                "Your room can quietly mislead your mix. "
                "Audient's iD pairs preamps with onboard DSP. "
                "RoomTune measures acoustics and corrects monitor playback. "
                "EQ, compression and reverb shape tone, dynamics and space. "
                "Now hear your violin phrase return with clearer monitor sound."
            ),
            "narration_evidence": [
                {"sentence_number": 2, "source_id": "S001"},
                {"sentence_number": 3, "source_id": "S002"},
                {"sentence_number": 4, "source_id": "S002"},
            ],
            "timeline": [],
            "timeline_evidence": [],
        }
        sources = [
            {"source_id": "S001", "publisher_domain": "musicradar.com", "url": "https://musicradar.com/article", "article_page_verified": True},
            {"source_id": "S002", "publisher_domain": "mixdownmag.com.au", "url": "https://mixdownmag.com.au/article", "article_page_verified": True},
        ]
        with patch.dict(os.environ, {"MOTION_HYPERFRAMES_RENDER_ENABLED": "true"}), \
             patch.object(daily.engine, "is_direct_publisher_article", return_value=True), \
             patch.object(daily.engine, "article_freshness", return_value={"freshness_status": "acceptable", "age_hours": 48}):
            report = daily.engine.build_story_quality_report(plan, sources, {"status": "passed"})
        self.assertEqual(report["narration_claim_sentence_count"], 3)
        self.assertEqual(report["narration_evidence_status"], "passed")
        self.assertEqual(report["status"], "passed")

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

    def test_daily_production_requires_motion_hyperframes(self):
        with patch.object(daily, "is_motion_hyperframes_render_enabled", return_value=False), \
             patch.object(daily.engine, "is_blender_render_enabled", return_value=False):
            with self.assertRaisesRegex(daily.engine.PipelineError, "Motion \\+ HyperFrames is mandatory"):
                daily.run_daily_plan(Path("missing-daily-plan.json"))

    def test_daily_production_rejects_blender(self):
        with patch.object(daily, "is_motion_hyperframes_render_enabled", return_value=True), \
             patch.object(daily.engine, "is_blender_render_enabled", return_value=True):
            with self.assertRaisesRegex(daily.engine.PipelineError, "2D-only"):
                daily.run_daily_plan(Path("missing-daily-plan.json"))

    def test_main_accepts_validated_motion_explainer_filename(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            (output / "violin-prince-explainer.mp4").write_bytes(b"valid-motion-mp4" * 512)
            with patch.object(daily, "run_daily_plan", return_value=0), \
                 patch.object(daily, "is_motion_hyperframes_render_enabled", return_value=True), \
                 patch.object(daily.engine, "OUT", output), \
                 patch.object(daily.engine, "validate_final_video") as legacy_validator, \
                 patch.object(sys, "argv", ["run_daily_plan.py", "--plan", "plan.json"]):
                self.assertEqual(daily.main(), 0)
                legacy_validator.assert_not_called()


if __name__ == "__main__":
    unittest.main()
