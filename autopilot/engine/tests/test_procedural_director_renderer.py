"""End-to-end mapping tests for procedural Master Director v3 plans."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

from procedural_director_renderer import ProceduralDirectorError, build_procedural_director_project
from master_creative_director import validate_director_plan


FIXTURE = ENGINE_DIR / "tests" / "fixtures" / "master-director-procedural-demo.json"
RIG_BUNDLE = ENGINE_DIR / "assets" / "characters" / "violin-prince-rig"


class ProceduralDirectorRendererTests(unittest.TestCase):
    def setUp(self):
        self.plan = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_source_grounded_procedural_plan_passes_v3_contract(self):
        self.assertEqual(validate_director_plan(self.plan), [])
        self.assertEqual(self.plan["render_mode"], "procedural_2d")
        self.assertEqual(len(self.plan["storyboard"]["shots"]), 8)
        self.assertTrue(all(shot["procedural_scene"]["objects"] for shot in self.plan["storyboard"]["shots"]))

    def test_director_shots_become_real_motion_scenes_without_picture_layers(self):
        with tempfile.TemporaryDirectory() as temporary:
            project = build_procedural_director_project(
                self.plan,
                temporary,
                rig_bundle_dir=RIG_BUNDLE,
            )
            root = Path(temporary)
            self.assertEqual(project["render_mode"], "procedural_2d")
            self.assertEqual(project["duration_seconds"], 32)
            self.assertEqual(len(project["scenes"]), 8)
            self.assertEqual(project["visual_asset_policy"]["generated_scene_images"], 0)
            self.assertEqual(project["visual_asset_policy"]["generated_cutout_images"], 0)
            self.assertEqual(project["shot_asset_manifest"], [])

            character = next(item for item in project["characters"] if item["id"] == "violin-prince")
            self.assertEqual(len(character["layers"]), 9)
            for section in ("layers",):
                for item in character.get(section, []):
                    asset = (root / item["src"]).resolve()
                    self.assertTrue(asset.is_file(), item["src"])
                    self.assertIn("assets/characters/violin-prince/", item["src"])
            for section in ("expressions", "pose_assets"):
                for item in (character.get(section) or {}).values():
                    self.assertTrue((root / item["src"]).is_file(), item["src"])

            for source_shot, scene in zip(self.plan["storyboard"]["shots"], project["scenes"], strict=True):
                with self.subTest(scene=scene["id"]):
                    self.assertEqual(scene["id"], source_shot["id"])
                    self.assertEqual(scene["visual_mode"], "procedural_2d")
                    self.assertEqual(scene["stagecraft"]["environment"], source_shot["procedural_scene"]["environment"])
                    self.assertEqual(scene["stagecraft"]["objects"], source_shot["procedural_scene"]["objects"])
                    self.assertEqual(scene["director_camera"], source_shot["camera"])
                    expected_action = dict(source_shot["character_action"])
                    if source_shot.get("graphic_data"):
                        expected_action.update({"x": 315, "scale": 0.56})
                    self.assertEqual(scene["character_actions"]["violin-prince"], expected_action)
                    self.assertNotIn("visual_layers", scene)
                    self.assertNotIn("image", scene)
                    self.assertEqual(scene.get("graphic_data"), source_shot.get("graphic_data"))
                    if source_shot.get("graphic_data"):
                        self.assertEqual(scene["visual_composition"]["layout"], "graphic_left_presenter_right")
                        self.assertEqual(scene["character_actions"]["violin-prince"]["x"], 315)
                        self.assertEqual(scene["character_actions"]["violin-prince"]["scale"], 0.56)
                    else:
                        self.assertNotIn("visual_composition", scene)
                    self.assertGreater(scene["duration"], 0)
                    self.assertTrue(scene["animation_execution_status"].startswith("procedural_"))

            saved = json.loads((root / "project.json").read_text(encoding="utf-8"))
            self.assertEqual(saved["director_contract"], "violin-prince-master-director-v3")
            self.assertEqual(saved["diagnostics"]["publishing"], "disabled")

    def test_invalid_procedural_scene_is_rejected_before_project_creation(self):
        bad = json.loads(json.dumps(self.plan))
        bad["storyboard"]["shots"][0]["procedural_scene"]["objects"][0]["kind"] = "background_jpeg"
        self.assertTrue(any("kind is unsupported" in issue for issue in validate_director_plan(bad)))
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(ProceduralDirectorError):
                build_procedural_director_project(bad, temporary, rig_bundle_dir=RIG_BUNDLE)
            self.assertFalse((Path(temporary) / "project.json").exists())


if __name__ == "__main__":
    unittest.main()
