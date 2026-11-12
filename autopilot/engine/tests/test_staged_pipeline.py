"""Offline tests for the staged story/visual/render review flow."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("CF_ACCOUNT_ID", "test-account")
os.environ.setdefault("CF_AI_TOKEN", "test-ai-token")
ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from PIL import Image
import run as pipeline


class StagedPipelineTests(unittest.TestCase):
    def _write_package(self, folder, include_images=False):
        folder = Path(folder)
        folder.mkdir(parents=True, exist_ok=True)
        plan = {
            "title": "Test story",
            "topic": "A test topic",
            "narration_script": "A short test narration.",
            "scenes": [
                {"caption": "The opening scene", "image_prompt": "A lighthouse at dawn"},
                {"caption": "The middle detail", "image_prompt": "A close view of a glowing lantern"},
                {"caption": "The final reveal", "image_prompt": "A ship returning safely to shore"},
            ],
        }
        metadata = {
            "schema_version": 1,
            "narration_info": {
                "subtitle_cues": [{"start": 0.0, "end": 1.0, "text": "A short test narration."}]
            },
        }
        (folder / "creative_plan.json").write_text(json.dumps(plan), encoding="utf-8")
        (folder / "stage.json").write_text(json.dumps(metadata), encoding="utf-8")
        (folder / "soundtrack.wav").write_bytes(b"fake soundtrack")
        (folder / "narration.wav").write_bytes(b"fake narration")
        if include_images:
            for index, shade in enumerate((40, 80, 120), start=1):
                Image.new("RGB", (120, 200), (shade, shade, shade)).save(folder / f"scene-{index}.jpg")
        return plan

    def test_prepared_package_can_load_before_images_exist(self):
        with tempfile.TemporaryDirectory() as folder:
            self._write_package(folder, include_images=False)
            original = pipeline.PACKAGE
            try:
                pipeline.PACKAGE = Path(folder)
                plan, metadata, narration_info, paths, images = pipeline._read_package(require_images=False)
                self.assertEqual(len(plan["scenes"]), 3)
                self.assertEqual(len(narration_info["subtitle_cues"]), 1)
                self.assertTrue(paths["audio"].is_file())
                self.assertEqual(len(images), 3)
            finally:
                pipeline.PACKAGE = original

    def test_visual_package_requires_three_valid_images(self):
        with tempfile.TemporaryDirectory() as folder:
            self._write_package(folder, include_images=False)
            original = pipeline.PACKAGE
            try:
                pipeline.PACKAGE = Path(folder)
                with self.assertRaisesRegex(pipeline.PipelineError, "scene-1.jpg"):
                    pipeline._read_package(require_images=True)
            finally:
                pipeline.PACKAGE = original

    def test_visual_package_accepts_all_three_valid_images(self):
        with tempfile.TemporaryDirectory() as folder:
            self._write_package(folder, include_images=True)
            original = pipeline.PACKAGE
            try:
                pipeline.PACKAGE = Path(folder)
                plan, metadata, narration_info, paths, images = pipeline._read_package(require_images=True)
                self.assertTrue(all(path.is_file() for path in images))
                self.assertEqual(len(images), 3)
            finally:
                pipeline.PACKAGE = original

    def test_visual_feedback_is_added_without_changing_base_scene_prompt(self):
        scene = {"image_prompt": "A lighthouse at dawn"}
        prompt = pipeline._scene_visual_prompt(scene, "use a richer illustrated look and stronger depth")
        self.assertIn("A lighthouse at dawn", prompt)
        self.assertIn("richer illustrated look", prompt)
        self.assertIn("no watermark", prompt)
        self.assertIn("premium cinematic storybook illustration", prompt)
        self.assertIn("layered foreground", prompt)


if __name__ == "__main__":
    unittest.main()
