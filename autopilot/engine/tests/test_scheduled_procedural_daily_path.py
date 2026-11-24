from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import run_daily_plan as daily


class ScheduledProceduralDailyPathTests(unittest.TestCase):
    def test_scheduled_public_batch_uses_procedural_renderer_and_never_generates_scene_images(self):
        script = (
            "Why does a violin string move? "
            "A measured string vibrates at a repeating frequency. "
            "The bridge transfers that movement into the instrument body. "
            "The body then moves air and helps shape the sound."
        )
        script_sha = hashlib.sha256(script.encode("utf-8")).hexdigest()
        source_records = [
            {"source_id": "S001", "publisher_domain": "publisher-one.example"},
            {"source_id": "S002", "publisher_domain": "publisher-two.example"},
        ]
        plan = {
            "production_date": "2026-11-24",
            "slot_id": "production-tech",
            "title": "A verified studio demonstration",
            "topic": "How a studio processor changes a violin signal",
            "narration_script": script,
            "quality_control": {"status": "passed"},
            "publish_metadata": {"privacy_status": "public"},
        }
        audio_asset = {
            "kind": "generated_cc0",
            "bpm": 120,
            "beat_times": [index * 0.5 for index in range(48)],
            "onsets": [],
        }
        audio_bytes = b"approved decoded soundtrack bytes" * 400
        captured: dict[str, object] = {}

        class AnimationProductionGateError(RuntimeError):
            pass

        def synthesize_voice(script_value: str, destination: Path):
            destination = Path(destination)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(b"narration audio bytes" * 200)
            return destination, {
                "script_sha256": script_sha,
                "word_sync_status": "passed",
                "private_voice_run_id": "test-voice-run",
            }

        def fake_procedural_render(engine, working_plan, sources, audio_path, narration_path, narration_info, **kwargs):
            captured["procedural_plan"] = working_plan
            captured["procedural_sources"] = sources
            captured["procedural_audio"] = Path(audio_path).read_bytes()
            captured["procedural_kwargs"] = kwargs
            return {
                "status": "passed",
                "render_mode": "procedural_2d",
                "width": 720,
                "height": 1280,
                "video_codec": "h264",
                "fps": 25,
                "duration_seconds": 32,
                "audio_sample_rate": 48000,
                "shot_count": 8,
                "character_count": 1,
                "motion_report": {"status": "passed", "animated_presenter_count": 5},
                "music_sync_report": {
                    "status": "passed",
                    "motion_report_status": "passed",
                    "measured_audio_sync_verified": True,
                    "cue_count": 3,
                    "rendered_motion_track_count": 3,
                    "cues": [],
                },
            }

        def fake_handoff(output_dir, **kwargs):
            captured["handoff_kwargs"] = kwargs
            return (
                {
                    "publish_ready": True,
                    "publisher_preflight": {"status": "ready", "blockers": []},
                },
                {"assets": {"render_mode": "procedural_2d"}},
            )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            plan_path = root / "input" / "daily-plan.json"
            plan_path.parent.mkdir(parents=True)
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            workspace = root / "slot-workspace"

            audio_module = SimpleNamespace(
                analyse_audio_file=lambda *args, **kwargs: {
                    "status": "metadata_verified",
                    "duration_seconds": 24.0,
                    "bpm": 120,
                    "beat_times": [index * 0.5 for index in range(48)],
                    "onsets": [],
                }
            )
            gate_module = SimpleNamespace(
                AnimationProductionGateError=AnimationProductionGateError,
                require_approved_animation_production=lambda: None,
            )
            renderer_module = SimpleNamespace(
                ProceduralDailyRenderError=RuntimeError,
                render_procedural_daily_video=fake_procedural_render,
            )

            fake_metadata_check = {
                "value": {
                    "title": plan["title"],
                    "description": "A source-verified animated studio demonstration.",
                    "tags": ["Violin", "Audio Production", "Studio"],
                    "made_for_kids": False,
                    "privacy_status": "public",
                },
                "audience_confirmed": True,
                "warnings": [],
            }
            fake_identity = {
                "production_identity": "2026-11-24:production-tech",
                "narration_script_sha256": script_sha,
                "narration_word_count": len(script.split()),
            }

            with (
                patch.dict(sys.modules, {
                    "audio_analysis": audio_module,
                    "animation_production_gate": gate_module,
                    "procedural_daily_renderer": renderer_module,
                }),
                patch.multiple(
                    daily.engine,
                    WORK=root / "legacy-work",
                    OUT=root / "legacy-output",
                    IMAGES=root / "legacy-images",
                    PACKAGE=root / "legacy-package",
                    RUN_ID="procedural-daily-test",
                    get_audio=Mock(return_value=(audio_asset, audio_bytes)),
                    make_image=Mock(side_effect=AssertionError("scheduled procedural path must not generate scene images")),
                    _write_review_text=Mock(),
                    make_storyboard_preview=Mock(side_effect=AssertionError("scheduled procedural path must not build image storyboards")),
                ),
                patch.object(daily, "require_approved_own_voice"),
                patch.object(daily, "validate_and_enrich_plan", side_effect=lambda loaded: (loaded, source_records)),
                patch.object(daily, "build_production_identity", return_value=fake_identity),
                patch.object(daily, "validate_publish_metadata", return_value=fake_metadata_check),
                patch.object(daily, "synthesize_voiceover", side_effect=synthesize_voice),
                patch.object(daily, "write_handoff_files", side_effect=fake_handoff),
                patch.object(daily, "write_slot_receipt") as write_receipt,
                patch.object(daily, "enable_presenter_from_environment", side_effect=AssertionError("scheduled path must use the production rig gate")),
                patch.object(daily, "attach_violin_prince_presenter", side_effect=AssertionError("scheduled path must not attach legacy upper-body assets")),
                patch.object(daily, "prepare_character_assets", side_effect=AssertionError("scheduled path must use the approved procedural rig bundle")),
                patch.object(daily, "render_daily_plan", side_effect=AssertionError("scheduled path must not call the legacy image renderer")),
            ):
                result = daily.run_daily_plan(
                    plan_path,
                    workspace_root=workspace,
                    batch_snapshot_sha256="a" * 64,
                )

            self.assertEqual(result, 0)
            handoff = captured["handoff_kwargs"]
            self.assertEqual(handoff["image_paths"], [])
            self.assertEqual(handoff["plan"]["publish_metadata"]["privacy_status"], "public")
            self.assertEqual(handoff["video_quality"]["render_mode"], "procedural_2d")
            self.assertEqual(captured["procedural_plan"]["slot_id"], "production-tech")
            self.assertEqual(len(captured["procedural_sources"]), 2)
            self.assertTrue(captured["procedural_audio"])
            self.assertEqual(captured["procedural_kwargs"]["beat_analysis"]["status"], "metadata_verified")
            daily.engine.make_image.assert_not_called()
            daily.engine.make_storyboard_preview.assert_not_called()
            write_receipt.assert_called_once()
            self.assertEqual(write_receipt.call_args.kwargs["status"], "rendered_ready_for_public_youtube_upload")


if __name__ == "__main__":
    unittest.main()
