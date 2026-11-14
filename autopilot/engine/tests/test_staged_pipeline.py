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
            "title": "How a violin string creates sound",
            "topic": "The physical vibration of a violin string",
            "story_type": "violin_physics",
            "cover_payoff": "An original violin phrase will let listeners hear the string vibration becoming a resonant musical note.",
            "narration_script": "A short test narration.",
            "sources": [
                {
                    "source_id": "S0001",
                    "article_page_verified": True,
                    "publisher_name": "Publisher One",
                    "publisher_domain": "publisher-one.example",
                    "title": "Source one article",
                    "url": "https://publisher-one.example/articles/source-one",
                    "link_type": "publisher_article",
                },
                {
                    "source_id": "S0002",
                    "article_page_verified": True,
                    "publisher_name": "Publisher Two",
                    "publisher_domain": "publisher-two.example",
                    "title": "Source two article",
                    "url": "https://publisher-two.example/articles/source-two",
                    "link_type": "publisher_article",
                },
            ],
            "source_group": {
                "group_id": "STORY_TEST",
                "source_ids": ["S0001", "S0002"],
                "verified_source_ids": ["S0001", "S0002"],
            },
            "quality_control": {
                "status": "passed",
                "verified_source_count": 2,
                "date_check": {"status": "passed"},
                "freshness": {
                    "status": "passed",
                    "maximum_age_hours": 168,
                    "verified_sources": [
                        {"source_id": "S0001", "freshness_status": "preferred", "age_hours": 12},
                        {"source_id": "S0002", "freshness_status": "acceptable", "age_hours": 121},
                    ],
                },
            },
            "scenes": [
                {"caption": "The opening scene", "image_prompt": "A macro view of a violin string", "visual_mode": "macro_3d"},
                {"caption": "The middle detail", "image_prompt": "A waveform showing vibration", "visual_mode": "waveform"},
                {"caption": "The final reveal", "image_prompt": "A violin performance close-up", "visual_mode": "cover_performance"},
            ],
        }
        metadata = {
            "schema_version": 1,
            "narration_info": {
                "subtitle_cues": [{"start": 0.0, "end": 1.0, "text": "A short test narration."}]
            },
            "story_review": {
                "status": "approved",
                "approved": True,
                "approved_at": "2026-11-14T00:00:00+00:00",
                "approval_method": "test",
            },
        }
        (folder / "creative_plan.json").write_text(json.dumps(plan), encoding="utf-8")
        (folder / "stage.json").write_text(json.dumps(metadata), encoding="utf-8")
        (folder / "quality_control.json").write_text(
            json.dumps({
                "status": "passed",
                "verified_source_count": 2,
                "date_check": {"status": "passed"},
                "freshness": {
                    "status": "passed",
                    "maximum_age_hours": 168,
                    "verified_sources": [
                        {"source_id": "S0001", "freshness_status": "preferred", "age_hours": 12},
                        {"source_id": "S0002", "freshness_status": "acceptable", "age_hours": 121},
                    ],
                },
            }), encoding="utf-8"
        )
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

    def test_previous_run_research_is_loaded_without_new_feed_requests(self):
        with tempfile.TemporaryDirectory() as folder:
            original = pipeline.WORK
            try:
                pipeline.WORK = Path(folder) / "work"
                reuse = pipeline.WORK / "reuse"
                reuse.mkdir(parents=True)
                research = [
                    {
                        "title": f"Headline {index}",
                        "url": f"https://publisher{index}.example/articles/{index}",
                        "publisher_domain": f"publisher{index}.example",
                        "article_page_verified": True,
                        "article_page_kind": "article_metadata",
                        "published_at_utc": "2026-11-14T12:00:00Z",
                        "link_type": "publisher_article",
                        "evidence_text": (
                            f"This directly fetched publisher article number {index} contains "
                            "a readable paragraph with enough factual material to be retained "
                            "for source-first research and subsequent corroboration checks."
                        ),
                    }
                    for index in range(70)
                ]
                (reuse / "research.json").write_text(json.dumps(research), encoding="utf-8")
                loaded = pipeline.load_reusable_research()
                self.assertEqual(len(loaded), 70)
                self.assertTrue((pipeline.WORK / "research.json").is_file())
            finally:
                pipeline.WORK = original

    def test_lead_only_research_artifact_is_discarded_for_fresh_publisher_discovery(self):
        with tempfile.TemporaryDirectory() as folder:
            original = pipeline.WORK
            try:
                pipeline.WORK = Path(folder) / "work"
                reuse = pipeline.WORK / "reuse"
                reuse.mkdir(parents=True)
                research = [
                    {
                        "title": "A headline from a news aggregator",
                        "url": "https://news.google.com/rss/articles/example",
                        "publisher_domain": "publisher.example",
                    }
                ]
                (reuse / "research.json").write_text(json.dumps(research), encoding="utf-8")
                loaded = pipeline.load_reusable_research()
                self.assertIsNone(loaded)
                self.assertFalse((pipeline.WORK / "research.json").exists())
            finally:
                pipeline.WORK = original

    def test_research_reuse_returns_none_when_no_previous_artifact_is_given(self):
        with tempfile.TemporaryDirectory() as folder:
            original = pipeline.WORK
            try:
                pipeline.WORK = Path(folder) / "work"
                self.assertIsNone(pipeline.load_reusable_research())
            finally:
                pipeline.WORK = original

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

    def test_render_package_requires_automated_quality_gate_clearance(self):
        with tempfile.TemporaryDirectory() as folder:
            self._write_package(folder, include_images=True)
            metadata_path = Path(folder) / "stage.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["story_review"]["approved"] = False
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
            original = pipeline.PACKAGE
            try:
                pipeline.PACKAGE = Path(folder)
                with self.assertRaisesRegex(pipeline.PipelineError, "automated editorial quality gates"):
                    pipeline._read_package(require_images=True)
            finally:
                pipeline.PACKAGE = original

    def test_visual_stage_passes_automatically_after_quality_gates_without_checkbox(self):
        with tempfile.TemporaryDirectory() as folder:
            folder = Path(folder)
            self._write_package(folder, include_images=False)
            metadata_path = folder / "stage.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["story_review"] = {
                "status": "awaiting_automated_quality_gates",
                "approved": False,
                "approved_at": None,
                "approval_method": None,
            }
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

            original_package = pipeline.PACKAGE
            original_account, original_token = pipeline.CF_ACCOUNT, pipeline.CF_TOKEN
            old_approval = os.environ.get("STORY_APPROVED")
            pipeline.PACKAGE = folder
            pipeline.CF_ACCOUNT, pipeline.CF_TOKEN = "test-account", "test-ai-token"
            os.environ["STORY_APPROVED"] = "false"

            def fake_make_image(_prompt, index):
                target = folder / f"generated-{index + 1}.jpg"
                Image.new("RGB", (120, 200), (40 + index * 25, 55, 80)).save(target, "JPEG")
                return target

            try:
                with unittest.mock.patch.object(pipeline, "make_image", side_effect=fake_make_image):
                    pipeline.visuals_stage()
                updated = json.loads(metadata_path.read_text(encoding="utf-8"))
                self.assertTrue(updated["story_review"]["approved"])
                self.assertEqual(
                    updated["story_review"]["approval_method"],
                    "automated_source_date_freshness_and_channel_fit_checks",
                )
                self.assertTrue((folder / "storyboard-preview.png").is_file())
            finally:
                pipeline.PACKAGE = original_package
                pipeline.CF_ACCOUNT, pipeline.CF_TOKEN = original_account, original_token
                if old_approval is None:
                    os.environ.pop("STORY_APPROVED", None)
                else:
                    os.environ["STORY_APPROVED"] = old_approval

    def test_visual_feedback_is_added_without_changing_base_scene_prompt(self):
        scene = {"image_prompt": "A lighthouse at dawn"}
        feedback = "keep photorealistic violin imagery and add stronger foreground depth"
        prompt = pipeline._scene_visual_prompt(scene, feedback)
        self.assertIn("A lighthouse at dawn", prompt)
        self.assertIn("additional visual direction: " + feedback, prompt)
        self.assertIn("no watermark", prompt)
        self.assertIn("photorealistic cinematic still imagery", prompt)
        self.assertIn("layered foreground/midground/background", prompt)

    def test_full_mode_runs_each_stage_once_in_order(self):
        with tempfile.TemporaryDirectory() as folder:
            original_work, original_out = pipeline.WORK, pipeline.OUT
            pipeline.WORK = Path(folder) / "work"
            pipeline.OUT = pipeline.WORK / "output"
            calls = []
            try:
                with unittest.mock.patch.object(pipeline, "prepare_stage", side_effect=lambda: calls.append("prepare") or 0), \
                     unittest.mock.patch.object(pipeline, "visuals_stage", side_effect=lambda feedback="": calls.append("visuals") or 0), \
                     unittest.mock.patch.object(pipeline, "render_stage", side_effect=lambda: calls.append("render") or 0):
                    result = pipeline.main(stage="full")
                self.assertEqual(result, 0)
                self.assertEqual(calls, ["prepare", "visuals", "render"])
            finally:
                pipeline.WORK, pipeline.OUT = original_work, original_out

    def test_full_mode_stops_before_later_stages_if_prepare_fails(self):
        with tempfile.TemporaryDirectory() as folder:
            original_work, original_out = pipeline.WORK, pipeline.OUT
            pipeline.WORK = Path(folder) / "work"
            pipeline.OUT = pipeline.WORK / "output"
            calls = []
            try:
                with unittest.mock.patch.object(pipeline, "prepare_stage", side_effect=lambda: calls.append("prepare") or 1), \
                     unittest.mock.patch.object(pipeline, "visuals_stage", side_effect=lambda feedback="": calls.append("visuals") or 0), \
                     unittest.mock.patch.object(pipeline, "render_stage", side_effect=lambda: calls.append("render") or 0):
                    result = pipeline.main(stage="full")
                self.assertEqual(result, 1)
                self.assertEqual(calls, ["prepare"])
            finally:
                pipeline.WORK, pipeline.OUT = original_work, original_out


if __name__ == "__main__":
    unittest.main()
