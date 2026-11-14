"""Unit tests for optional reference-informed visual direction."""
import sys
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import run as pipeline
from visual_reference import (
    normalize_visual_reference,
    scene_camera_move,
    scene_transition,
    scene_visual_prompt_suffix,
    transition_duration,
    validate_visual_reference,
)


class VisualReferenceTests(unittest.TestCase):
    def setUp(self):
        self.scenes = [
            {"visual_mode": "macro_3d"},
            {"visual_mode": "mechanism_3d"},
            {"visual_mode": "cover_performance"},
        ]

    def test_missing_reference_keeps_existing_default_path(self):
        self.assertIsNone(normalize_visual_reference(None, self.scenes))
        self.assertEqual(scene_camera_move({}, 0), "locked")
        self.assertEqual(scene_transition({}, 0), "fade")
        self.assertAlmostEqual(transition_duration({}), 0.35)
        self.assertEqual(scene_visual_prompt_suffix({}, 0), "")

    def test_normalizes_reference_style_and_scene_choreography(self):
        profile = normalize_visual_reference(
            {
                "source_url": "https://www.youtube.com/shorts/example",
                "reference_summary": "Fast macro reveals with graphic transitions.",
                "motion_profile": "animated_stills",
                "visual_language": "cinematic_cgi",
                "pacing": "dynamic",
                "scene_guidance": [
                    {
                        "shot_type": "extreme_macro",
                        "camera_move": "pan_left",
                        "transition_out": "wipe_left",
                    },
                    {
                        "shot_type": "mechanism_cutaway",
                        "camera_move": "pan_up",
                        "transition_out": "smooth_left",
                    },
                    {
                        "shot_type": "performance_close",
                        "camera_move": "locked",
                        "transition_out": "crossfade",
                    },
                ],
            },
            self.scenes,
        )
        plan = {"visual_reference": profile}

        self.assertEqual(profile["schema_version"], 1)
        self.assertEqual(profile["visual_language"], "cinematic_cgi")
        self.assertEqual(profile["motion_profile"], "animated_stills")
        self.assertEqual(scene_camera_move(plan, 0), "pan_left")
        self.assertEqual(scene_camera_move(plan, 1), "pan_up")
        self.assertEqual(scene_transition(plan, 0), "wipeleft")
        self.assertEqual(scene_transition(plan, 1), "smoothleft")
        self.assertAlmostEqual(transition_duration(plan), 0.27)

        suffix = scene_visual_prompt_suffix(plan, 0)
        self.assertIn("Reference-informed treatment", suffix)
        self.assertIn("Extreme macro framing", suffix)
        self.assertIn("do not reproduce exact frames", suffix)

    def test_scene_shot_defaults_follow_existing_visual_modes(self):
        profile = normalize_visual_reference(
            {"visual_language": "hybrid"},
            self.scenes,
        )
        guidance = profile["scene_guidance"]
        self.assertEqual(
            [item["shot_type"] for item in guidance],
            ["extreme_macro", "mechanism_cutaway", "performance_close"],
        )
        self.assertTrue(all(item["camera_move"] == "locked" for item in guidance))
        self.assertTrue(all(item["transition_out"] == "crossfade" for item in guidance))

    def test_video_clip_reference_is_honestly_adapted_not_misrepresented(self):
        profile = normalize_visual_reference(
            {"motion_profile": "video_clips"},
            self.scenes,
        )
        self.assertIn("does not generate new AI video clips", profile["adaptation_note"])
        self.assertIn("animated overlays", profile["adaptation_note"])

    def test_rejects_non_https_reference_urls(self):
        issues = validate_visual_reference(
            {"source_url": "javascript:alert(1)"},
            self.scenes,
        )
        self.assertTrue(issues)
        self.assertIn("safe HTTPS", issues[0])

    def test_rejects_unknown_visual_controls(self):
        issues = validate_visual_reference(
            {
                "pacing": "hyperfast",
                "scene_guidance": [{}, {}, {}],
            },
            self.scenes,
        )
        self.assertTrue(issues)
        self.assertIn("pacing", issues[0])

    def test_rejects_incomplete_scene_guidance(self):
        issues = validate_visual_reference(
            {"scene_guidance": [{"shot_type": "macro"}]},
            self.scenes,
        )
        self.assertTrue(issues)
        self.assertIn("exactly three", issues[0])

    def test_reference_camera_moves_are_deterministic_pans_not_zoompan(self):
        locked = pipeline.camera_motion_filter(200, 0)
        left = pipeline.camera_motion_filter(200, 0, "pan_left", 8.0)
        right = pipeline.camera_motion_filter(200, 1, "pan_right", 8.0)
        self.assertEqual(locked, f"fps={pipeline.FPS},setsar=1")
        self.assertIn("scale=792:1352", left)
        self.assertIn("crop=720:1280", left)
        self.assertIn("cos(PI*t/8.000000)", left)
        self.assertNotEqual(left, right)
        self.assertNotIn("zoompan", left)

    def test_unknown_camera_move_is_blocked(self):
        with self.assertRaisesRegex(Exception, "Unsupported reference camera move"):
            pipeline.camera_motion_filter(100, 0, "orbit", 8.0)


if __name__ == "__main__":
    unittest.main()
