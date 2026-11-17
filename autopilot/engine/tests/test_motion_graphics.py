"""Offline smoke tests for source-data-driven animated infographics."""
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageFont

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

from motion_graphics import make_motion_graphic_frames  # noqa: E402


def fixture_font(size, *args):
    # The rendering code only needs a valid Pillow font; system font files are
    # not required for this deterministic contract test.
    return ImageFont.load_default()


class MotionGraphicsDataTests(unittest.TestCase):
    def _render(self, graphic_data):
        with tempfile.TemporaryDirectory() as temp_dir:
            pattern = make_motion_graphic_frames(
                {
                    "visual_mode": "macro_illustration",
                    "caption": "The measured detail",
                    "graphic_label": "THE KEY DETAIL",
                    "graphic_detail": "Source-backed scene explanation",
                    "graphic_data": graphic_data,
                },
                0,
                {"title": "Violin Prince"},
                temp_dir,
                frame_count=12,
                fps=4,
                font=fixture_font,
                word_events=[
                    {"text": "back", "start": 0.1},
                    {"text": "arch", "start": 0.8},
                    {"text": "resonance", "start": 1.7},
                ],
            )
            self.assertTrue(str(pattern).endswith("frame-%05d.png"))
            with Image.open(Path(temp_dir) / "frame-00012.png") as frame:
                self.assertEqual(frame.size, (620, 260))
                self.assertEqual(frame.mode, "RGBA")
                self.assertGreater(frame.getbbox()[2], 500)

    def test_arch_height_chart_renders_sourced_measurements(self):
        self._render({
            "type": "arch_heights",
            "title": "BACK ARCH HEIGHTS",
            "unit": "mm",
            "items": [
                {"label": "LOW", "value": 12.1, "display": "12.1 mm"},
                {"label": "MID", "value": 14.8, "display": "14.8 mm"},
                {"label": "HIGH", "value": 17.5, "display": "17.5 mm"},
            ],
        })

    def test_process_flow_renders_a_three_step_explanation(self):
        self._render({
            "type": "process_flow",
            "title": "HOW THE SOUND CHANGES",
            "items": ["BACK ARCH", "BODY MODES", "RESONANCE"],
        })


if __name__ == "__main__":
    unittest.main()
