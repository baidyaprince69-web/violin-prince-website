"""Model-level Kokoro TTS smoke test; no paid speech API or Cloudflare secrets."""
import importlib.util
import tempfile
import sys
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from voiceover import synthesize_voiceover, write_srt

HAS_KOKORO_STACK = all(
    importlib.util.find_spec(name) is not None
    for name in ("kokoro", "numpy", "soundfile")
)


class KokoroModelSmokeTest(unittest.TestCase):
    @unittest.skipUnless(HAS_KOKORO_STACK, "Kokoro stack is installed only in the dedicated cloud voiceover workflow.")
    def test_kokoro_produces_nonempty_voiceover_and_sentence_cues(self):
        script = (
            "Tonight, the city turns toward the river, where thousands of tiny lights "
            "reflect across the water. It is a simple tradition, but each year it brings "
            "families together and gives the familiar streets a different kind of magic."
        )
        with tempfile.TemporaryDirectory() as folder:
            audio_path, info = synthesize_voiceover(
                script, Path(folder) / "kokoro-smoke.wav"
            )
            self.assertTrue(audio_path.exists())
            self.assertGreater(audio_path.stat().st_size, 10000)
            self.assertEqual(info["engine"], "Kokoro-82M")
            self.assertGreater(info["duration_seconds"], 1.0)
            self.assertEqual(info["sample_rate"], 24000)
            self.assertEqual(info["voice_type"], "synthetic_not_voice_cloned")
            self.assertGreaterEqual(len(info["subtitle_cues"]), 2)
            srt = write_srt(info["subtitle_cues"], Path(folder) / "kokoro-smoke.srt")
            self.assertTrue(srt.exists())
            self.assertIn("Tonight, the city", srt.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
