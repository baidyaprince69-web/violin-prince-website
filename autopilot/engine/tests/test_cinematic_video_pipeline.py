import json
import tempfile
import unittest
from pathlib import Path

from cinematic_video_pipeline import CompositionError, _filtergraph, validate_timeline


class CinematicTimelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        for name in ("character.mp4", "overlay.mov", "voice.wav", "music.wav", "whoosh.wav"):
            (self.root / name).write_bytes(b"fixture")
        self.manifest = {
            "schema_version": 1, "preview_only": True, "publish_enabled": False,
            "width": 720, "height": 1280, "fps": 25, "duration_seconds": 8,
            "video_layers": [
                {"id": "character", "path": "character.mp4", "kind": "video",
                 "role": "character", "start_seconds": 0, "end_seconds": 8},
                {"id": "visualizer", "path": "overlay.mov", "kind": "video",
                 "role": "motion_graphic", "start_seconds": 1, "end_seconds": 7,
                 "width": 360, "height": 640, "x": 180, "y": 250, "opacity": 0.9}
            ],
            "text_layers": [{"id": "caption", "text": "Violin Prince", "start_seconds": 0.5,
                             "end_seconds": 7.5, "font_size": 48}],
            "audio_tracks": [
                {"id": "narration", "path": "voice.wav", "role": "voice",
                 "start_seconds": 0, "end_seconds": 8, "private_source": True},
                {"id": "score", "path": "music.wav", "role": "music",
                 "start_seconds": 0, "end_seconds": 8, "loop": True, "gain_db": -12},
                {"id": "whoosh", "path": "whoosh.wav", "role": "sfx",
                 "start_seconds": 2, "end_seconds": 3, "gain_db": -9}
            ]
        }

    def tearDown(self):
        self.temp.cleanup()

    def test_accepts_character_voice_music_sfx_and_visual_layers(self):
        result = validate_timeline(self.manifest, self.root)
        self.assertEqual([x["role"] for x in result["layers"]], ["character", "motion_graphic"])
        self.assertEqual([x["role"] for x in result["audio"]], ["voice", "music", "sfx"])
        self.assertTrue(result["private"])

    def test_requires_publishing_to_be_disabled(self):
        data = dict(self.manifest, publish_enabled=True)
        with self.assertRaisesRegex(CompositionError, "publish_enabled=false"):
            validate_timeline(data, self.root)

    def test_requires_preview_mode(self):
        data = dict(self.manifest, preview_only=False)
        with self.assertRaises(CompositionError):
            validate_timeline(data, self.root)

    def test_requires_voice_track(self):
        data = dict(self.manifest, audio_tracks=[self.manifest["audio_tracks"][1]])
        with self.assertRaisesRegex(CompositionError, "voice"):
            validate_timeline(data, self.root)

    def test_rejects_duplicate_media_layer_ids(self):
        data = json.loads(json.dumps(self.manifest))
        data["video_layers"][1]["id"] = "character"
        with self.assertRaisesRegex(CompositionError, "duplicate"):
            validate_timeline(data, self.root)

    def test_rejects_layer_after_timeline_end(self):
        data = json.loads(json.dumps(self.manifest))
        data["video_layers"][1]["end_seconds"] = 9
        with self.assertRaises(CompositionError):
            validate_timeline(data, self.root)

    def test_rejects_missing_media(self):
        data = json.loads(json.dumps(self.manifest))
        data["audio_tracks"][0]["path"] = "missing.wav"
        with self.assertRaisesRegex(CompositionError, "does not exist"):
            validate_timeline(data, self.root)

    def test_filtergraph_has_independent_video_layers_and_audio_buses(self):
        timeline = validate_timeline(self.manifest, self.root)
        graph = _filtergraph(timeline, audio_offset=len(timeline["layers"]))
        for required in ("sidechaincompress", "overlay=", "drawtext=", "alimiter=", "asplit=2"):
            self.assertIn(required, graph)


if __name__ == "__main__":
    unittest.main()
