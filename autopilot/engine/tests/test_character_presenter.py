"""Regression coverage for the checked-in Violin Prince presenter bundle."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

from character_presenter import attach_violin_prince_presenter
from character_rig import validate_character_spec


class SavedPresenterBundleTests(unittest.TestCase):
    def test_checked_in_bundle_attaches_all_assets_to_an_opted_in_daily_plan(self):
        bundle_dir = ENGINE_DIR / "assets" / "characters" / "violin-prince-rig"
        self.assertTrue((bundle_dir / "character.json").is_file())
        self.assertTrue((bundle_dir / "separation-report.json").is_file())

        plan = {
            "use_violin_prince_presenter": True,
            "scenes": [
                {
                    "id": "intro",
                    "duration": 1.0,
                    "presenter_pose": "resting_hands",
                    "presenter_expression": "neutral",
                },
                {
                    "id": "explain",
                    "duration": 1.2,
                    "presenter_pose": "explaining_two_hands",
                    "presenter_expression": "speaking",
                },
            ],
        }

        with tempfile.TemporaryDirectory() as temporary:
            package_dir = Path(temporary) / "package"
            attached = attach_violin_prince_presenter(
                plan,
                package_dir=package_dir,
            )

            self.assertTrue(attached["presenter_integration"]["enabled"])
            self.assertEqual(len(attached["characters"]), 1)
            character = validate_character_spec(attached["characters"][0])
            self.assertEqual(character["id"], "violin-prince")
            self.assertEqual(len(character["layers"]), 9)
            self.assertEqual(len(character["joints"]), 7)
            self.assertEqual(len(character["expressions"]), 6)
            self.assertEqual(len(character["pose_assets"]), 6)

            for item in character["layers"]:
                self.assertTrue(Path(item["src"]).is_file(), item["src"])
            for item in character["expressions"].values():
                self.assertTrue(Path(item["src"]).is_file(), item["src"])
            for item in character["pose_assets"].values():
                self.assertTrue(Path(item["src"]).is_file(), item["src"])

            self.assertEqual(
                attached["scenes"][0]["character_actions"]["violin-prince"]["pose_asset"],
                "resting_hands",
            )
            self.assertEqual(
                attached["scenes"][1]["character_actions"]["violin-prince"]["expression"],
                "speaking",
            )


if __name__ == "__main__":
    unittest.main()
