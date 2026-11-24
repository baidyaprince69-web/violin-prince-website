import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from create_full_body_performance_preview import build_preview_project


class FullBodyPreviewVisibilityTests(unittest.TestCase):
    def test_performer_is_scheduled_from_the_first_frame(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundle = root / "bundle"
            output = root / "output"
            bundle.mkdir()
            Image.new("RGBA", (8, 8), (40, 50, 60, 255)).save(bundle / "torso.png")
            character = {
                "id": "violin-prince-test",
                "canvas": {"width": 8, "height": 8},
                "performance": {"instrument_performance": True},
                "layers": [{
                    "id": "torso",
                    "role": "torso",
                    "src": "torso.png",
                    "x": 0,
                    "y": 0,
                    "width": 8,
                    "height": 8,
                }],
                "props": {},
            }
            (bundle / "character.json").write_text(
                json.dumps(character), encoding="utf-8"
            )

            result = build_preview_project(bundle, output)
            project = json.loads((output / "project.json").read_text(encoding="utf-8"))
            action = project["scenes"][0]["character_actions"]["violin-prince"]

            self.assertEqual(result["status"], "preview_project_ready")
            self.assertTrue(action["visible"])
            self.assertEqual(action["start_offset"], 0.0)
            self.assertEqual(project["scenes"][0]["start"], 0)


if __name__ == "__main__":
    unittest.main()
