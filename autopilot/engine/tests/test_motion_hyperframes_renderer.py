"""Tests for the optional full-track Motion + HyperFrames route."""
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
            "scenes": [
                {"caption": "The melody begins"},
                {"caption": "A rising phrase"},
                {"caption": "The final note"},
                {"caption": "Not included"},
            ],
        })
        self.assertEqual(result["title"], "A Song for the Quiet Hours")
        self.assertEqual(result["topic"], "Violin Cover")
        self.assertEqual(len(result["captions"]), 3)
        self.assertEqual(result["captions"][2], "The final note")

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
