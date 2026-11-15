"""Regression tests for the researched Kokoro + Motion explainer route."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import run as pipeline
import run_daily_plan as daily


class MotionExplainerPipelineTests(unittest.TestCase):
    def test_main_cli_blocks_motion_prepare_that_would_call_legacy_workers_ai(self):
        for stage in ("prepare", "full"):
            with self.subTest(stage=stage), patch.dict(os.environ, {
                "MOTION_HYPERFRAMES_RENDER_ENABLED": "true",
                "BLENDER_RENDER_ENABLED": "false",
                "PUBLISH_ENABLED": "false",
            }), patch.object(pipeline, "prepare_stage") as prepare:
                with self.assertRaisesRegex(
                    pipeline.PipelineError, "ChatGPT-authored, source-verified plan"
                ):
                    pipeline.main(stage=stage)
                prepare.assert_not_called()

    def test_daily_plan_motion_route_uses_kokoro_and_skips_cloud_image_or_blender_paths(self):
        asset = {
            "filename": "sampled-violin-background.wav",
            "audio_source": "sampled_violin_cc0",
            "kind": "generated_sampled_instrument",
            "duration_seconds": 24.0,
            "sample_rate": 24000,
            "license": "CC0-1.0",
        }
        narration_info = {
            "engine": "Kokoro-82M",
            "voice": "af_heart",
            "duration_seconds": 18.2,
            "word_sync_status": "passed",
            "word_cues": [
                {"text": "A", "start": 0.0, "end": 0.2, "sentence_index": 0}
            ],
        }
        plan = {
            "story_type": "violin_physics",
            "topic": "How a violin produces sound",
            "title": "How a Violin Makes Sound",
            "hook": "Why does a violin sound so alive?",
            "description": "A researched explanation of the instrument.",
            "narration_script": (
                "Why does a violin sound so alive? "
                "The bow grips and releases each string. "
                "The bridge transfers vibration into the wooden body. "
                "The body and air shape the sound we hear."
            ),
            "narrative_style": "documentary",
            "cover_payoff": "A short original violin phrase demonstrates the explained mechanism.",
            "sources": [{"source_id": "S001", "url": "https://example.com/source"}],
            "scenes": [
                {
                    "caption": "The instrument",
                    "visual_mode": "macro_3d",
                    "graphic_label": "THE QUESTION",
                    "graphic_detail": "The complete violin",
                    "image_prompt": "A realistic violin on a dark studio background.",
                },
                {
                    "caption": "The bridge transfers vibration",
                    "visual_mode": "mechanism_3d",
                    "graphic_label": "THE MECHANISM",
                    "graphic_detail": "Vibration moves through the bridge",
                    "image_prompt": "A scientific violin bridge cutaway.",
                    "graphic_data": {
                        "type": "process_flow",
                        "items": ["BOW GRIPS STRING", "BRIDGE MOVES", "BODY RESONATES"],
                    },
                },
                {
                    "caption": "The sound emerges",
                    "visual_mode": "cover_performance",
                    "graphic_label": "THE PAYOFF",
                    "graphic_detail": "Hear the complete instrument",
                    "image_prompt": "A violin and bow in a performance close-up.",
                },
            ],
        }

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            old_values = {
                "WORK": pipeline.WORK,
                "OUT": pipeline.OUT,
                "PACKAGE": pipeline.PACKAGE,
                "API": pipeline.API,
                "JOB_TOKEN": pipeline.JOB_TOKEN,
            }
            pipeline.WORK = root / "work"
            pipeline.OUT = root / "work" / "output"
            pipeline.PACKAGE = root / "work" / "package"
            pipeline.API = ""
            pipeline.JOB_TOKEN = ""

            try:
                fake_audio = b"sampled violin audio fixture " * 300

                def synthesize(_script, target):
                    target = Path(target)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(b"kokoro narration wav fixture " * 300)
                    return target, narration_info

                def render():
                    pipeline.OUT.mkdir(parents=True, exist_ok=True)
                    (pipeline.OUT / "violin-prince-explainer.mp4").write_bytes(b"m" * 8192)
                    (pipeline.OUT / "metadata.json").write_text(json.dumps({
                        "render_engine": "motion_hyperframes",
                        "narration": narration_info,
                        "video_quality": {
                            "primary_audio_source": "Kokoro-82M",
                            "narration_word_sync_status": "passed",
                            "narration_word_timing_count": 1,
                            "music_bed_enabled": True,
                        },
                        "publishing_status": "rendered",
                    }), encoding="utf-8")
                    return 0

                with patch.dict(os.environ, {
                    "MOTION_HYPERFRAMES_RENDER_ENABLED": "true",
                    "BLENDER_RENDER_ENABLED": "false",
                    "PUBLISH_ENABLED": "false",
                    "MOTION_HYPERFRAMES_MUSIC_DURATION_SECONDS": "24",
                }), patch.object(daily, "validate_and_enrich_plan", return_value=(plan, [])), patch.object(
                    daily, "validate_publish_metadata", return_value={"value": {}}
                ), patch.object(daily.engine, "get_audio", return_value=(asset, fake_audio)), patch.object(
                    daily, "synthesize_voiceover", side_effect=synthesize
                ), patch.object(daily.engine, "_write_review_text"), patch.object(
                    daily.engine, "render_stage", side_effect=render
                ) as render_stage, patch.object(
                    daily.engine, "make_image",
                    side_effect=AssertionError("Motion must not invoke Cloudflare/FLUX image generation"),
                ), patch.object(
                    daily, "resolve_story_asset",
                    side_effect=AssertionError("Motion must not invoke the optional Blender asset resolver"),
                ):
                    result = daily.run_daily_plan(root / "chatgpt-plan.json")

                self.assertEqual(result, 0)
                render_stage.assert_called_once()
                paths = pipeline._package_paths()
                metadata = json.loads(paths["metadata"].read_text(encoding="utf-8"))
                prepared_plan = json.loads(paths["plan"].read_text(encoding="utf-8"))
                self.assertEqual(metadata["production_type"], "narrated_explainer")
                self.assertEqual(metadata["narration_info"]["engine"], "Kokoro-82M")
                self.assertEqual(metadata["narration_info"]["voice"], "af_heart")
                self.assertTrue(paths["narration"].is_file())
                self.assertEqual(
                    prepared_plan["scenes"][1]["graphic_data"]["items"][0],
                    "BOW GRIPS STRING",
                )
                self.assertFalse((pipeline.PACKAGE / "scene-1.jpg").exists())
                self.assertTrue((pipeline.OUT / "violin-prince-explainer.mp4").is_file())
            finally:
                pipeline.WORK = old_values["WORK"]
                pipeline.OUT = old_values["OUT"]
                pipeline.PACKAGE = old_values["PACKAGE"]
                pipeline.API = old_values["API"]
                pipeline.JOB_TOKEN = old_values["JOB_TOKEN"]

    def test_retired_instrumental_only_preparer_fails_closed(self):
        with self.assertRaisesRegex(pipeline.PipelineError, "retired"):
            pipeline.prepare_motion_music_video_stage()


if __name__ == "__main__":
    unittest.main()
