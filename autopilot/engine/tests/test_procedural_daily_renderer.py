from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from procedural_daily_renderer import (
    ProceduralDailyRenderError,
    creator_preferences_for_slot,
    render_procedural_daily_video,
    require_approved_presenter_rig,
    rig_bundle_sha256,
)


def _build_approved_rig(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "torso.png").write_bytes(b"test-rig-asset")
    (root / "character.json").write_text(json.dumps({
        "id": "violin-prince",
        "layers": [{"src": "torso.png"}],
        "expressions": {},
        "pose_assets": {},
    }), encoding="utf-8")
    (root / "separation-report.json").write_text(json.dumps({
        "character_id": "violin-prince",
        "status": "approved_for_production",
    }), encoding="utf-8")
    review = {
        "source_artwork_preserved": True,
        "face_and_head_alignment_reviewed": True,
        "arm_joint_alignment_reviewed": True,
        "hand_articulation_reviewed": True,
        "occlusion_reviewed": True,
        "motion_preview_reviewed": True,
    }
    approval = {
        "schema_version": 1,
        "status": "approved",
        "creator_approved": True,
        "bundle_sha256": rig_bundle_sha256(root),
        "approved_slots": ["music-secrets", "production-tech", "melody-stories"],
        "review": review,
    }
    (root / "production-approval.json").write_text(json.dumps(approval), encoding="utf-8")
    return root


def _valid_director_plan() -> dict:
    fixture = Path(__file__).resolve().parent / "fixtures" / "master-director-procedural-demo.json"
    plan = json.loads(fixture.read_text(encoding="utf-8"))
    plan["_director_provider"] = {"contract_version": "violin-prince-master-director-v3"}
    return plan


class ProceduralDailyRendererTests(unittest.TestCase):
    def test_slot_preferences_preserve_one_character_but_change_direction(self):
        music = creator_preferences_for_slot("music-secrets")
        tech = creator_preferences_for_slot("production-tech")
        story = creator_preferences_for_slot("melody-stories")
        self.assertEqual(music["canonical_character"], "Violin Prince")
        self.assertEqual(tech["canonical_character"], "Violin Prince")
        self.assertEqual(story["canonical_character"], "Violin Prince")
        self.assertNotEqual(music["category_direction"], tech["category_direction"])
        self.assertNotEqual(tech["category_direction"], story["category_direction"])
        self.assertFalse(music["static_image_slideshows_allowed"])

    def test_real_performance_waits_for_the_full_body_violin_rig(self):
        with self.assertRaisesRegex(ProceduralDailyRenderError, "full-body rig"):
            require_approved_presenter_rig("unused", slot_id="real-performance")

    def test_missing_creator_rig_approval_fails_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "character.json").write_text('{"id":"violin-prince"}', encoding="utf-8")
            (root / "separation-report.json").write_text('{"character_id":"violin-prince"}', encoding="utf-8")
            with self.assertRaisesRegex(ProceduralDailyRenderError, "missing creator production approval"):
                require_approved_presenter_rig(root, slot_id="production-tech")

    def test_changed_rig_bytes_invalidate_creator_approval(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = _build_approved_rig(Path(temporary) / "rig")
            (root / "torso.png").write_bytes(b"changed-after-approval")
            with self.assertRaisesRegex(ProceduralDailyRenderError, "does not match the current source assets"):
                require_approved_presenter_rig(root, slot_id="music-secrets")

    def test_daily_renderer_uses_verified_story_sources_and_motion_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rig = _build_approved_rig(root / "rig")
            package = root / "package"
            output = root / "output"
            work = root / "work"
            package.mkdir()
            output.mkdir()
            work.mkdir()
            audio = root / "bed.wav"
            narration = root / "narration.wav"
            audio.write_bytes(b"audio")
            narration.write_bytes(b"narration")
            video = output / "violin-prince-short.mp4"
            video.write_bytes(b"x" * 200000)
            director = _valid_director_plan()

            def generate(context, *, creator_preferences=None):
                self.assertEqual(context["slot_id"], "production-tech")
                self.assertEqual(len(context["verified_sources"]), 2)
                self.assertEqual(creator_preferences["canonical_character"], "Violin Prince")
                return director

            def render(*args, **kwargs):
                self.assertEqual(args[2], [])
                self.assertEqual(kwargs["rig_bundle_dir"], rig)
                self.assertTrue(kwargs["production_mode"])
                shots = director["storyboard"]["shots"]
                qa = {
                    "status": "passed", "width": 720, "height": 1280,
                    "video_codec": "h264", "audio_sample_rate": 48000,
                    "fps": 25.0, "duration_seconds": 32.0,
                }
                return {
                    "status": "passed", "render_mode": "procedural_2d",
                    "shot_count": len(shots), "animated_presenter_count": 5,
                    "rendered_layer_count": 0,
                    "motion_report": {
                        "status": "passed", "animated_stagecraft_scene_count": len(shots),
                        "animated_stagecraft_object_count": len(shots) * 3,
                        "animated_presenter_count": 5, "rendered_layer_count": 0,
                    },
                    "final_video_qa": qa, "publish_ready": True, "output": str(video),
                }

            engine = SimpleNamespace(
                W=720, H=1280, FPS=25, PACKAGE=package, OUT=output, WORK=work
            )
            plan = {
                "production_date": "2026-11-24",
                "slot_id": "production-tech",
                "title": "Test studio story",
                "topic": "A verified studio tool",
                "narration_script": "A four sentence script.",
            }
            result = render_procedural_daily_video(
                engine, plan,
                [{"source_id": "S1", "publisher_domain": "one.example"},
                 {"source_id": "S2", "publisher_domain": "two.example"}],
                audio, narration, {"subtitle_cues": [], "word_cues": []},
                director_generator=generate,
                render_function=render,
                rig_bundle_dir=rig,
            )
            self.assertEqual(result["render_mode"], "procedural_2d")
            self.assertEqual(result["duration_seconds"], 32.0)
            self.assertEqual(plan["procedural_director_manifest"]["rendered_layer_count"], 0)
            self.assertTrue((package / "master-director" / "master-director-plan.json").is_file())
            self.assertTrue((output / "master-director-render-report.json").is_file())

    def test_daily_renderer_rejects_generated_picture_layers(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rig = _build_approved_rig(root / "rig")
            package = root / "package"
            output = root / "output"
            work = root / "work"
            for folder in (package, output, work):
                folder.mkdir()
            audio, narration = root / "audio.wav", root / "voice.wav"
            audio.write_bytes(b"audio")
            narration.write_bytes(b"narration")
            director = _valid_director_plan()
            def generate(*args, **kwargs):
                return director
            def render(*args, **kwargs):
                return {
                    "status": "passed", "render_mode": "procedural_2d", "shot_count": 8,
                    "motion_report": {"status": "passed", "animated_stagecraft_scene_count": 8,
                                      "animated_stagecraft_object_count": 24, "animated_presenter_count": 5,
                                      "rendered_layer_count": 1},
                    "final_video_qa": {"status": "passed"},
                }
            engine = SimpleNamespace(W=720,H=1280,FPS=25,PACKAGE=package,OUT=output,WORK=work)
            with self.assertRaisesRegex(ProceduralDailyRenderError, "zero generated still-image layers"):
                render_procedural_daily_video(
                    engine,
                    {"production_date":"2026-11-24","slot_id":"production-tech","title":"Title","topic":"Topic","narration_script":"Script"},
                    [{"source_id":"1"},{"source_id":"2"}], audio,narration,{},
                    director_generator=generate,render_function=render,rig_bundle_dir=rig
                )


if __name__ == "__main__":
    unittest.main()
