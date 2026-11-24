"""Regression coverage for pose selection in the daily presenter composition."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

from character_daily_integration_test import build_daily_portrait_project


class DailyPresenterPoseSelectionTests(unittest.TestCase):
    def test_daily_portrait_project_routes_each_requested_pose_to_motion(self):
        bundle_dir = ENGINE_DIR / "assets" / "characters" / "violin-prince-rig"
        expected = [
            "resting_hands",
            "one_arm_raised",
            "explaining_two_hands",
            "point_left",
            "point_right",
            "open_palms",
            "resting_hands",
        ]

        with tempfile.TemporaryDirectory() as temporary:
            project_path = build_daily_portrait_project(bundle_dir, temporary)
            project = json.loads(project_path.read_text(encoding="utf-8"))

        self.assertEqual(len(project["scenes"]), len(expected) + 1)
        character = next(
            item for item in project["characters"]
            if item.get("id") == "violin-prince"
        )
        available_poses = set(character.get("pose_assets") or {})

        for scene, expected_pose in zip(project["scenes"][:len(expected)], expected, strict=True):
            with self.subTest(scene=scene["id"]):
                action = scene["character_actions"]["violin-prince"]
                self.assertTrue(action["visible"])
                self.assertEqual(action["pose_asset"], expected_pose)
                self.assertIn(action["pose_asset"], available_poses)
                self.assertNotIn("presenter_pose", scene)

        performance = project["scenes"][-1]
        self.assertEqual(performance["id"], "scene-procedural-performance")
        self.assertEqual(performance["stagecraft"]["environment"], "concert_stage")
        self.assertEqual(len(performance["stagecraft"]["objects"]), 4)
        self.assertEqual(performance["director_camera"]["movement"], "dolly_in")
        action = performance["character_actions"]["violin-prince"]
        self.assertTrue(action["visible"])
        self.assertEqual(action["gesture"], "dance_groove")
        self.assertTrue(action["loop"])
        self.assertEqual(action["root_motion"]["type"], "sway")
        self.assertNotIn("pose_asset", action)


if __name__ == "__main__":
    unittest.main()
