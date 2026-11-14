"""Offline tests for encrypted GitHub-native SEO learning persistence."""
import base64
import json
import os
import tempfile
import unittest
from pathlib import Path

from autopilot.engine.seo_intelligence.storage import (
    encrypt_learning_snapshot,
    load_learning_signals,
    read_encrypted_snapshot,
    write_encrypted_snapshot,
)


def make_key() -> str:
    return base64.urlsafe_b64encode(os.urandom(32)).decode("ascii").rstrip("=")


class EncryptedSEOLearningStorageTests(unittest.TestCase):
    def setUp(self):
        self.key = make_key()
        self.snapshot = {
            "captured_at": "2026-11-14",
            "seo_learning": {
                "sample_count": 6,
                "learning_ready": True,
                "language_signals": [
                    {"language": "en", "sample_count": 3, "relative_performance": "above_channel_median"}
                ],
                "search_term_signals": [
                    {
                        "language": "en",
                        "search_term": "emotional violin cover",
                        "views": 17,
                        "video_sample_count": 3,
                    }
                ],
            },
        }

    def test_encrypt_decrypt_round_trip(self):
        envelope = encrypt_learning_snapshot(self.snapshot, self.key)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "latest.enc.json"
            path.write_text(json.dumps(envelope), encoding="utf-8")
            restored = read_encrypted_snapshot(path, self.key)
        self.assertEqual(restored, self.snapshot)

    def test_plaintext_keywords_do_not_appear_in_envelope(self):
        envelope = encrypt_learning_snapshot(self.snapshot, self.key)
        serialized = json.dumps(envelope)
        self.assertNotIn("emotional violin cover", serialized)
        self.assertNotIn("above_channel_median", serialized)
        self.assertEqual(envelope["algorithm"], "AES-256-GCM")

    def test_discover_loader_returns_only_learning_signals(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "latest.enc.json"
            write_encrypted_snapshot(self.snapshot, path, self.key)
            learning = load_learning_signals(path, self.key)
        self.assertEqual(learning["captured_at"], "2026-11-14")
        self.assertEqual(learning["sample_count"], 6)
        self.assertNotIn("raw_channel_metrics", learning)

    def test_wrong_key_fails_closed(self):
        envelope = encrypt_learning_snapshot(self.snapshot, self.key)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "latest.enc.json"
            path.write_text(json.dumps(envelope), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "corrupt or the encryption key"):
                read_encrypted_snapshot(path, make_key())

    def test_tampered_ciphertext_fails_closed(self):
        envelope = encrypt_learning_snapshot(self.snapshot, self.key)
        encrypted = base64.b64decode(envelope["ciphertext"])
        envelope["ciphertext"] = base64.b64encode(encrypted[:-1] + bytes([encrypted[-1] ^ 1])).decode("ascii")
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "latest.enc.json"
            path.write_text(json.dumps(envelope), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "corrupt or the encryption key"):
                read_encrypted_snapshot(path, self.key)

    def test_invalid_key_length_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "exactly 32 random bytes"):
            encrypt_learning_snapshot(self.snapshot, base64.urlsafe_b64encode(b"short").decode("ascii"))


if __name__ == "__main__":
    unittest.main()
