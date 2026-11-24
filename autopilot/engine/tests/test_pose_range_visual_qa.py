import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

from pose_range_visual_qa import analyse_sampled_frames, create_contact_sheet


def _sample_image(offset: int = 0) -> Image.Image:
    image = Image.new("RGB", (80, 60), (12, 18, 24))
    draw = ImageDraw.Draw(image)
    draw.rectangle((10 + offset, 8, 38 + offset, 46), fill=(220, 170, 105))
    draw.line((0, 50 - offset, 79, 50 - offset), fill=(70, 130, 180), width=3)
    return image


class PoseRangeVisualQATests(unittest.TestCase):
    def test_analyser_reports_dense_frame_variation(self):
        images = [_sample_image(offset) for offset in (0, 1, 2, 3)]
        report = analyse_sampled_frames(images, fps=4.0)

        self.assertEqual(report["status"], "passed")
        self.assertEqual(report["sample_count"], 4)
        self.assertEqual(report["sample_interval_seconds"], 0.25)
        self.assertEqual(report["unique_frame_count"], 4)
        self.assertEqual(report["nonblank_frame_count"], 4)
        self.assertGreater(report["mean_adjacent_frame_difference"], 0)

    def test_analyser_rejects_a_blank_or_uniform_frame(self):
        blank = Image.new("RGB", (80, 60), (0, 0, 0))
        with self.assertRaisesRegex(ValueError, "blank or near-uniform"):
            analyse_sampled_frames([_sample_image(), blank], fps=4.0)

    def test_analyser_rejects_a_static_sequence(self):
        frame = _sample_image()
        with self.assertRaisesRegex(ValueError, "All sampled frames are identical"):
            analyse_sampled_frames([frame, frame.copy()], fps=4.0)

    def test_analyser_rejects_mismatched_frame_sizes(self):
        with self.assertRaisesRegex(ValueError, "dimensions differ"):
            analyse_sampled_frames(
                [_sample_image(), Image.new("RGB", (40, 30), (20, 40, 60))],
                fps=4.0,
            )

    def test_large_opening_transition_is_flagged_for_visual_review(self):
        background = Image.new("RGB", (80, 60), (12, 18, 24))
        draw = ImageDraw.Draw(background)
        draw.line((0, 12, 79, 12), fill=(80, 84, 100), width=2)
        draw.ellipse((62, 34, 67, 39), fill=(180, 170, 130))
        images = [background, _sample_image(0), _sample_image(1), _sample_image(2)]

        report = analyse_sampled_frames(images, fps=4.0)

        self.assertEqual(report["opening_interval_review"], "flagged")
        self.assertTrue(report["review_flags"])
        self.assertIn("performer visibility", report["review_flags"][0])

    def test_normal_small_motion_does_not_flag_opening_interval(self):
        report = analyse_sampled_frames(
            [_sample_image(offset) for offset in (0, 1, 2, 3)],
            fps=4.0,
        )
        self.assertEqual(report["opening_interval_review"], "clear")
        self.assertEqual(report["review_flags"], [])

    def test_contact_sheet_is_written_with_all_samples(self):
        images = [_sample_image(offset) for offset in (0, 1, 2, 3, 4, 5)]
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "pose-range.jpg"
            create_contact_sheet(images, output, fps=4.0, columns=3)
            self.assertTrue(output.is_file())
            with Image.open(output) as sheet:
                self.assertEqual(sheet.size, (540, 34 + 2 * 350))


if __name__ == "__main__":
    unittest.main()
