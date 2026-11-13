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
            assets = []
            for index, shade in enumerate((40, 80, 120), start=1):
                image_path = folder / f"scene-{index}.jpg"
                Image.new("RGB", (720, 1280), (shade, shade, shade)).save(image_path)
                import hashlib
                assets.append({
                    "file": image_path.name,
                    "mode": "cloudflare_flux_portrait_extended",
                    "width": 720,
                    "height": 1280,
                    "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
                    "visual_review": {
                        "model": pipeline.VISION_MODEL,
                        "score": 92,
                        "passed": True,
                        "issues": [],
                        "summary": "Test fixture visually approved.",
                    },
                })
            metadata["stage"] = "visuals_ready"
            metadata["visual_review_status"] = "all_scenes_and_storyboard_passed_ai_review_human_review_still_required"
            metadata["storyboard_review"] = {"model": pipeline.VISION_MODEL, "score": 92, "passed": True, "issues": [], "summary": "Consistent test storyboard."}
            metadata["visual_assets"] = assets
            metadata["visual_modes"] = ["cloudflare_flux_portrait_extended"] * 3
            metadata["visual_review_model"] = pipeline.VISION_MODEL
            (folder / "stage.json").write_text(json.dumps(metadata), encoding="utf-8")
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
                    {"title": f"Headline {index}", "url": f"https://publisher.example/{index}",
                     "publisher_domain": "publisher.example"}
                    for index in range(70)
                ]
                (reuse / "research.json").write_text(json.dumps(research), encoding="utf-8")
                loaded = pipeline.load_reusable_research()
                self.assertEqual(len(loaded), 70)
                self.assertTrue((pipeline.WORK / "research.json").is_file())
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

    def test_visual_package_rejected_when_storyboard_continuity_did_not_pass(self):
        with tempfile.TemporaryDirectory() as folder:
            self._write_package(folder, include_images=True)
            metadata_path = Path(folder) / "stage.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["storyboard_review"]["passed"] = False
            metadata["storyboard_review"]["score"] = 54
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

            original = pipeline.PACKAGE
            try:
                pipeline.PACKAGE = Path(folder)
                with self.assertRaisesRegex(
                    pipeline.PipelineError, "storyboard has not passed AI continuity review"
                ):
                    pipeline._read_package(require_images=True)
            finally:
                pipeline.PACKAGE = original

    def test_visual_package_rejects_contradictory_storyboard_review(self):
        with tempfile.TemporaryDirectory() as folder:
            self._write_package(folder, include_images=True)
            metadata_path = Path(folder) / "stage.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            # A positive pass/score cannot override explicit continuity defects.
            metadata["storyboard_review"]["issues"] = ["same performer changes between scenes"]
            metadata["storyboard_review"]["summary"] = "All three panels look consistent."
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

            original = pipeline.PACKAGE
            try:
                pipeline.PACKAGE = Path(folder)
                with self.assertRaisesRegex(
                    pipeline.PipelineError, "storyboard has not passed AI continuity review"
                ):
                    pipeline._read_package(require_images=True)
            finally:
                pipeline.PACKAGE = original

    def test_visual_package_rejects_scene_review_with_unresolved_issues(self):
        with tempfile.TemporaryDirectory() as folder:
            self._write_package(folder, include_images=True)
            metadata_path = Path(folder) / "stage.json"
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            metadata["visual_assets"][1]["visual_review"]["issues"] = [
                "one or more required bow components are unclear"
            ]
            metadata_path.write_text(json.dumps(metadata), encoding="utf-8")

            original = pipeline.PACKAGE
            try:
                pipeline.PACKAGE = Path(folder)
                with self.assertRaisesRegex(pipeline.PipelineError, "Scene 2 has not passed AI visual review"):
                    pipeline._read_package(require_images=True)
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
        prompt = pipeline._scene_visual_prompt(scene, "use realistic photographic depth and a richer natural background")
        self.assertIn("A lighthouse at dawn", prompt)
        self.assertIn("realistic photographic depth", prompt)
        self.assertIn("no watermark", prompt)
        self.assertIn("photorealistic cinematic editorial photography", prompt)
        self.assertNotIn("premium hand-painted cinematic editorial illustration", prompt)
        self.assertIn("Layered foreground, midground and background", prompt)

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


    def test_scene_review_uses_non_streaming_answer_contract_and_parses_wrapped_json(self):
        answer = (
            'Assessment follows:\n```json\n'
            '{"score": 94, "passed": true, "issues": [], "checks": '
            '{"subject":"YES","action":"YES","instrument":"YES","composition":"YES","photorealism":"YES"}, '
            '"summary": "Clear, coherent scene."}'
            '\n```'
        )
        with tempfile.TemporaryDirectory() as folder:
            image_path = Path(folder) / "scene.jpg"
            Image.new("RGB", (720, 1280), (40, 50, 60)).save(image_path, "JPEG")
            with unittest.mock.patch.object(
                pipeline, "ai",
                return_value={"answer": answer, "response": "This field should not be preferred."}
            ) as mocked:
                review = pipeline.review_scene_image(
                    image_path,
                    {"title": "Test violin story", "topic": "Violin performance", "visual_motif": "amber violin"},
                    {"image_prompt": "A violinist playing an amber violin", "caption": "The opening phrase"},
                    0,
                )

        self.assertTrue(review["passed"])
        self.assertEqual(review["score"], 94)
        payload = mocked.call_args.args[1]
        self.assertFalse(payload["stream"])
        self.assertFalse(payload["reasoning"])
        self.assertEqual(payload["temperature"], 0)
        self.assertEqual(payload["max_tokens"], 192)

    def test_storyboard_review_requires_same_performer_and_issue_free_result(self):
        answer = (
            '{"score": 94, "passed": true, "issues": [], "checks": '
            '{"same_performer":"YES","same_violin":"YES","macro_anatomy":"YES","consistent_palette":"YES"}, '
            '"summary": "Same performer and instrument across all panels."}'
        )
        with tempfile.TemporaryDirectory() as folder:
            contact_sheet = Path(folder) / "storyboard.png"
            Image.new("RGB", (900, 500), (20, 30, 40)).save(contact_sheet, "PNG")
            with unittest.mock.patch.object(pipeline, "ai", return_value={"answer": answer}) as mocked:
                review = pipeline.review_storyboard_consistency(
                    contact_sheet,
                    {
                        "title": "How a Violinist Shapes a Phrase",
                        "topic": "Violin performance",
                        "visual_motif": "same adult male performer, white shirt, charcoal waistcoat and amber violin",
                    },
                )
        question = mocked.call_args.args[1]["question"]
        self.assertTrue(review["passed"])
        self.assertIn("SAME identifiable performer", question)
        self.assertIn("same_performer=YES", question)
        self.assertIn("same_violin=YES", question)
        self.assertIn("macro_anatomy=YES", question)

    def test_storyboard_review_uses_non_streaming_answer_contract(self):
        answer = (
            '{"score": 91, "passed": true, "issues": [], "checks": '
            '{"same_performer":"YES","same_violin":"YES","macro_anatomy":"YES","consistent_palette":"YES"}, '
            '"summary": "All three shots share a coherent visual identity."}'
        )
        with tempfile.TemporaryDirectory() as folder:
            contact_sheet = Path(folder) / "storyboard.png"
            Image.new("RGB", (900, 500), (20, 30, 40)).save(contact_sheet, "PNG")
            with unittest.mock.patch.object(pipeline, "ai", return_value={"answer": answer}) as mocked:
                review = pipeline.review_storyboard_consistency(
                    contact_sheet,
                    {"title": "Test violin story", "topic": "Violin performance", "visual_motif": "amber violin"},
                )

        self.assertTrue(review["passed"])
        self.assertEqual(review["score"], 91)
        self.assertFalse(mocked.call_args.args[1]["stream"])
        self.assertFalse(mocked.call_args.args[1]["reasoning"])

    def test_vision_checklist_requires_every_individual_visual_check(self):
        checks = [
            "bridge", "four_strings", "fingerboard", "one_bow", "bow_stick",
            "horsehair", "hair_contact", "all_in_focus",
        ]
        answer = "; ".join(f"{key}=YES" for key in checks)
        passing = pipeline._parse_vision_assessment(
            {"result": {"answer": answer}},
            required_checks=checks,
        )
        self.assertTrue(passing["passed"])
        self.assertEqual(passing["score"], pipeline.MIN_IMAGE_QA_SCORE)
        self.assertEqual(passing["assessment_mode"], "per_requirement_checklist")

        generic_pass = pipeline._parse_vision_assessment(
            {"result": {"answer": "PASS"}},
            required_checks=checks,
        )
        self.assertFalse(generic_pass["passed"])
        self.assertIn("bridge: missing verdict", generic_pass["issues"])

        missing_check = pipeline._parse_vision_assessment(
            {"result": {"answer": "; ".join(f"{key}=YES" for key in checks[:-1])}},
            required_checks=checks,
        )
        self.assertFalse(missing_check["passed"])
        self.assertIn("all_in_focus: missing verdict", missing_check["issues"])

        visible_defect = "; ".join(
            f"{key}={'NO' if key == 'hair_contact' else 'YES'}" for key in checks
        )
        rejected = pipeline._parse_vision_assessment(
            {"result": {"answer": visible_defect}},
            required_checks=checks,
        )
        self.assertFalse(rejected["passed"])
        self.assertIn("hair_contact: reviewer marked NO", rejected["issues"])

        prose = pipeline._parse_vision_assessment(
            {"result": {"answer": "Excellent, matching the prompt. No visible defects."}},
            required_checks=checks,
        )
        self.assertFalse(prose["passed"])

    def test_generic_pass_and_positive_prose_never_approve_without_checklist(self):
        for answer in ("PASS", "Excellent, matching the prompt. No visible defects."):
            review = pipeline._parse_vision_assessment({"result": {"answer": answer}})
            self.assertFalse(review["passed"])
            self.assertEqual(review["score"], 0)

    def test_vision_text_finds_answer_inside_unexpected_wrapper(self):
        response = {
            "provider_payload": {
                "model_output": {
                    "answer": "PASS",
                    "finish_reason": "stop",
                }
            },
            "usage": {"tokens": 18},
        }
        self.assertEqual(pipeline._vision_text(response), "PASS")

    def test_storyboard_repair_selects_macro_or_final_performer_scene(self):
        self.assertEqual(
            pipeline._storyboard_repair_scene_index(["bow stick is unclear", "bridge cropped"]),
            1,
        )
        self.assertEqual(
            pipeline._storyboard_repair_scene_index(["performer identity drift"]),
            2,
        )
        self.assertEqual(
            pipeline._storyboard_repair_scene_index(["inconsistent lighting direction"]),
            2,
        )

    def test_violin_macro_prompt_keeps_every_physical_detail_in_focus(self):
        prompt = pipeline._scene_visual_prompt(
            {
                "image_prompt": "A violin macro showing the bow contacting one string",
                "caption": "The bow catches each string",
            },
            index=1,
            plan={
                "title": "How a Violinist Shapes a Phrase",
                "topic": "Violin performance",
                "visual_motif": "the same amber-varnished violin and dark tailpiece",
            },
        )
        self.assertIn("exactly four separate strings", prompt)
        self.assertIn("complete upright maple bridge", prompt)
        self.assertIn("slim dark wooden stick", prompt)
        self.assertIn("narrow pale horsehair ribbon", prompt)
        self.assertIn("moderate depth of field", prompt)
        self.assertIn("simultaneously sharp", prompt)

    def test_nested_or_chunked_vision_answer_is_extracted(self):
        assessment = '{"score": 88, "passed": true, "issues": [], "summary": "Readable composition."}'
        self.assertEqual(
            pipeline._vision_text({"answer": [{"text": assessment[:25]}, {"chunk": assessment[25:]}]}),
            assessment,
        )
        parsed = pipeline._parse_vision_assessment({"answer": {"text": assessment}})
        self.assertTrue(parsed["passed"])
        self.assertEqual(parsed["score"], 88)

        wrapped = pipeline._parse_vision_assessment(
            {"result": {"answer": assessment}, "usage": {"tokens": 44}}
        )
        self.assertTrue(wrapped["passed"])
        self.assertEqual(wrapped["score"], 88)

    def test_vision_assessment_rejects_passed_response_with_any_listed_issues(self):
        review = pipeline._parse_vision_assessment({
            "result": {
                "answer": (
                    '{"score": 97, "passed": true, '
                    '"issues": ["performer identity differs between scenes"], '
                    '"summary": "The images look polished but the lead performer changed."}'
                )
            },
            "usage": {"tokens": 42},
        })
        self.assertFalse(review["passed"])
        self.assertEqual(review["score"], 97)
        self.assertIn("performer identity differs", review["issues"][0])

    def test_json_pass_is_rejected_when_a_required_check_contradicts_it(self):
        required = ["same_performer", "same_violin", "macro_anatomy", "consistent_palette"]
        answer = json.dumps({
            "score": 99,
            "passed": True,
            "issues": [],
            "checks": {
                "same_performer": "NO",
                "same_violin": "YES",
                "macro_anatomy": "YES",
                "consistent_palette": "YES",
            },
            "summary": "The same performer appears in every scene.",
        })
        review = pipeline._parse_vision_assessment(
            {"result": {"answer": answer}},
            label="storyboard continuity reviewer",
            required_checks=required,
        )
        self.assertFalse(review["passed"])
        self.assertIn("same_performer: reviewer marked NO", review["issues"])

    def test_empty_vision_response_reports_provider_field_shape(self):
        diagnostic = pipeline._parse_vision_assessment(
            {"answer": None, "reasoning": {"trace": "omitted"}, "metrics": {"tokens": 0}}
        )
        self.assertFalse(diagnostic["passed"])
        self.assertIn("answer=NoneType", diagnostic["summary"])
        self.assertIn("reasoning=dict", diagnostic["summary"])
        self.assertIn("metrics=dict", diagnostic["summary"])

    def test_malformed_vision_answer_fails_closed_with_diagnostic(self):
        review = pipeline._parse_vision_assessment(
            {"answer": "The image looks good, but I cannot format the requested data."}
        )
        self.assertFalse(review["passed"])
        self.assertEqual(review["score"], 0)
        self.assertIn("lacked structured JSON", review["issues"][0])
        self.assertIn("image looks good", review["summary"])


if __name__ == "__main__":
    unittest.main()
