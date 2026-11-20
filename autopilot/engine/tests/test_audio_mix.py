"""Regression tests for narration-forward Violin Prince audio mixing."""
import sys
import unittest
from pathlib import Path

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

from audio_mix import (  # noqa: E402
    VOICE_PRIORITY_MIX,
    bed_volume_for,
    sidechain_music_filter,
    voice_processing_filter,
)


class VoicePriorityMixTests(unittest.TestCase):
    def test_violin_bed_is_lower_than_previous_mix(self):
        self.assertEqual(bed_volume_for("sampled_violin_cc0"), 0.12)
        self.assertEqual(bed_volume_for("generated_sampled_instrument"), 0.12)
        self.assertLess(bed_volume_for("sampled_violin_cc0"), 0.24)

    def test_ambient_and_creator_beds_stay_quieter(self):
        self.assertEqual(bed_volume_for("generated_ambient_fallback"), 0.10)
        self.assertEqual(bed_volume_for("creator_recorded_violin"), 0.12)
        self.assertEqual(VOICE_PRIORITY_MIX["creator_take_volume"], 0.80)

    def test_voice_chain_adds_presence_and_level_without_extreme_eq(self):
        chain = voice_processing_filter()
        self.assertIn("highpass=f=80", chain)
        self.assertIn("equalizer=f=2600:t=q:w=1.0:g=1.5", chain)
        self.assertIn("acompressor=threshold=-22dB:ratio=3.5", chain)
        self.assertIn("volume=1.40", chain)

    def test_music_is_ducked_more_strongly_by_narration(self):
        chain = sidechain_music_filter()
        self.assertIn("threshold=0.025", chain)
        self.assertIn("ratio=16", chain)
        self.assertIn("attack=8", chain)
        self.assertIn("release=480", chain)
        self.assertIn("[duckedbed]", chain)

    def test_custom_filter_labels_are_supported(self):
        chain = sidechain_music_filter("music", "voice_sc", "ducked_music")
        self.assertTrue(chain.startswith("[music][voice_sc]"))
        self.assertTrue(chain.endswith("[ducked_music]"))


if __name__ == "__main__":
    unittest.main()
