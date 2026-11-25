import json
import tempfile
import unittest
from pathlib import Path

from cinematic_video_pipeline import CompositionError, _camera_move, _filtergraph, _rasterize_text_layers, validate_timeline


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
                 "width": 360, "height": 640, "x": 180, "y": 250, "opacity": 0.9,
                 "fade_in_seconds": 0.3, "fade_out_seconds": 0.4}
            ],
            "text_layers": [{"id": "caption", "text": "Violin Prince", "start_seconds": 0.5,
                             "end_seconds": 7.5, "font_size": 48, "fade_in_seconds": 0.2, "fade_out_seconds": 0.3}],
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

    def _presenter_cut_manifest(self):
        data = json.loads(json.dumps(self.manifest))
        base = data["video_layers"][0]
        base.update({
            "role": "character_performance",
            "camera_framing": "full_body_wide",
            "shot_id": "shot-01-wide",
            "camera_move": {"type": "push_in", "intensity": 0.55},
            "camera_move_duration_seconds": 1.65,
        })
        cuts = [
            ("medium", 1.65, 3.15, "medium_performance"),
            ("instrument", 3.15, 4.75, "instrument_hands_close_up"),
            ("face", 4.75, 6.25, "face_close_up"),
            ("hero", 6.25, 8.0, "full_body_wide"),
        ]
        cut_layers = []
        for name, start, end, framing in cuts:
            cut_layers.append({
                "id": "shot_" + name,
                "path": "character.mp4",
                "kind": "video",
                "role": "character_performance",
                "start_seconds": start,
                "end_seconds": end,
                "source_in_seconds": start,
                "x": 0, "y": 0, "width": 720, "height": 1280,
                "fit": "cover",
                "camera_framing": framing,
                "shot_id": "shot-" + name,
                "camera_move": {"type": "push_in", "intensity": 0.5},
            })
        data["video_layers"] = [base, *cut_layers, data["video_layers"][1]]
        return data

    def test_accepts_character_voice_music_sfx_and_visual_layers(self):
        result = validate_timeline(self.manifest, self.root)
        self.assertEqual([x["role"] for x in result["layers"]], ["character", "motion_graphic"])
        self.assertEqual([x["role"] for x in result["audio"]], ["voice", "music", "sfx"])
        self.assertTrue(result["private"])

    def test_character_camera_shots_are_opaque_gapless_hard_cuts(self):
        timeline = validate_timeline(self._presenter_cut_manifest(), self.root)
        shots = [
            layer for layer in timeline["layers"]
            if layer["role"] == "character_performance" and layer["shot_id"]
        ]
        self.assertEqual(timeline["camera_cut_mode"], "opaque_hard_cuts")
        self.assertEqual(timeline["presenter_camera_shot_count"], 5)
        self.assertEqual(
            [(round(x["effective_start"], 2), round(x["effective_end"], 2)) for x in shots],
            [(0.0, 1.65), (1.65, 3.15), (3.15, 4.75), (4.75, 6.25), (6.25, 8.0)],
        )
        self.assertEqual(shots[0]["camera_move_duration"], 1.65)

    def test_rejects_faded_presenter_camera_cuts(self):
        data = self._presenter_cut_manifest()
        data["video_layers"][1]["fade_in_seconds"] = 0.12
        with self.assertRaisesRegex(CompositionError, "fully opaque"):
            validate_timeline(data, self.root)

    def test_rejects_presenter_camera_gaps_and_overlaps(self):
        data = self._presenter_cut_manifest()
        data["video_layers"][1]["end_seconds"] = 3.10
        with self.assertRaisesRegex(CompositionError, "contiguous opaque hard cuts"):
            validate_timeline(data, self.root)
        data = self._presenter_cut_manifest()
        data["video_layers"][1]["end_seconds"] = 3.20
        with self.assertRaisesRegex(CompositionError, "contiguous opaque hard cuts"):
            validate_timeline(data, self.root)

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

    def test_creator_recorded_voice_and_violin_are_private_and_provenance_is_preserved(self):
        data = json.loads(json.dumps(self.manifest))
        data["audio_tracks"][0]["source_type"] = "creator_recorded_voice"
        data["audio_tracks"][0]["private_source"] = True
        data["audio_tracks"][1]["source_type"] = "creator_recorded_violin"
        data["audio_tracks"][1]["private_source"] = True
        data["audio_tracks"][1]["loop"] = False
        timeline = validate_timeline(data, self.root)
        self.assertTrue(timeline["private"])
        self.assertEqual(timeline["audio"][0]["source_type"], "creator_recorded_voice")
        self.assertEqual(timeline["audio"][1]["source_type"], "creator_recorded_violin")

    def test_rejects_creator_voice_if_declared_public(self):
        data = json.loads(json.dumps(self.manifest))
        data["audio_tracks"][0]["source_type"] = "creator_recorded_voice"
        data["audio_tracks"][0]["private_source"] = False
        with self.assertRaisesRegex(CompositionError, "private voice track"):
            validate_timeline(data, self.root)

    def test_rejects_creator_violin_if_looped_or_declared_public(self):
        data = json.loads(json.dumps(self.manifest))
        data["audio_tracks"][1]["source_type"] = "creator_recorded_violin"
        data["audio_tracks"][1]["private_source"] = True
        data["audio_tracks"][1]["loop"] = True
        with self.assertRaisesRegex(CompositionError, "must be private and must not loop"):
            validate_timeline(data, self.root)

    def test_text_layers_are_rasterised_as_transparent_video_assets(self):
        timeline = validate_timeline(self.manifest, self.root)
        layers = _rasterize_text_layers(timeline, self.root)
        self.assertEqual(len(layers), 1)
        self.assertEqual(layers[0]["kind"], "image")
        self.assertEqual(layers[0]["role"], "text")
        self.assertTrue(layers[0]["path"].is_file())
        from PIL import Image
        with Image.open(layers[0]["path"]) as image:
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.size, (720, 1280))
        self.assertEqual(layers[0]["fade_in"], 0.2)
        self.assertEqual(layers[0]["fade_out"], 0.3)
        self.assertIsNone(layers[0]["camera_move"])

    def test_camera_crop_and_color_grade_are_compiled(self):
        data = json.loads(json.dumps(self.manifest))
        data["video_layers"][0]["camera_crop"] = {
            "x": 0.1, "y": 0.05, "width": 0.8, "height": 0.8
        }
        data["video_layers"][0]["camera_framing"] = "full_body_wide"
        data["video_layers"][0]["shot_id"] = "shot-wide"
        data["video_layers"][0]["grade"] = {
            "contrast": 1.1, "saturation": 0.9, "brightness": -0.02, "gamma": 0.98
        }
        data["video_layers"][1]["camera_crop"] = {
            "x": 0.28, "y": 0.18, "width": 0.64, "height": 0.64
        }
        data["video_layers"][1]["camera_framing"] = "instrument_hands_close_up"
        timeline = validate_timeline(data, self.root)
        graph = _filtergraph(timeline, audio_offset=len(timeline["layers"]))
        self.assertIn("crop=w=trunc(iw*0.800000/2)*2", graph)
        self.assertIn("crop=w=trunc(iw*0.640000/2)*2", graph)
        self.assertIn("eq=contrast=1.1000:saturation=0.9000", graph)
        self.assertEqual(timeline["layers"][1]["camera_framing"], "instrument_hands_close_up")

    def test_rejects_camera_crop_outside_source_frame(self):
        data = json.loads(json.dumps(self.manifest))
        data["video_layers"][1]["camera_crop"] = {
            "x": 0.8, "y": 0.1, "width": 0.4, "height": 0.5
        }
        with self.assertRaisesRegex(CompositionError, "inside the source frame"):
            validate_timeline(data, self.root)

    def test_camera_moves_compile_as_frame_seekable_zoompan(self):
        data = json.loads(json.dumps(self.manifest))
        data["video_layers"][0]["camera_move"] = {"type": "push_in", "intensity": 0.65}
        data["video_layers"][1]["camera_move"] = {"type": "pan_right", "intensity": 0.4}
        timeline = validate_timeline(data, self.root)
        graph = _filtergraph(timeline, audio_offset=len(timeline["layers"]))
        self.assertIn("zoompan=z='1+0.09100*min(on/199,1)'", graph)
        self.assertIn("zoompan=z='1+0.04800*min(on/149,1)'", graph)
        self.assertIn("(iw-iw/zoom)*(0.09+0.82*(min(on/149,1)))", graph)
        self.assertIn("min(on/40,1)", _camera_move(timeline["layers"][0], 25))
        self.assertIn("s=720x1280:fps=25", graph)
        self.assertIn("s=360x640:fps=25", graph)
        self.assertEqual(timeline["layers"][0]["camera_move"], {"type": "push_in", "intensity": 0.65})
        self.assertEqual(timeline["layers"][1]["camera_move"], {"type": "pan_right", "intensity": 0.4})

    def test_rejects_invalid_camera_move(self):
        data = json.loads(json.dumps(self.manifest))
        data["video_layers"][1]["camera_move"] = {"type": "teleport", "intensity": 0.5}
        with self.assertRaisesRegex(CompositionError, "unsupported camera_move"):
            validate_timeline(data, self.root)

    def test_rejects_camera_move_intensity_out_of_range(self):
        data = json.loads(json.dumps(self.manifest))
        data["video_layers"][1]["camera_move"] = {"type": "push_in", "intensity": 1.5}
        with self.assertRaisesRegex(CompositionError, "between 0 and 1"):
            validate_timeline(data, self.root)

    def test_rejects_unknown_camera_framing(self):
        data = json.loads(json.dumps(self.manifest))
        data["video_layers"][1]["camera_framing"] = "extreme_zoom"
        with self.assertRaisesRegex(CompositionError, "unsupported camera_framing"):
            validate_timeline(data, self.root)

    def test_filtergraph_has_independent_video_layers_and_audio_buses(self):
        timeline = validate_timeline(self.manifest, self.root)
        graph = _filtergraph(timeline, audio_offset=len(timeline["layers"]))
        for required in ("sidechaincompress", "overlay=", "fade=t=in", "fade=t=out", "alimiter=", "asplit=2"):
            self.assertIn(required, graph)


if __name__ == "__main__":
    unittest.main()
