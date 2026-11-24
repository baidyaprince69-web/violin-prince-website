from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from animation_production_gate import (
    AnimationProductionGateError,
    animation_production_blockers,
    require_approved_animation_production,
)


def valid_approval() -> dict:
    return {
        "schema_version": 1,
        "status": "approved",
        "mode": "animation_only",
        "provider": "test_video_provider",
        "renderer": "master_director_video",
        "static_image_fallback_allowed": False,
        "test_evidence": {
            "workflow_run_id": 123456,
            "workflow_status": "success",
            "director_shot_count": 8,
            "generated_video_asset_count": 8,
            "downloaded_video_asset_count": 8,
            "all_shots_have_video_assets": True,
            "actual_motion_verified": True,
            "static_image_only_shot_count": 0,
            "motion_coverage": 0.85,
            "final_video_verified": True,
        },
        "creator_review": {"approved": True},
    }


class AnimationProductionGateTests(unittest.TestCase):
    def test_missing_approval_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "animation-production-approval.json"
            blockers = animation_production_blockers(missing)
        self.assertTrue(blockers)
        self.assertIn("Animation-only production is locked", blockers[0])

    def test_complete_genuine_animation_evidence_passes(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "animation-production-approval.json"
            path.write_text(json.dumps(valid_approval()), encoding="utf-8")
            result = require_approved_animation_production(path)
        self.assertEqual(result["mode"], "animation_only")

    def test_still_image_fallback_is_rejected(self):
        approval = valid_approval()
        approval["static_image_fallback_allowed"] = True
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "animation-production-approval.json"
            path.write_text(json.dumps(approval), encoding="utf-8")
            blockers = animation_production_blockers(path)
        self.assertTrue(any("Static-image fallback" in item for item in blockers))

    def test_missing_downloaded_shot_blocks_approval(self):
        approval = valid_approval()
        approval["test_evidence"]["downloaded_video_asset_count"] = 7
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "animation-production-approval.json"
            path.write_text(json.dumps(approval), encoding="utf-8")
            with self.assertRaises(AnimationProductionGateError):
                require_approved_animation_production(path)

    def test_complete_procedural_motion_evidence_passes_without_generated_video_assets(self):
        approval = valid_approval()
        approval["production_pipeline"] = "procedural_2d"
        evidence = approval["test_evidence"]
        evidence.pop("generated_video_asset_count")
        evidence.pop("downloaded_video_asset_count")
        evidence.pop("all_shots_have_video_assets")
        evidence.update({
            "render_mode": "procedural_2d",
            "rendered_shot_count": 8,
            "animated_stagecraft_scene_count": 8,
            "animated_stagecraft_object_count": 24,
            "animated_presenter_count": 6,
            "rendered_layer_count": 0,
        })
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "animation-production-approval.json"
            path.write_text(json.dumps(approval), encoding="utf-8")
            result = require_approved_animation_production(path)
        self.assertEqual(result["production_pipeline"], "procedural_2d")

    def test_procedural_static_layers_are_rejected(self):
        approval = valid_approval()
        approval["production_pipeline"] = "procedural_2d"
        evidence = approval["test_evidence"]
        for field in ("generated_video_asset_count", "downloaded_video_asset_count", "all_shots_have_video_assets"):
            evidence.pop(field, None)
        evidence.update({
            "render_mode": "procedural_2d",
            "rendered_shot_count": 8,
            "animated_stagecraft_scene_count": 8,
            "animated_stagecraft_object_count": 24,
            "animated_presenter_count": 6,
            "rendered_layer_count": 1,
        })
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "animation-production-approval.json"
            path.write_text(json.dumps(approval), encoding="utf-8")
            blockers = animation_production_blockers(path)
        self.assertTrue(any("zero generated still-image layers" in item for item in blockers))

    def test_legacy_daily_runner_stops_before_voice_or_image_work(self):
        from unittest.mock import patch

        import run_daily_plan as daily

        with patch.object(daily, "require_approved_own_voice") as own_voice:
            with self.assertRaisesRegex(daily.engine.PipelineError, "Genuine-animation production blocked"):
                daily.run_daily_plan(Path("missing-plan.json"))
            own_voice.assert_not_called()

    def test_low_motion_coverage_is_rejected(self):
        approval = valid_approval()
        approval["test_evidence"]["motion_coverage"] = 0.20
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "animation-production-approval.json"
            path.write_text(json.dumps(approval), encoding="utf-8")
            blockers = animation_production_blockers(path)
        self.assertTrue(any("75 percent" in item for item in blockers))


if __name__ == "__main__":
    unittest.main()
