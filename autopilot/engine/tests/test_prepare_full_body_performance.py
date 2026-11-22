"""Tests for preparation of a full-body violin performance reference."""
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from prepare_full_body_performance import prepare


class FullBodyPerformancePreparationTests(unittest.TestCase):
    def test_prepares_props_and_four_finger_regions_from_full_body_source(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "playing.png"
            neutral = root / "neutral.png"
            output = root / "output"
            references = root / "references"
            references.mkdir()

            master = Image.new("RGBA", (441, 755), (40, 40, 45, 255))
            Image.new("RGBA", (580, 762), (20, 20, 25, 0)).save(neutral)
            master.save(source)

            result = prepare(source, neutral, output, references)
            self.assertEqual(result["status"], "full_body_reference_prepared")
            self.assertEqual(result["canvas"], {"width": 441, "height": 755})
            self.assertTrue((output / "master-character.webp").is_file())
            props = json.loads((references / "instrument-props.json").read_text(encoding="utf-8"))
            fingers = json.loads((references / "finger-regions.json").read_text(encoding="utf-8"))
            self.assertEqual(set(props["props"]), {"violin", "bow"})
            self.assertEqual(set(fingers["fingers"]), {"index", "middle", "ring", "little"})
            self.assertEqual(result["publishing"], "disabled")


if __name__ == "__main__":
    unittest.main()
