import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import soundfile as sf
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

    def test_creator_wav_sets_full_duration_and_drives_note_level_fingering(self):
        sample_rate = 22050
        duration = 5.0
        samples = np.zeros(int(sample_rate * duration), dtype=np.float32)
        for start, end, frequency in (
            (0.12, 0.52, 440.0),
            (0.92, 1.32, 493.883),
            (1.82, 2.22, 587.330),
            (2.72, 3.12, 659.255),
            (3.62, 4.02, 698.456),
        ):
            left = int(start * sample_rate)
            right = int(end * sample_rate)
            time = np.arange(right - left, dtype=np.float32) / sample_rate
            envelope = np.minimum(
                1.0,
                np.minimum(time / 0.06, (end - start - time) / 0.06),
            )
            samples[left:right] = 0.22 * envelope * (
                np.sin(2 * np.pi * frequency * time)
                + 0.20 * np.sin(2 * np.pi * frequency * 2 * time)
            )

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
            recording = root / "creator-violin.wav"
            sf.write(recording, samples, sample_rate, subtype="PCM_16")

            result = build_preview_project(
                bundle, output, audio_path=recording, bpm=120.0
            )
            project = json.loads((output / "project.json").read_text(encoding="utf-8"))
            sync = project["scenes"][0]["character_actions"]["violin-prince"]["music_sync"]

        self.assertEqual(result["duration_seconds"], duration)
        self.assertEqual(project["duration_seconds"], duration)
        self.assertEqual(project["scenes"][0]["duration"], duration)
        self.assertEqual(sync["event_map_source"], "creator_recording_pitch_analysis")
        self.assertEqual(sync["note_analysis_status"], "passed")
        self.assertGreaterEqual(sync["note_analysis_event_count"], 4)
        self.assertGreaterEqual(len(sync["note_events"]), 4)
        self.assertEqual(sync["onsets"], [event["time"] for event in sync["note_events"]])

    def test_explicit_duration_cannot_exceed_attached_audio(self):
        sample_rate = 22050
        samples = np.zeros(sample_rate * 4, dtype=np.float32)
        for start, frequency in ((0.1, 440.0), (1.0, 493.883), (2.0, 587.330), (3.0, 659.255)):
            left = int(start * sample_rate)
            right = min(len(samples), left + int(0.4 * sample_rate))
            time = np.arange(right - left, dtype=np.float32) / sample_rate
            samples[left:right] = 0.2 * np.sin(2 * np.pi * frequency * time)

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
                    "id": "torso", "role": "torso", "src": "torso.png",
                    "x": 0, "y": 0, "width": 8, "height": 8,
                }],
                "props": {},
            }
            (bundle / "character.json").write_text(json.dumps(character), encoding="utf-8")
            recording = root / "short-violin.wav"
            sf.write(recording, samples, sample_rate, subtype="PCM_16")

            with self.assertRaisesRegex(ValueError, "shorter than the requested"):
                build_preview_project(
                    bundle, output, audio_path=recording, bpm=120.0,
                    duration_seconds=5.0,
                )


    def test_instrumental_performance_uses_neutral_face_and_only_an_occasional_blink(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            bundle = root / "bundle"
            output = root / "output"
            bundle.mkdir()
            Image.new("RGBA", (8, 8), (40, 50, 60, 255)).save(bundle / "torso.png")
            Image.new("RGBA", (8, 8), (80, 70, 60, 255)).save(bundle / "neutral-head.png")
            Image.new("RGBA", (8, 8), (80, 70, 60, 255)).save(bundle / "blink-head.png")
            character = {
                "id": "violin-prince-test",
                "canvas": {"width": 8, "height": 8},
                "performance": {"instrument_performance": True},
                "layers": [{
                    "id": "torso", "role": "torso", "src": "torso.png",
                    "x": 0, "y": 0, "width": 8, "height": 8,
                }],
                "props": {},
                "head_variants": {
                    "neutral": {
                        "src": "neutral-head.png",
                        "x": 0, "y": 0, "width": 8, "height": 8,
                    },
                    "blink_closed": {
                        "src": "blink-head.png",
                        "x": 0, "y": 0, "width": 8, "height": 8,
                    },
                },
            }
            (bundle / "character.json").write_text(
                json.dumps(character), encoding="utf-8"
            )

            build_preview_project(bundle, output)
            project = json.loads((output / "project.json").read_text())
            action = project["scenes"][0]["character_actions"]["violin-prince"]

        self.assertEqual(action["expression"], "neutral")
        self.assertEqual(action["head_expression"], "neutral")
        self.assertEqual(
            action["head_expression_sequence"],
            ["neutral", "neutral", "neutral", "blink_closed", "neutral", "neutral"],
        )
        self.assertEqual(action["head_expression_cycle_duration_seconds"], 8.0)
        self.assertFalse(
            {"happy", "smile", "sad", "shocked_open", "speaking_open", "speaking_closed"}
            & set(action["head_expression_sequence"])
        )


if __name__ == "__main__":
    unittest.main()
