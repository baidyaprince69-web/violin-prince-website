"""Offline FFmpeg render smoke test; no external AI services are called."""
import array
import math
import os
import shutil
import subprocess
import sys
import wave
import unittest
from pathlib import Path

os.environ.setdefault("AUTOPILOT_API_URL", "https://example.invalid")
os.environ.setdefault("AUTOPILOT_JOB_TOKEN", "test-job-token")
os.environ.setdefault("CF_ACCOUNT_ID", "test-account")
os.environ.setdefault("CF_AI_TOKEN", "test-ai-token")

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from PIL import Image
from synth_audio import create_original_soundtrack
import run as pipeline


class FFmpegRenderSmokeTests(unittest.TestCase):
    def test_complete_vertical_video_has_picture_audio_and_timed_subtitles(self):
        pipeline.WORK = Path("work")
        pipeline.OUT = pipeline.WORK / "output"
        pipeline.IMAGES = pipeline.WORK / "images"
        pipeline.W = 720
        pipeline.H = 1280
        pipeline.FPS = 8
        pipeline.SECONDS = 8

        shutil.rmtree(pipeline.WORK, ignore_errors=True)
        pipeline.WORK.mkdir(parents=True, exist_ok=True)
        pipeline.OUT.mkdir(parents=True, exist_ok=True)
        pipeline.IMAGES.mkdir(parents=True, exist_ok=True)

        original_make_image = pipeline.make_image

        def fake_make_image(prompt, index):
            target = pipeline.IMAGES / f"smoke-{index + 1}.jpg"
            colours = [(32, 52, 78), (72, 48, 42), (34, 72, 62)]
            Image.new("RGB", (1024, 1024), colours[index % len(colours)]).save(target, "JPEG")
            return target

        try:
            # Simulate a package whose images were generated and reviewed in an earlier run.
            prepared_images = [fake_make_image("approved scene", index) for index in range(3)]

            def unexpected_ai_image_call(_prompt, _index):
                raise AssertionError("Render stage must reuse approved images and never call image generation.")

            pipeline.make_image = unexpected_ai_image_call

            background = pipeline.WORK / "background.wav"
            create_original_soundtrack(background, seed_text="render-smoke-test")

            narration = pipeline.OUT / "narration-test.wav"
            sample_rate = 24000
            sample_count = sample_rate * 6
            samples = array.array("h")
            for i in range(sample_count):
                t = i / sample_rate
                envelope = min(1.0, t / 0.25, (6.0 - t) / 0.35)
                value = 0.16 * envelope * math.sin(2.0 * math.pi * 220.0 * t)
                samples.append(int(max(-1.0, min(1.0, value)) * 32767))
            with wave.open(str(narration), "wb") as output:
                output.setnchannels(1)
                output.setsampwidth(2)
                output.setframerate(sample_rate)
                output.writeframes(samples.tobytes())

            performance_video = pipeline.WORK / "creator-performance-test.mp4"
            subprocess.run(
                [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                    "-f", "lavfi", "-i", "testsrc2=size=640x360:rate=8",
                    "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=24000",
                    "-t", "9", "-c:v", "libx264", "-preset", "ultrafast",
                    "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
                    str(performance_video),
                ],
                check=True,
            )

            plan = {
                "title": "A Small Test Story",
                "narration_script": "A test voice explains a short story with a beginning, a useful detail and a clear ending.",
                "scenes": [
                    {"caption": "A story begins", "image_prompt": "test image one"},
                    {"caption": "A new detail appears", "image_prompt": "test image two"},
                    {"caption": "The story resolves", "image_prompt": "test image three"},
                ],
            }
            narration_info = {
                "subtitle_cues": [
                    {"start": 0.20, "end": 2.40, "text": "A test voice explains a short story."},
                    {"start": 2.55, "end": 5.20, "text": "A useful detail brings the story to a clear ending."},
                ]
            }

            final_path, quality = pipeline.render(
                plan, background.read_bytes(), narration, narration_info,
                image_paths=prepared_images, performance_video_path=performance_video
            )

            self.assertTrue(final_path.exists())
            self.assertEqual(quality["width"], 720)
            self.assertEqual(quality["height"], 1280)
            self.assertGreaterEqual(quality["duration_seconds"], 23.5)
            self.assertLessEqual(quality["duration_seconds"], 24.5)
            self.assertGreater(quality["file_size_bytes"], 150000)
            self.assertTrue(quality["creator_performance_video"]["inserted"])
            self.assertTrue(quality["creator_performance_video"]["audio_inserted"])
            self.assertEqual(quality["creator_performance_video"]["source_width"], 640)
            self.assertGreater(quality["creator_performance_video"]["timeline_start_seconds"], 5)

            subtitle_file = pipeline.OUT / "narration.srt"
            self.assertTrue(subtitle_file.exists())
            subtitle_text = subtitle_file.read_text(encoding="utf-8")
            self.assertIn("00:00:00,200 --> 00:00:02,400", subtitle_text)
            self.assertIn("A test voice explains a short story.", subtitle_text.replace("\n", " "))

            audio_check = subprocess.run(
                ["ffmpeg", "-hide_banner", "-i", str(final_path),
                 "-map", "0:a:0", "-af", "volumedetect", "-f", "null", "-"],
                capture_output=True, text=True
            )
            self.assertEqual(audio_check.returncode, 0, audio_check.stderr[-1000:])
            self.assertIn("mean_volume:", audio_check.stderr)
            self.assertNotIn("mean_volume: -inf", audio_check.stderr)
        finally:
            pipeline.make_image = original_make_image
            shutil.rmtree(pipeline.WORK, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
