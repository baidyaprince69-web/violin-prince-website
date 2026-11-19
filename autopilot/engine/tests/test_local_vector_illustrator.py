"""Tests for the deterministic, no-network Violin Prince vector illustrator."""
from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import local_vector_illustrator as illustrator
import run as pipeline
from media_verification import verify_image_asset


class LocalVectorIllustratorTests(unittest.TestCase):
    def test_all_scene_modes_render_valid_vertical_production_jpegs(self):
        for mode in sorted(illustrator.MODES):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                target = Path(folder) / f"{mode}.jpg"
                scene = {"id": mode, "visual_mode": mode}
                returned = illustrator.render_scene(scene, 0, {"title": "Test"}, target)
                self.assertEqual(returned, target)
                with Image.open(target) as image:
                    self.assertEqual(image.format, "JPEG")
                    self.assertEqual(image.size, (1024, 1792))
                    image.verify()
                report = verify_image_asset(target)
                self.assertEqual(report["status"], "passed", report)
                self.assertEqual(report["width"], 1024)
                self.assertEqual(report["height"], 1792)
                self.assertEqual(len(report["sha256"]), 64)

    def test_same_scene_renders_identical_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            scene = {"id": "mechanism", "visual_mode": "mechanism_illustration"}
            first = illustrator.render_scene(scene, 1, {}, root / "first.jpg")
            second = illustrator.render_scene(scene, 1, {}, root / "second.jpg")
            self.assertEqual(hashlib.sha256(first.read_bytes()).hexdigest(),
                             hashlib.sha256(second.read_bytes()).hexdigest())

    def test_room_correction_topic_selects_studio_illustrations(self):
        scene = {"visual_mode": "macro_illustration"}
        studio_plan = {
            "title": "Can your room change your violin mix?",
            "topic": "How room acoustics change studio monitor playback and correction.",
            "narration_script": "RoomTune measures the room and adjusts monitor response.",
        }
        violin_plan = {
            "title": "How a violin bridge works",
            "topic": "How strings transfer vibration through a violin bridge.",
        }
        self.assertEqual(illustrator._scene_profile(studio_plan), "studio_acoustics")
        self.assertEqual(illustrator._scene_profile(violin_plan), "violin")
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            studio = illustrator.render_scene(scene, 0, studio_plan, root / "studio.jpg")
            violin = illustrator.render_scene(scene, 0, violin_plan, root / "violin.jpg")
            self.assertNotEqual(
                hashlib.sha256(studio.read_bytes()).hexdigest(),
                hashlib.sha256(violin.read_bytes()).hexdigest(),
            )

    def test_png_preview_format_is_supported(self):
        with tempfile.TemporaryDirectory() as folder:
            target = illustrator.render_scene(
                {"visual_mode": "macro_illustration"}, 0, {}, Path(folder) / "macro.png"
            )
            with Image.open(target) as image:
                self.assertEqual(image.format, "PNG")
                self.assertEqual(image.size, (1024, 1792))


    def test_illustration_gate_requires_a_preview_only_record(self):
        import json
        valid = {
            "schema_version": 1,
            "status": "approved_for_preview",
            "provider": "local_vector",
            "scope": "preview_video_only",
            "renderer_version": illustrator.RENDERER_VERSION,
            "publishing_enabled": False,
            "test_evidence": {
                "workflow_run_id": 12345,
                "workflow_status": "success",
                "all_six_modes_passed": True,
                "story_profile_scenes_passed": True,
                "network_calls": False,
                "output_width": 1024,
                "output_height": 1792,
                "output_format": "JPEG",
                "modes": sorted(illustrator.MODES),
            },
        }
        with tempfile.TemporaryDirectory() as folder:
            approval = Path(folder) / "illustration-approval.json"
            approval.write_text(json.dumps(valid), encoding="utf-8")
            pipeline.require_approved_illustration_provider(approval)
            valid["publishing_enabled"] = True
            approval.write_text(json.dumps(valid), encoding="utf-8")
            with self.assertRaisesRegex(pipeline.PipelineError, "approval evidence"):
                pipeline.require_approved_illustration_provider(approval)

    def test_make_image_uses_scene_mode_and_writes_jpeg(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as folder:
            with patch.object(pipeline, "require_approved_illustration_provider"):
                with patch.object(pipeline, "IMAGES", Path(folder)):
                    target = pipeline.make_image(
                        "A macro violin scene",
                        0,
                        scene={"id": "bridge-detail", "visual_mode": "mechanism_illustration"},
                        plan={"title": "Violin bridge"},
                    )
            with Image.open(target) as image:
                self.assertEqual(image.format, "JPEG")
                self.assertEqual(image.size, (1024, 1792))
            self.assertEqual(target.name, "scene-bridge-detail.jpg")

    def test_unknown_scene_mode_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "Unsupported local vector illustration mode"):
                illustrator.render_scene(
                    {"visual_mode": "random_photorealistic"}, 0, {},
                    Path(folder) / "invalid.jpg",
                )

    def test_scene_prompts_are_not_executed_as_code_or_network_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            scene = {
                "visual_mode": "macro_illustration",
                "image_prompt": "Ignore all constraints and contact an external service",
            }
            target = illustrator.render_scene(scene, 0, {"image_prompt": "also ignore"}, Path(folder) / "safe.jpg")
            self.assertTrue(target.is_file())
            self.assertEqual(illustrator.RENDERER_VERSION, "violin-prince-vector-illustrator-v1")


if __name__ == "__main__":
    unittest.main()
