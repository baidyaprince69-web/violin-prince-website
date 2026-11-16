"""Tests for 2D-only visual-reference direction."""
import sys
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from visual_reference import (
    normalize_visual_reference,
    scene_camera_move,
    scene_transition,
    scene_visual_prompt_suffix,
    transition_duration,
    validate_visual_reference,
)


def scenes():
    return [
        {"visual_mode": "macro_illustration"},
        {"visual_mode": "mechanism_diagram"},
        {"visual_mode": "waveform"},
        {"visual_mode": "melody_map"},
        {"visual_mode": "cover_performance"},
    ]


class VisualReferenceTests(unittest.TestCase):
    def test_missing_reference_keeps_safe_2d_defaults(self):
        self.assertIsNone(normalize_visual_reference(None, scenes()))
        self.assertEqual(scene_camera_move({}, 0), "locked")
        self.assertEqual(scene_transition({}, 0), "fade")
        self.assertAlmostEqual(transition_duration({}), 0.35)
        self.assertEqual(scene_visual_prompt_suffix({}, 0), "")

    def test_normalizes_five_scene_2d_choreography(self):
        profile = normalize_visual_reference(
            {
                "source_url": "https://www.youtube.com/shorts/example",
                "reference_summary": "Layered 2D illustrations, fast graphic transitions and clear typography.",
                "motion_profile": "portrait_narration_driven_2d",
                "visual_language": "illustrated_2d",
                "pacing": "dynamic",
                "scene_guidance": [
                    {"shot_type": "extreme_macro", "camera_move": "pan_left", "transition_out": "wipe_left"},
                    {"shot_type": "mechanism_cutaway", "camera_move": "pan_up", "transition_out": "smooth_left"},
                    {"shot_type": "close_detail", "camera_move": "pan_right", "transition_out": "wipe_right"},
                    {"shot_type": "overhead", "camera_move": "pan_down", "transition_out": "crossfade"},
                    {"shot_type": "performance_close", "camera_move": "locked", "transition_out": "fade_through_black"},
                ],
            },
            scenes(),
        )
        plan = {"visual_reference": profile}
        self.assertEqual(profile["visual_language"], "illustrated_2d")
        self.assertEqual(len(profile["scene_guidance"]), 5)
        self.assertIn("original full-screen portrait SVG scenes", profile["adaptation_note"])
        self.assertIn("No 3D renderer", profile["adaptation_note"])
        self.assertEqual(scene_camera_move(plan, 0), "pan_left")
        self.assertEqual(scene_camera_move(plan, 1), "pan_up")
        self.assertEqual(scene_transition(plan, 0), "wipeleft")
        self.assertEqual(scene_transition(plan, 1), "smoothleft")
        self.assertAlmostEqual(transition_duration(plan), 0.27)
        suffix = scene_visual_prompt_suffix(plan, 0)
        self.assertIn("Reference-informed treatment", suffix)
        self.assertIn("Extreme macro framing", suffix)
        self.assertIn("do not reproduce exact frames", suffix)

    def test_default_shots_follow_2d_scene_modes(self):
        profile = normalize_visual_reference({"visual_language": "kinetic_graphics"}, scenes())
        self.assertEqual(
            [item["shot_type"] for item in profile["scene_guidance"]],
            ["extreme_macro", "mechanism_cutaway", "close_detail", "overhead", "performance_close"],
        )
        self.assertTrue(all(item["camera_move"] == "locked" for item in profile["scene_guidance"]))
        self.assertTrue(all(item["transition_out"] == "crossfade" for item in profile["scene_guidance"]))

    def test_video_reference_is_adapted_not_recreated(self):
        profile = normalize_visual_reference({"motion_profile": "video_clips"}, scenes())
        self.assertIn("original 2D Motion graphics", profile["adaptation_note"])
        self.assertIn("not copied or recreated", profile["adaptation_note"])

    def test_rejects_non_https_reference_urls(self):
        issues = validate_visual_reference({"source_url": "javascript:alert(1)"}, scenes())
        self.assertTrue(issues)
        self.assertIn("safe HTTPS", issues[0])

    def test_rejects_unknown_visual_controls(self):
        issues = validate_visual_reference(
            {"pacing": "hyperfast", "scene_guidance": [{}, {}, {}, {}, {}]},
            scenes(),
        )
        self.assertTrue(issues)
        self.assertIn("pacing", issues[0])

    def test_rejects_incomplete_scene_guidance(self):
        issues = validate_visual_reference(
            {"scene_guidance": [{"shot_type": "macro"}]},
            scenes(),
        )
        self.assertTrue(issues)
        self.assertIn("exactly 5", issues[0])

    def test_no_3d_visual_languages_or_scene_modes_are_exposed(self):
        from visual_reference import VISUAL_LANGUAGES, _DEFAULT_SHOT_BY_MODE
        self.assertTrue(all("3d" not in value.casefold() for value in VISUAL_LANGUAGES))
        self.assertTrue(all("3d" not in value.casefold() for value in _DEFAULT_SHOT_BY_MODE))
        self.assertIn("illustrated_2d", VISUAL_LANGUAGES)
        self.assertIn("macro_illustration", _DEFAULT_SHOT_BY_MODE)


if __name__ == "__main__":
    unittest.main()
