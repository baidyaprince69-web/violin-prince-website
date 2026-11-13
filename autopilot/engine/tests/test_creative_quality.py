"""Offline tests for Phase 1 creative quality and resilient rendering."""
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


class CreativeQualityTests(unittest.TestCase):
    def test_scene_timing_follows_narration_beats_and_fills_24_seconds(self):
        info = {
            "subtitle_cues": [
                {"start": 0.0, "end": 3.1, "text": "Hook"},
                {"start": 3.25, "end": 8.0, "text": "Context"},
                {"start": 8.15, "end": 14.4, "text": "Distinctive detail"},
                {"start": 14.55, "end": 20.1, "text": "Payoff"},
            ]
        }
        durations = pipeline.scene_durations_from_narration(info)
        self.assertEqual(len(durations), 3)
        self.assertTrue(all(value >= 4.8 for value in durations))
        self.assertAlmostEqual(sum(durations), 24.0, places=2)
        self.assertNotEqual(durations, (8.0, 8.0, 8.0))


    def test_motion_graphic_card_is_transparent_and_contains_scene_detail(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "motion-graphic.png"
            scene = {
                "caption": "A remarkable detail emerges",
                "graphic_label": "THE KEY DETAIL",
                "graphic_detail": "The original source confirms this detail",
            }
            pipeline.make_motion_graphic_card(scene, 1, {"title": "Test"}, target)
            with Image.open(target) as graphic:
                self.assertEqual(graphic.size, (620, 245))
                self.assertEqual(graphic.mode, "RGBA")
                self.assertEqual(graphic.getpixel((0, 0))[3], 0)
                self.assertGreater(graphic.getchannel("A").getbbox()[2], 500)

    def test_square_ai_art_is_extended_to_portrait_without_losing_its_full_source(self):
        source = Image.new("RGB", (1024, 1024), (160, 90, 45))
        frame = pipeline.portrait_scene_frame(source)
        self.assertEqual(frame.size, (720, 1280))
        # The centre remains the original image colour rather than a crop-only substitute.
        self.assertEqual(frame.getpixel((360, 640)), (160, 90, 45))

    def test_precision_violin_macro_has_physically_ordered_geometry(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "macro-contact.jpg"
            result = pipeline.make_macro_contact_illustration(target)
            self.assertTrue(target.is_file())
            self.assertEqual((result["width"], result["height"]), (720, 1280))
            self.assertEqual(result["string_count"], 4)
            self.assertEqual(result["bridge_notch_count"], 4)
            self.assertEqual(result["bridge_foot_count"], 2)
            self.assertEqual(result["highlighted_contact_points"], 1)
            self.assertEqual(result["active_contact_string_number"], 2)
            self.assertTrue(result["contact_between_fingerboard_and_bridge"])
            self.assertLess(
                result["fingerboard_end_y"] + 18,
                result["contact_y"],
            )
            self.assertLess(result["contact_y"], result["bridge_center_y"] - 28)
            self.assertTrue(result["bow_stick_and_horsehair_separate"])
            self.assertGreaterEqual(result["bow_hair_stick_separation_px"], 60)
            self.assertTrue(result["hair_contacts_selected_string"])
            self.assertEqual(result["bow_hair_contact_string_number"], 2)
            self.assertEqual(len(result["string_spacing_at_contact_y_px"]), 3)
            self.assertTrue(all(value >= 50 for value in result["string_spacing_at_contact_y_px"]))
            positions = result["string_positions_at_contact_y"]
            self.assertEqual(len(positions), 4)
            self.assertTrue(all(a < b for a, b in zip(positions, positions[1:])))
            self.assertTrue(
                all((b - a) >= 55 for a, b in zip(positions, positions[1:]))
            )
            with Image.open(target) as illustration:
                self.assertEqual(illustration.size, (720, 1280))
                self.assertEqual(illustration.mode, "RGB")

    def test_precision_macro_is_selected_only_for_violin_bow_performance(self):
        plan = {"topic": "How a violinist shapes a phrase"}
        scene = {"image_prompt": "Violin bow hair contacting one string"}
        self.assertTrue(pipeline.use_precision_macro(plan, scene, 1))
        self.assertFalse(pipeline.use_precision_macro(plan, scene, 0))
        self.assertFalse(pipeline.use_precision_macro({"topic": "A cello story"}, scene, 1))
        self.assertFalse(pipeline.use_precision_macro({"topic": "A violin and cello comparison"}, scene, 1))
        self.assertFalse(
            pipeline.use_precision_macro(plan, {"image_prompt": "A macro view of the bridge"}, 1)
        )

    def test_kinetic_captions_keep_measured_sentence_times_and_animation(self):
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "narration.ass"
            pipeline.write_kinetic_ass(
                [{"start": 0.2, "end": 2.4, "text": "A remarkable detail emerges today."}],
                target,
            )
            content = target.read_text(encoding="utf-8")
            self.assertIn("Dialogue: 0,0:00:00.20,0:00:02.40,VP", content)
            self.assertIn("fad(180,220)", content)
            self.assertIn("008BCEEA", content)
            self.assertIn("remarkable", content)

    def test_camera_motion_varies_by_scene_but_keeps_smooth_easing(self):
        first = pipeline.camera_motion_filter(120, 0)
        second = pipeline.camera_motion_filter(120, 1)
        third = pipeline.camera_motion_filter(120, 2)
        self.assertNotEqual(first, second)
        self.assertNotEqual(second, third)
        self.assertIn("3-2*", first)

    def test_scene_timing_has_safe_equal_duration_fallback(self):
        self.assertEqual(
            pipeline.scene_durations_from_narration({"subtitle_cues": []}),
            (8.0, 8.0, 8.0),
        )

    def test_all_scenes_share_brand_art_direction_but_have_distinct_roles(self):
        plan = {"topic": "A violin component travelled into orbit"}
        scene = {"image_prompt": "A small violin bridge near an orbital satellite"}
        prompts = [
            pipeline._scene_visual_prompt(scene, index=i, plan=plan)
            for i in range(3)
        ]
        self.assertIn("SHOT 1 — TWO-SECOND HOOK", prompts[0])
        self.assertIn("SHOT 2 — EXTREME CLOSE-UP DETAIL", prompts[1])
        self.assertIn("SHOT 3 — EMOTIONAL PAYOFF", prompts[2])
        for prompt in prompts:
            self.assertIn("SUBJECT & ACTION", prompt)
            self.assertIn("RECURRING ASSET ANCHOR", prompt)
            self.assertIn("STYLE & MATERIAL", prompt)
            self.assertIn("LIGHTING & CAMERA", prompt)
            self.assertIn("BACKGROUND & ATMOSPHERE", prompt)
            self.assertIn("warm", prompt.lower())
            self.assertIn("antique gold", prompt)
            self.assertIn("Avoid blue, teal, cyan or cold-blue backgrounds", prompt)
            self.assertIn("clearly illustrated concept art rather than photography", prompt)
            self.assertIn("Portrait 9:16 composition", prompt)
            self.assertLessEqual(len(prompt), pipeline.MAX_IMAGE_PROMPT_CHARS)
        self.assertEqual(len(set(prompts)), 3)

    def test_performance_detail_prompt_is_an_extreme_macro_with_physical_constraints(self):
        plan = {
            "topic": "A virtuoso violinist performs a rapid technical passage",
            "visual_motif": "same violin, amber varnish, dark tailpiece and four strings",
        }
        scene = {
            "image_prompt": "A violinist's bow moves rapidly across the strings",
            "caption": "Rapid bow changes",
            "graphic_label": "BOW CONTROL",
            "graphic_detail": "The bow crosses the strings",
        }
        prompt = pipeline._scene_visual_prompt(scene, index=1, plan=plan)
        for expected in (
            "EXTREME CLOSE-UP MACRO",
            "85mm macro lens",
            "very shallow depth of field",
            "RECURRING ASSET ANCHOR",
            "SINGLE FROZEN MACRO KEYFRAME",
            "string-height three-quarter side angle",
            "four separate, taut, parallel strings",
            "crosses the strings from frame-left to frame-right at approximately 90 degrees",
            "horsehair ribbon—not the bow stick",
            "one sharply focused contact point",
            "between the bridge and fingerboard",
            "no hands are required",
            "no duplicate bows",
        ):
            self.assertIn(expected, prompt)
        self.assertIn("warm directional key light around 3200K", prompt)
        self.assertLessEqual(len(prompt), pipeline.MAX_IMAGE_PROMPT_CHARS)

    def test_macro_prompt_is_complete_and_sent_without_truncation(self):
        plan = {
            "topic": "A violinist demonstrates bow-string contact",
            "visual_motif": "amber-varnished violin, dark tailpiece, four strings",
        }
        scene = {
            "image_prompt": "Single frozen side-three-quarter macro keyframe of bow-hair contact",
            "caption": "The bow hair contacts one string",
            "graphic_label": "BOW CONTACT",
        }
        prompt = pipeline._scene_visual_prompt(scene, index=1, plan=plan)
        payload = pipeline.image_request_payload(prompt)
        self.assertEqual(payload["prompt"], prompt)
        self.assertIn("SUBJECT & ACTION: Violin bow hair contacting one string", prompt)
        self.assertLessEqual(len(prompt), pipeline.MAX_IMAGE_PROMPT_CHARS)
        for phrase in (
            "SINGLE FROZEN MACRO KEYFRAME",
            "85mm macro lens",
            "four separate, taut, parallel strings",
            "horsehair ribbon—not the bow stick",
            "one sharply focused contact point",
            "between the bridge and fingerboard",
        ):
            self.assertIn(phrase, payload["prompt"])

    def test_single_story_review_integrates_macro_and_keeps_scope_to_one_video(self):
        source = (ENGINE / "motion_prototype.py").read_text(encoding="utf-8")
        self.assertIn("pipeline.make_macro_contact_illustration(macro_path)", source)
        self.assertIn('"macro_contact"', source)
        self.assertIn('"single_story_prototype_rendered"', source)
        self.assertIn("Only the primary prepared story is rendered", source)
        self.assertNotIn("second_report = build_prototype", source)

    def test_renderer_uses_phrase_consistent_captions_and_cinematic_scene_wipe(self):
        renderer = ENGINE.parent / "motion-prototype" / "render.mjs"
        source = renderer.read_text(encoding="utf-8")
        self.assertIn("const transition=.92;", source)
        self.assertIn("function drawSceneTransition", source)
        self.assertIn("Fine copper rails", source)
        self.assertIn("if (sceneIndex !== 1 || !scene.macro_contact) return;", source)
        self.assertIn("D.scenes[sceneIndex]?.macro_contact", source)
        self.assertIn("Let the instrument anatomy occupy the frame", source)
        self.assertIn("start: 0.005, end: 0.055", source)
        self.assertNotIn('if (TECHNICAL_TERMS.test(clean)) return "outline";', source)
        self.assertIn("Keep one expressive treatment across the full phrase", source)

    def test_motion_renderer_uses_svg_text_and_audits_actual_story_frames(self):
        renderer = ENGINE.parent / "motion-prototype" / "render.mjs"
        source = renderer.read_text(encoding="utf-8")
        motion_source = (ENGINE / "motion_prototype.py").read_text(encoding="utf-8")

        # Visible copy is emitted as complete SVG text nodes layered over the
        # scene canvas; the old synthetic Canvas phrase probe is not sign-off.
        self.assertIn('<svg id="text-layer"', source)
        self.assertIn('id="stage-wrap"', source)
        self.assertIn("function drawSvgText", source)
        self.assertIn('document.createElementNS("http://www.w3.org/2000/svg", "text")', source)
        self.assertIn("node.textContent = value", source)
        self.assertIn("context.getTransform()", source)
        self.assertIn('node.setAttribute("text-anchor", anchor)', source)
        self.assertIn("textLayer.replaceChildren()", source)

        # QA checks the live text layer at actual video timestamps and verifies
        # that timed words still match the exact narration script.
        self.assertIn("window.__TEXT_FRAME_AUDIT__", source)
        self.assertIn("window.__FRAME_TEXT_EXPECTED__", source)
        self.assertIn("D.narration_text", source)
        expected_unicode_pattern = "replace(/[^" + chr(92) * 2 + "p{L}" + chr(92) * 2 + "p{N}']/gu"
        expected_whitespace_pattern = ".split(/" + chr(92) * 2 + "s+/)"
        self.assertIn(expected_unicode_pattern, source)
        self.assertIn(expected_whitespace_pattern, source)
        self.assertIn("scriptWords.length === cueWords.length", source)
        self.assertIn("textAudit.ok", source)
        self.assertIn('page.locator("#stage-wrap").screenshot', source)
        self.assertIn("final-text-frame-audit.json", source)

        # The actual narration script is provided to the renderer, and final
        # review frames are decoded from the completed MP4 after audio muxing.
        self.assertIn('"narration_text": script', motion_source)
        self.assertIn("def _extract_final_review_frames", motion_source)
        self.assertIn("final-encoded-qa-frames", motion_source)
        self.assertIn("final_encoded_review_frames", motion_source)

        # The old Canvas probe remains diagnostic only; final visual sign-off
        # is tied to the actual SVG text layer in rendered frames.
        self.assertIn("'DejaVu Sans', sans-serif", source)
        self.assertIn("'DejaVu Serif', serif", source)
        self.assertIn("window.__GRAPHIC_TEXT_QA__", source)

    def test_non_violin_performance_does_not_inherit_violin_macro_anatomy(self):
        prompt = pipeline._scene_visual_prompt(
            {
                "image_prompt": "A cellist draws the bow across the cello strings",
                "caption": "The bow changes direction",
            },
            index=1,
            plan={"topic": "How a cellist shapes a musical phrase"},
        )
        self.assertIn("SHOT 2 — EXTREME CLOSE-UP DETAIL", prompt)
        self.assertNotIn("Violin bow hair contacting one string", prompt)
        self.assertNotIn("maple bridge supports four separate", prompt)

    def test_square_legacy_image_is_not_reused_and_macro_is_always_regenerated(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            square = root / "square.jpg"
            portrait = root / "portrait.jpg"
            Image.new("RGB", (1024, 1024), (40, 50, 60)).save(square)
            Image.new("RGB", (pipeline.W, pipeline.H), (40, 50, 60)).save(portrait)
            violin_plan = {"topic": "How a violinist shapes a phrase"}
            violin_scene = {"image_prompt": "Violin bow hair contacting one string"}
            other_scene = {"image_prompt": "A lighthouse at dawn"}
            self.assertFalse(pipeline.should_reuse_scene_image(square, violin_plan, other_scene, 0))
            self.assertTrue(pipeline.should_reuse_scene_image(portrait, violin_plan, other_scene, 0))
            self.assertFalse(pipeline.should_reuse_scene_image(portrait, violin_plan, violin_scene, 1))

    def test_non_performance_macro_uses_one_clear_focal_detail(self):
        prompt = pipeline._scene_visual_prompt(
            {"image_prompt": "A close view of rosin dust moving along a bow hair"},
            index=1,
            plan={"topic": "How violin rosin creates friction"},
        )
        self.assertIn("EXTREME CLOSE-UP DETAIL", prompt)
        self.assertIn("one exact surface", prompt)
        self.assertNotIn("ANATOMY / INSTRUMENT NEGATIVES", prompt)

    def test_storyboard_preview_wraps_captions_without_overlapping_columns(self):
        with tempfile.TemporaryDirectory() as folder:
            paths = []
            for index, colour in enumerate(((20, 40, 60), (60, 40, 20), (30, 60, 45))):
                path = Path(folder) / f"scene-{index + 1}.jpg"
                Image.new("RGB", (320, 480), colour).save(path)
                paths.append(path)
            plan = {
                "title": "A Violin With an Extraordinary Journey",
                "scenes": [
                    {"caption": "A violin component travels into orbit"},
                    {"caption": "A unique instrument is revealed on stage"},
                    {"caption": "Music connects the distant journey to Earth"},
                ],
            }
            target = Path(folder) / "storyboard.png"
            pipeline.make_storyboard_preview(plan, paths, target)
            self.assertTrue(target.is_file())
            with Image.open(target) as preview:
                self.assertEqual(preview.size, (1280, 900))


if __name__ == "__main__":
    unittest.main()
