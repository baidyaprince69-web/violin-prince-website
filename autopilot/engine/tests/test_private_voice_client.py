"""Offline validation tests for the authenticated private Qwen3 bridge."""
import hashlib
import os
import re
import sys
import tempfile
import unittest
from io import BytesIO
from pathlib import Path

import numpy as np
import soundfile as sf

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from private_voice_client import (
    PrivateVoiceBridgeError,
    generate_private_voiceover,
    validate_private_narration,
    _select_private_draft_release,
)

SCRIPT = (
    "Could your room change your violin mix? "
    "Audient's new iD range adds RoomTune monitor correction. "
    "It measures your room's acoustics and adjusts monitor playback. "
    "Onboard DSP runs input EQ, compression and reverb with no latency."
)


def fixture_payload(duration=22.5):
    script = re.sub(r"\s+", " ", SCRIPT).strip()
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+", script) if part.strip()]
    words = []
    for sentence_index, sentence in enumerate(sentences):
        for word in re.findall(r"[\w’'-]+", sentence):
            words.append((word, sentence_index))

    wav_buffer = BytesIO()
    sf.write(wav_buffer, np.zeros(round(24_000 * duration), dtype=np.float32), 24_000, format="WAV", subtype="PCM_16")
    wav_bytes = wav_buffer.getvalue()

    word_cues = []
    for index, (word, sentence_index) in enumerate(words):
        start = 0.4 + index * ((duration - 1.0) / max(1, len(words)))
        word_cues.append({
            "text": word,
            "start": round(start, 4),
            "end": round(start + 0.065, 4),
            "sentence_index": sentence_index,
        })

    subtitle_cues = []
    for sentence_index, sentence in enumerate(sentences):
        sentence_words = [cue for cue in word_cues if cue["sentence_index"] == sentence_index]
        subtitle_cues.append({
            "text": sentence,
            "start": sentence_words[0]["start"],
            "end": sentence_words[-1]["end"],
            "sentence_index": sentence_index,
        })

    metadata = {
        "schema_version": 1,
        "request_id": "123456789",
        "model": "Qwen/Qwen3-TTS-12Hz-0.6B-Base",
        "script_sha256": hashlib.sha256(script.encode("utf-8")).hexdigest(),
        "audio": {
            "sha256": hashlib.sha256(wav_bytes).hexdigest(),
            "size_bytes": len(wav_bytes),
            "sample_rate": 24_000,
            "channels": 1,
            "duration_seconds": round(duration, 4),
        },
        "audio_postprocessing": "none",
        "word_sync_status": "verified_exact_transcript",
        "word_timing_method": "faster-whisper-cross-attention-dtw",
        "aligner": {
            "name": "faster-whisper",
            "version": "1.2.1",
            "model": "small.en",
            "hotwords": ["Audient", "RoomTune", "iD"],
            "transcript_match": "exact",
        },
        "word_cues": word_cues,
        "subtitle_cues": subtitle_cues,
    }
    return wav_bytes, metadata



class PrivateDraftReleaseLookupTests(unittest.TestCase):
    def test_selects_matching_draft_release(self):
        tag = "private-own-voice-narration-123456789"
        releases = [
            {"tag_name": "older-release", "draft": True},
            {"tag_name": tag, "draft": True, "assets": [{"name": "narration.wav"}]},
        ]
        self.assertEqual(_select_private_draft_release(releases, tag), releases[1])

    def test_returns_none_when_matching_draft_is_not_listed(self):
        self.assertIsNone(_select_private_draft_release(
            [{"tag_name": "another-release", "draft": True}],
            "private-own-voice-narration-123456789",
        ))

    def test_rejects_a_matching_release_that_is_not_draft(self):
        tag = "private-own-voice-narration-123456789"
        with self.assertRaisesRegex(PrivateVoiceBridgeError, "published unexpectedly"):
            _select_private_draft_release([{"tag_name": tag, "draft": False}], tag)


class PrivateVoiceValidationTests(unittest.TestCase):
    def test_accepts_exact_transcript_and_complete_word_timings(self):
        wav_bytes, metadata = fixture_payload()
        info = validate_private_narration(
            SCRIPT, wav_bytes, metadata,
            expected_hotwords=["Audient", "RoomTune", "iD"],
        )
        self.assertEqual(info["word_sync_status"], "verified_exact_transcript")
        self.assertEqual(info["word_timing_count"], 35)
        self.assertEqual(info["engine"], "Qwen3-TTS")
        self.assertEqual(len(info["subtitle_cues"]), 4)

    def test_rejects_scripts_outside_the_35_word_calibration(self):
        wav_bytes, metadata = fixture_payload()
        with self.assertRaisesRegex(PrivateVoiceBridgeError, "exactly 35 words"):
            validate_private_narration(SCRIPT.replace("with no latency.", "with latency."), wav_bytes, metadata)
        with self.assertRaisesRegex(PrivateVoiceBridgeError, "exactly 35 words"):
            validate_private_narration(SCRIPT.replace("with no latency.", "with no latency every single session today."), wav_bytes, metadata)

    def test_rejects_asr_hotword_metadata_that_differs_from_the_request(self):
        wav_bytes, metadata = fixture_payload()
        with self.assertRaisesRegex(PrivateVoiceBridgeError, "hotword hints do not match"):
            validate_private_narration(
                SCRIPT, wav_bytes, metadata,
                expected_hotwords=["Audient", "RoomTune", "different"],
            )

    def test_rejects_audio_outside_the_22_to_23_second_target(self):
        for duration in (21.9, 23.1):
            with self.subTest(duration=duration):
                wav_bytes, metadata = fixture_payload(duration=duration)
                with self.assertRaisesRegex(PrivateVoiceBridgeError, "22.0 and 23.0 seconds"):
                    validate_private_narration(SCRIPT, wav_bytes, metadata)

    def test_rejects_a_metadata_script_hash_mismatch(self):
        wav_bytes, metadata = fixture_payload()
        metadata["script_sha256"] = "0" * 64
        with self.assertRaisesRegex(PrivateVoiceBridgeError, "does not match"):
            validate_private_narration(SCRIPT, wav_bytes, metadata)

    def test_rejects_changed_audio_bytes(self):
        wav_bytes, metadata = fixture_payload()
        corrupted = wav_bytes[:-2] + bytes([wav_bytes[-2] ^ 0xFF, wav_bytes[-1]])
        with self.assertRaisesRegex(PrivateVoiceBridgeError, "checksum"):
            validate_private_narration(SCRIPT, corrupted, metadata)

    def test_rejects_word_sequence_that_does_not_match_the_script(self):
        wav_bytes, metadata = fixture_payload()
        metadata["word_cues"][0]["text"] = "Different"
        with self.assertRaisesRegex(PrivateVoiceBridgeError, "do not match"):
            validate_private_narration(SCRIPT, wav_bytes, metadata)

    def test_rejects_non_monotonic_or_out_of_range_word_timing(self):
        wav_bytes, metadata = fixture_payload()
        metadata["word_cues"][4]["start"] = metadata["word_cues"][3]["start"] - 0.1
        metadata["word_cues"][4]["end"] = metadata["word_cues"][3]["start"] - 0.02
        with self.assertRaisesRegex(PrivateVoiceBridgeError, "timing validation"):
            validate_private_narration(SCRIPT, wav_bytes, metadata)

    def test_rejects_unverified_transcript_alignment(self):
        wav_bytes, metadata = fixture_payload()
        metadata["aligner"]["transcript_match"] = "approximate"
        with self.assertRaisesRegex(PrivateVoiceBridgeError, "transcript verification"):
            validate_private_narration(SCRIPT, wav_bytes, metadata)

    def test_fails_closed_when_private_repository_token_is_missing(self):
        previous = os.environ.pop("PRIVATE_VOICE_REPO_TOKEN", None)
        try:
            with tempfile.TemporaryDirectory() as folder:
                with self.assertRaisesRegex(PrivateVoiceBridgeError, "PRIVATE_VOICE_REPO_TOKEN"):
                    generate_private_voiceover(SCRIPT, Path(folder) / "narration.wav", request_id="123")
        finally:
            if previous is not None:
                os.environ["PRIVATE_VOICE_REPO_TOKEN"] = previous


if __name__ == "__main__":
    unittest.main()
