from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from create_cinematic_composition_preview import _audio_track_manifest


class CinematicPreviewAudioInputTests(unittest.TestCase):
    def test_creator_voice_and_violin_are_private_and_not_looped(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tracks = _audio_track_manifest(
                root / "voice.wav",
                root / "violin.wav",
                root / "whoosh.wav",
                creator_voice=True,
                music_source="creator_recording",
                voice_source_in_seconds=1.25,
            )
        voice, music, sfx = tracks
        self.assertEqual(voice["source_type"], "creator_recorded_voice")
        self.assertTrue(voice["private_source"])
        self.assertEqual(voice["source_in_seconds"], 1.25)
        self.assertEqual(music["source_type"], "creator_recorded_violin")
        self.assertTrue(music["private_source"])
        self.assertFalse(music["loop"])
        self.assertEqual(sfx["source_type"], "generated_preview_sfx")
        self.assertFalse(sfx["private_source"])

    def test_synthetic_voice_is_explicitly_marked_as_test_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            tracks = _audio_track_manifest(
                root / "synthetic.wav",
                root / "sample.wav",
                root / "whoosh.wav",
                creator_voice=False,
                music_source="cc0_sample",
            )
        voice, music, _sfx = tracks
        self.assertEqual(voice["source_type"], "synthetic_test_fixture")
        self.assertFalse(voice["private_source"])
        self.assertEqual(music["source_type"], "cc0_sample")
        self.assertTrue(music["loop"])
        self.assertFalse(music["private_source"])

    def test_rejects_unsupported_music_source(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ValueError, "music_source"):
                _audio_track_manifest(
                    root / "voice.wav",
                    root / "music.wav",
                    root / "sfx.wav",
                    creator_voice=True,
                    music_source="downloaded_random_track",
                )


if __name__ == "__main__":
    unittest.main()
