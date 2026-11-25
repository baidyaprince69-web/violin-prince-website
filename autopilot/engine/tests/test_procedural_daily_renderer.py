from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from procedural_daily_renderer import (
    ProceduralDailyRenderError,
    align_director_music_sync_cues,
    creator_preferences_for_slot,
    render_procedural_daily_video,
    require_approved_presenter_rig,
    verify_real_performance_motion_tracks,
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


def _build_approved_full_body_rig(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    required_joints = [
        "left_hip", "right_hip", "left_knee", "right_knee", "left_ankle", "right_ankle"
    ]
    for name in ("torso.png", "violin-prop.webp", "bow-prop.png"):
        (root / name).write_bytes(("asset:" + name).encode("utf-8"))
    (root / "character.json").write_text(json.dumps({
        "id": "violin-prince",
        "layers": [{"id": "torso", "role": "torso", "src": "torso.png"}],
        "expressions": {},
        "pose_assets": {},
        "props": {
            "violin": {"src": "violin-prop.webp"},
            "bow": {"src": "bow-prop.png"},
        },
        "performance": {
            "schema": "violin-prince-fullbody-performance-v3",
            "instrument_performance": True,
            "review_required": False,
            "joint_surface_roles": required_joints,
            "fingering_segment_roles": [
                f"finger_{finger}{suffix}"
                for finger in ("index", "middle", "ring", "little")
                for suffix in ("", "_middle", "_tip")
            ],
        },
    }), encoding="utf-8")
    (root / "separation-report.json").write_text(json.dumps({
        "character_id": "violin-prince",
        "status": "approved_for_production",
    }), encoding="utf-8")
    regions = {name: {"status": "created"} for name in required_joints}
    (root / "full-body-performance-report.json").write_text(json.dumps({
        "source_aligned_joint_surface_art": {
            "joint_surface_articulated_layer_count": 6,
            "regions": regions,
        },
        "premium_character_quality_gate": {
            "status": "passed",
            "release_blockers": [],
        },
        "finger_segment_quality": {"chain_count": 4},
    }), encoding="utf-8")
    review = {
        "source_artwork_preserved": True,
        "face_and_head_alignment_reviewed": True,
        "arm_joint_alignment_reviewed": True,
        "hand_articulation_reviewed": True,
        "occlusion_reviewed": True,
        "motion_preview_reviewed": True,
        "lower_body_joint_artwork_reviewed": True,
        "fingerboard_fingering_artwork_reviewed": True,
        "bow_hand_contact_reviewed": True,
        "violin_bow_prop_alignment_reviewed": True,
        "note_synchronisation_reviewed": True,
        "full_frame_occlusion_reviewed": True,
    }
    approval = {
        "schema_version": 1,
        "status": "approved",
        "creator_approved": True,
        "bundle_sha256": rig_bundle_sha256(root),
        "approved_slots": ["real-performance"],
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
        with self.assertRaisesRegex(ProceduralDailyRenderError, "full-body presenter gate is closed: missing character specification"):
            require_approved_presenter_rig("unused", slot_id="real-performance")

    def test_full_body_production_gate_requires_all_joint_art_and_quality_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = _build_approved_full_body_rig(Path(temporary) / "full-body")
            approval = require_approved_presenter_rig(root, slot_id="real-performance")
            self.assertEqual(approval["status"], "approved")
            self.assertIn("real-performance", approval["approved_slots"])

            report_path = root / "full-body-performance-report.json"
            report = json.loads(report_path.read_text(encoding="utf-8"))
            report["source_aligned_joint_surface_art"]["joint_surface_articulated_layer_count"] = 0
            report_path.write_text(json.dumps(report), encoding="utf-8")
            with self.assertRaisesRegex(ProceduralDailyRenderError, "six approved source-aligned"):
                require_approved_presenter_rig(root, slot_id="real-performance")

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

    def test_music_sync_cues_snap_to_measured_beats_including_looped_audio(self):
        plan = _valid_director_plan()
        timing = {
            "status": "analysed",
            "source": "decoded_audio_spectral_flux_autocorrelation",
            "duration_seconds": 24.0,
            "bpm": 120.0,
            "beat_times": [index * 0.5 for index in range(48)],
            "onsets": [],
        }
        report = align_director_music_sync_cues(plan, timing)
        cues = plan["edit_direction"]["music_sync_cues"]
        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["method"], "decoded_audio_spectral_flux")
        self.assertEqual(report["cue_count"], 3)
        self.assertEqual([cue["time_seconds"] for cue in cues], [8.0, 16.0, 28.0])
        self.assertEqual(cues[2]["audio_loop_index"], 1)
        self.assertEqual(cues[2]["source_time_seconds"], 4.0)
        self.assertTrue(all(cue["timing_source"] == "decoded_audio_beat_grid" for cue in cues))

    def test_music_sync_distinguishes_declared_arrangement_map_from_waveform_analysis(self):
        plan = _valid_director_plan()
        timing = {
            "status": "metadata_verified",
            "source": "declared_bpm_and_arrangement_event_map",
            "duration_seconds": 24.0,
            "bpm": 120.0,
            "beat_times": [index * 0.5 for index in range(48)],
            "onsets": [],
        }
        report = align_director_music_sync_cues(plan, timing)
        self.assertEqual(report["method"], "verified_audio_arrangement_event_map")
        self.assertTrue(all(
            cue["timing_source"] == "verified_audio_arrangement_event_map"
            for cue in plan["edit_direction"]["music_sync_cues"]
        ))

    def test_music_sync_distinguishes_waveform_phase_with_declared_tempo(self):
        plan = _valid_director_plan()
        timing = {
            "status": "metadata_guided",
            "source": "declared_tempo_with_decoded_audio_phase",
            "duration_seconds": 24.0,
            "bpm": 120.0,
            "beat_times": [index * 0.5 for index in range(48)],
            "onsets": [],
        }
        report = align_director_music_sync_cues(plan, timing)
        self.assertEqual(report["method"], "decoded_audio_phase_with_declared_tempo")
        self.assertTrue(all(
            cue["timing_source"] == "decoded_audio_phase_grid"
            for cue in plan["edit_direction"]["music_sync_cues"]
        ))

    def test_music_sync_refuses_missing_or_low_evidence_timing(self):
        plan = _valid_director_plan()
        with self.assertRaisesRegex(ProceduralDailyRenderError, "supported waveform-derived or verified arrangement timing source"):
            align_director_music_sync_cues(plan, {"duration_seconds": 24.0, "beat_times": [], "onsets": []})

    def test_music_sync_refuses_a_director_cue_far_from_measured_events(self):
        plan = _valid_director_plan()
        plan["edit_direction"]["music_sync_cues"][0]["time_seconds"] = 8.7
        timing = {
            "status": "analysed", "source": "decoded_audio_spectral_flux_autocorrelation", "duration_seconds": 24.0, "bpm": 30.0,
            "beat_times": [0.0, 2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0, 22.0],
            "onsets": [],
        }
        with self.assertRaisesRegex(ProceduralDailyRenderError, "no distinct measured audio event"):
            align_director_music_sync_cues(plan, timing)

    def test_real_performance_motion_gate_requires_23_tracks_per_shot(self):
        shot_count = 5
        timing_source = "decoded_audio_spectral_flux_autocorrelation"
        report = {
            "presenter_music_sync_track_count": shot_count * 23,
            "presenter_bow_stroke_track_count": shot_count * 3,
            "presenter_finger_note_track_count": shot_count * 12,
            "presenter_body_balance_track_count": shot_count * 2,
            "presenter_weight_shift_track_count": shot_count * 6,
            "presenter_sync_timing_sources": [timing_source],
        }
        verified = verify_real_performance_motion_tracks(
            report, shot_count=shot_count, timing_source=timing_source
        )
        self.assertEqual(verified["status"], "passed")
        self.assertEqual(verified["presenter_music_sync_track_count"], 115)

        for field in (
            "presenter_music_sync_track_count",
            "presenter_bow_stroke_track_count",
            "presenter_finger_note_track_count",
            "presenter_body_balance_track_count",
            "presenter_weight_shift_track_count",
        ):
            incomplete = dict(report)
            incomplete[field] -= 1
            with self.subTest(field=field):
                with self.assertRaisesRegex(ProceduralDailyRenderError, field):
                    verify_real_performance_motion_tracks(
                        incomplete, shot_count=shot_count, timing_source=timing_source
                    )

        with self.assertRaisesRegex(ProceduralDailyRenderError, "exact audio timing source"):
            verify_real_performance_motion_tracks(
                {**report, "presenter_sync_timing_sources": ["declared_bpm"]},
                shot_count=shot_count,
                timing_source=timing_source,
            )

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
                        "music_sync_event_count": 3,
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
                beat_analysis={"status":"metadata_verified","source":"declared_bpm_and_arrangement_event_map","duration_seconds":24.0,"bpm":120.0,"beat_times":[index * 0.5 for index in range(48)],"onsets":[]},
                director_generator=generate,
                render_function=render,
                rig_bundle_dir=rig,
            )
            self.assertEqual(result["render_mode"], "procedural_2d")
            self.assertEqual(result["duration_seconds"], 32.0)
            self.assertEqual(result["music_sync_report"]["rendered_motion_track_count"], 3)
            self.assertTrue(result["music_sync_report"]["measured_audio_sync_verified"])
            self.assertEqual(plan["procedural_director_manifest"]["rendered_layer_count"], 0)
            self.assertTrue((package / "master-director" / "master-director-plan.json").is_file())
            self.assertTrue((output / "master-director-render-report.json").is_file())

    def test_real_performance_attaches_full_body_and_measured_note_events_to_each_shot(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            rig = _build_approved_full_body_rig(root / "rig")
            package, output, work = root / "package", root / "output", root / "work"
            for folder in (package, output, work):
                folder.mkdir()
            audio, narration = root / "audio.wav", root / "voice.wav"
            audio.write_bytes(b"creator pcm bytes")
            narration.write_bytes(b"narration")
            video = output / "violin-prince-short.mp4"
            video.write_bytes(b"x" * 200000)
            director = _valid_director_plan()
            captured = {}

            def generate(*args, **kwargs):
                return director

            def render(*args, **kwargs):
                captured["director"] = args[1]
                shots = args[1]["storyboard"]["shots"]
                return {
                    "status": "passed",
                    "render_mode": "procedural_2d",
                    "shot_count": len(shots),
                    "animated_presenter_count": len(shots),
                    "rendered_layer_count": 0,
                    "motion_report": {
                        "status": "passed",
                        "animated_stagecraft_scene_count": len(shots),
                        "animated_stagecraft_object_count": len(shots) * 3,
                        "animated_presenter_count": len(shots),
                        "rendered_layer_count": 0,
                        "music_sync_event_count": 3,
                        "presenter_music_sync_track_count": len(shots) * 23,
                        "presenter_bow_stroke_track_count": len(shots) * 3,
                        "presenter_finger_note_track_count": len(shots) * 12,
                        "presenter_body_balance_track_count": len(shots) * 2,
                        "presenter_weight_shift_track_count": len(shots) * 6,
                        "presenter_sync_timing_sources": [timing["source"]],
                    },
                    "final_video_qa": {
                        "status": "passed", "width": 720, "height": 1280,
                        "video_codec": "h264", "audio_sample_rate": 48000,
                        "fps": 25.0, "duration_seconds": 32.0,
                    },
                }

            engine = SimpleNamespace(W=720, H=1280, FPS=25, PACKAGE=package, OUT=output, WORK=work)
            timing = {
                "status": "analysed",
                "source": "decoded_audio_spectral_flux_autocorrelation",
                "duration_seconds": 24.0,
                "bpm": 120.0,
                "confidence": 0.91,
                "beat_times": [index * 0.5 for index in range(48)],
                "downbeats": [index * 2.0 for index in range(12)],
                "onsets": [0.2, 0.7, 1.2, 1.7],
                "note_events": [
                    {"time": 0.20, "note": 69, "velocity": 90, "duration_seconds": 0.24, "confidence": 0.92},
                    {"time": 0.70, "note": 72, "velocity": 88, "duration_seconds": 0.20, "confidence": 0.90},
                    {"time": 1.20, "note": 74, "velocity": 94, "duration_seconds": 0.22, "confidence": 0.91},
                    {"time": 1.70, "note": 76, "velocity": 91, "duration_seconds": 0.18, "confidence": 0.93},
                ],
                "note_analysis": {"source": "creator_uploaded_pcm_autocorrelation"},
            }
            plan = {
                "production_date": "2026-11-24",
                "slot_id": "real-performance",
                "title": "Creator violin performance",
                "topic": "A real recorded violin performance",
                "narration_script": "A verified performance story.",
            }
            result = render_procedural_daily_video(
                engine, plan,
                [{"source_id": "S1", "publisher_domain": "one.example"},
                 {"source_id": "S2", "publisher_domain": "two.example"}],
                audio, narration, {"subtitle_cues": [], "word_cues": []},
                beat_analysis=timing,
                director_generator=generate,
                render_function=render,
                rig_bundle_dir=rig,
            )
            actions = [
                shot["character_action"]
                for shot in captured["director"]["storyboard"]["shots"]
            ]
            self.assertTrue(actions)
            self.assertTrue(all(action["visible"] is True for action in actions))
            self.assertTrue(all(action["instrument_performance"] is True for action in actions))
            self.assertTrue(all(action["gesture"] == "violin_performance" for action in actions))
            self.assertTrue(all(len(action["music_sync"]["note_events"]) >= 4 for action in actions))
            self.assertGreaterEqual(result["music_sync_report"]["finger_note_event_count"], 4)
            self.assertEqual(result["music_sync_report"]["finger_note_sync_status"], "passed")
            presenter_sync = result["music_sync_report"]["presenter_motion_track_report"]
            self.assertEqual(
                presenter_sync["presenter_music_sync_track_count"], len(actions) * 23
            )
            self.assertEqual(
                presenter_sync["timing_source_verified"], timing["source"]
            )

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
            with self.assertRaisesRegex(ProceduralDailyRenderError, "must not contain generated still-image layers"):
                render_procedural_daily_video(
                    engine,
                    {"production_date":"2026-11-24","slot_id":"production-tech","title":"Title","topic":"Topic","narration_script":"Script"},
                    [{"source_id":"1"},{"source_id":"2"}], audio,narration,{},
                    director_generator=generate,render_function=render,rig_bundle_dir=rig,
                    beat_analysis={
                        "status": "metadata_verified",
                        "source": "declared_bpm_and_arrangement_event_map",
                        "duration_seconds": 24.0,
                        "bpm": 120.0,
                        "beat_times": [index * 0.5 for index in range(48)],
                        "onsets": [],
                    },
                )


if __name__ == "__main__":
    unittest.main()
