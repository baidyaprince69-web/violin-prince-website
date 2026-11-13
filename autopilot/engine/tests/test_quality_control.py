"""Unit tests for Phase 2 fail-closed production quality control."""
import sys
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from quality_control import (
    retry_stage_for_failures,
    resolve_frame_rate,
    validate_cues,
    validate_text_audit_payload,
)


class QualityControlTests(unittest.TestCase):
    def test_valid_native_word_cues_pass_with_required_coverage(self):
        cues = [
            {"start": 0.00, "end": 0.22, "text": "Can"},
            {"start": 0.23, "end": 0.46, "text": "one"},
            {"start": 0.48, "end": 0.82, "text": "person"},
            {"start": 0.84, "end": 1.10, "text": "play"},
            {"start": 1.12, "end": 1.42, "text": "this"},
            {"start": 1.44, "end": 1.80, "text": "music?"},
            {"start": 1.82, "end": 2.10, "text": "A"},
            {"start": 2.12, "end": 2.46, "text": "great"},
            {"start": 2.48, "end": 2.82, "text": "artist"},
            {"start": 2.84, "end": 3.20, "text": "performs"},
        ]
        result = validate_cues(cues, 24, word_count=10, require_word_timing=True)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["count"], 10)

    def test_cue_order_overlap_and_out_of_bounds_are_rejected(self):
        cues = [
            {"start": 0.0, "end": 1.0, "text": "First"},
            {"start": 0.4, "end": 1.2, "text": "Second"},
            {"start": 25.0, "end": 25.3, "text": "Late"},
        ]
        result = validate_cues(cues, 24)
        self.assertFalse(result["valid"])
        self.assertTrue(any("overlaps" in error for error in result["errors"]))
        self.assertTrue(any("beyond" in error for error in result["errors"]))

    def test_empty_cue_list_fails_closed(self):
        self.assertFalse(validate_cues([], 24)["valid"])

    def test_sampled_encoded_frame_text_audit_passes(self):
        payload = {
            "ok": True,
            "frames": [
                {
                    "ok": True,
                    "expected_text_nodes": 7,
                    "actual_text_nodes": 7,
                    "missing_text": [],
                    "invalid_text_nodes": [],
                    "out_of_bounds_text": [],
                    "narration_word_count": 41,
                    "timed_word_count": 41,
                    "narration_word_order_valid": True,
                }
                for _ in range(5)
            ],
        }
        result = validate_text_audit_payload(payload)
        self.assertTrue(result["valid"], result["errors"])
        self.assertEqual(result["frame_count"], 5)

    def test_text_audit_rejects_missing_or_overflowing_captions(self):
        payload = {
            "ok": False,
            "frames": [{
                "ok": False,
                "expected_text_nodes": 5,
                "actual_text_nodes": 4,
                "missing_text": ["missing"],
                "invalid_text_nodes": [],
                "out_of_bounds_text": ["overflow"],
                "narration_word_order_valid": False,
            }] * 5,
        }
        result = validate_text_audit_payload(payload)
        self.assertFalse(result["valid"])
        self.assertTrue(result["errors"])

    def test_frame_rate_uses_nominal_rate_when_average_is_zero_or_invalid(self):
        self.assertAlmostEqual(resolve_frame_rate("0/0", "25/1", 600, 24.0), 25.0)
        self.assertAlmostEqual(resolve_frame_rate("N/A", "30/1", None, 24.0), 30.0)
        self.assertAlmostEqual(resolve_frame_rate("0/0", "N/A", 600, 24.0), 25.0)

    def test_frame_rate_can_be_derived_from_actual_decoded_frame_count(self):
        self.assertAlmostEqual(resolve_frame_rate("0/0", "0/0", "600", 24.0), 25.0)

    def test_motion_prototype_retries_narration_when_timing_gate_fails(self):
        source = (ENGINE / "motion_prototype.py").read_text(encoding="utf-8")
        stage = source.split("# Stage 1 — narration.", 1)[1].split("# Stage 2 — baseline.", 1)[0]
        self.assertIn("_valid_narration(candidate_info)", stage)
        self.assertIn("retrying only narration", stage)
        self.assertIn("word_timing_method", stage)
        self.assertIn("validate_cues(", stage)

    def test_renderer_distinguishes_legacy_visual_packages_from_ai_reviewed_packages(self):
        source = (ENGINE / "motion_prototype.py").read_text(encoding="utf-8")
        helper = source.split("def _validate_approved_visual_package(", 1)[1].split("def _mix_audio(", 1)[0]
        self.assertIn("legacy_visuals_ready_no_machine_review_records", helper)
        self.assertIn("ai_reviewed_hash_verified", helper)
        self.assertIn("visual_review_status", helper)
        self.assertIn("recorded_plan_hash", helper)

    def test_retry_planner_targets_only_the_failed_stage(self):
        self.assertEqual(retry_stage_for_failures([{"passed": False, "category": "audio"}]), "audio_mix")
        self.assertEqual(retry_stage_for_failures([{"passed": False, "category": "text"}]), "video_render")
        self.assertEqual(retry_stage_for_failures([{"passed": False, "category": "video"}]), "video_render")
        self.assertEqual(retry_stage_for_failures([{"passed": False, "category": "narration"}]), "none")

    def test_prepare_and_visual_stages_persist_intermediate_checkpoints(self):
        source = (ENGINE / "run.py").read_text(encoding="utf-8")
        prepare = source.split("def prepare_stage(", 1)[1].split("def visuals_stage(", 1)[0]
        visuals = source.split("def visuals_stage(", 1)[1].split("def render_stage(", 1)[0]
        self.assertIn("Reusing checkpointed narration", prepare)
        self.assertIn("Reusing checkpointed creative plan", prepare)
        self.assertIn('metadata["stage"] = "visuals_in_progress"', visuals)
        self.assertIn('_write_json_atomic(paths["metadata"], metadata)', visuals)
        self.assertIn('"plan_sha256": plan_hash', visuals)


if __name__ == "__main__":
    unittest.main()
