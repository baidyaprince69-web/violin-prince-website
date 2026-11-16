"""Tests for the full-track 2D Motion + HyperFrames route."""
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from motion_hyperframes_renderer import (
    MotionHyperFramesError,
    build_content_context,
    is_motion_hyperframes_render_enabled,
    select_renderer,
    render_full_track,
)


class MotionHyperFramesRendererTests(unittest.TestCase):
    def test_motion_renderer_is_disabled_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(is_motion_hyperframes_render_enabled())

    def test_motion_renderer_flag_accepts_common_true_values(self):
        for value in ("true", "TRUE", "1", "yes", "on"):
            with self.subTest(value=value):
                self.assertTrue(is_motion_hyperframes_render_enabled(value))

    def test_motion_renderer_flag_rejects_false_and_unknown_values(self):
        for value in ("false", "0", "off", "", "enabled"):
            with self.subTest(value=value):
                self.assertFalse(is_motion_hyperframes_render_enabled(value))

    def test_default_and_blender_renderer_selection_are_unchanged(self):
        self.assertEqual(select_renderer(False, False), "standard")
        self.assertEqual(select_renderer(False, True), "blender")

    def test_motion_renderer_is_an_explicit_optional_route(self):
        self.assertEqual(select_renderer(True, False), "motion_hyperframes")

    def test_motion_and_blender_routes_cannot_be_enabled_together(self):
        with self.assertRaisesRegex(MotionHyperFramesError, "cannot both be true"):
            select_renderer(True, True)

    def test_approved_editorial_content_is_passed_to_the_composition(self):
        result = build_content_context({
            "title": "A Song for the Quiet Hours",
            "topic": "Violin Cover",
            "hook": "A familiar melody, heard in a different light.",
            "narration_script": "A concise explanation of this musical idea.",
            "scenes": [
                {
                    "caption": "The melody begins",
                    "visual_mode": "macro_3d",
                    "graphic_label": "THE QUESTION",
                    "graphic_detail": "The first important observation",
                    "graphic_data": {"type": "process_flow", "items": [{"label": "Bow", "display": "Bow"}, "Bridge moves"]},
                },
                {"caption": "A rising phrase"},
                {"caption": "The bridge", "sentence_index": 2},
                {"caption": "The next phrase", "sentence_index": 3},
                {"caption": "The final note", "sentence_index": 4},
                {"caption": "Not included", "sentence_index": 5},
            ],
        }, {
            "engine": "Kokoro-82M",
            "voice": "af_heart",
            "word_cues": [{"text": "A", "start": 0.0, "end": 0.2, "sentence_index": 0}],
        })
        self.assertEqual(result["title"], "A Song for the Quiet Hours")
        self.assertEqual(result["topic"], "Violin Cover")
        self.assertEqual(len(result["captions"]), 5)
        self.assertEqual(result["captions"][4], "The final note")
        self.assertEqual(result["scenes"][4]["sentence_index"], 4)
        self.assertEqual(result["narration_engine"], "Kokoro-82M")
        self.assertEqual(result["narration_voice"], "af_heart")
        self.assertEqual(result["narration_words"][0]["text"], "A")
        self.assertEqual(result["scenes"][0]["graphic_data"]["items"][0]["label"], "Bow")
        self.assertEqual(result["scenes"][0]["graphic_data"]["items"][1]["label"], "Bridge moves")

    def test_illustrated_2d_scene_types_are_preserved_for_svg_renderer(self):
        result = build_content_context({
            "title": "Illustrated room correction",
            "scenes": [
                {"caption": "The room", "sentence_index": 0, "visual_mode": "waveform", "graphic_data": {"type": "room_acoustics", "items": ["Monitors", "Listener"]}},
                {"caption": "The interface", "sentence_index": 1, "graphic_data": {"type": "audio_interface"}},
                {"caption": "RoomTune", "sentence_index": 2, "graphic_data": {"type": "roomtune_process"}},
                {"caption": "DSP", "sentence_index": 3, "graphic_data": {"type": "dsp_stages"}},
                {"caption": "The musical payoff", "sentence_index": 4, "visual_mode": "cover_performance", "graphic_data": {"type": "violin_performance_2d", "items": ["Illustrated violin"]}},
            ],
        })
        self.assertEqual(
            [scene["graphic_data"]["type"] for scene in result["scenes"]],
            ["room_acoustics", "audio_interface", "roomtune_process", "dsp_stages", "violin_performance_2d"],
        )

    def test_illustrated_2d_scene_types_are_preserved_for_svg_renderer(self):
        result = build_content_context({
            "title": "Illustrated room correction",
            "scenes": [
                {"caption": "The room", "visual_mode": "waveform", "graphic_data": {"type": "room_acoustics", "items": ["Monitors", "Listener"]}},
                {"caption": "The signal", "visual_mode": "waveform", "graphic_data": {"type": "signal_chain", "items": ["Measure", "Process", "Playback"]}},
                {"caption": "The musical payoff", "visual_mode": "cover_performance", "graphic_data": {"type": "violin_performance_2d", "items": ["Illustrated violin"]}},
            ],
        })
        self.assertEqual(
            [scene["graphic_data"]["type"] for scene in result["scenes"]],
            ["room_acoustics", "signal_chain", "violin_performance_2d"],
        )

    def test_renderer_refuses_instrumental_only_audio(self):
        with self.assertRaisesRegex(MotionHyperFramesError, "Kokoro narration audio is required"):
            render_full_track(
                audio_bytes=b"v" * 4096,
                audio_filename="violin.wav",
                output_path="unused.mp4",
                work_dir="unused",
            )

    def test_editorial_context_is_bounded_and_non_string_values_are_ignored(self):
        result = build_content_context({
            "title": "T" * 100,
            "topic": 123,
            "hook": "H" * 200,
            "scenes": [{"caption": "C" * 200}, {"caption": None}],
        })
        self.assertEqual(len(result["title"]), 60)
        self.assertEqual(result["topic"], "")
        self.assertEqual(len(result["hook"]), 110)
        self.assertEqual(len(result["captions"][0]), 72)
        self.assertEqual(result["captions"][1], "")


if __name__ == "__main__":
    unittest.main()
