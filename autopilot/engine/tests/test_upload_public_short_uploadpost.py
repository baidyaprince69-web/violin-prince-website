from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import upload_public_short_uploadpost as publisher


class PublicUploadDisabledTests(unittest.TestCase):
    def test_public_creator_approval_cannot_enable_public_uploads(self):
        with self.assertRaisesRegex(publisher.PublishBlocked, "Public YouTube publishing is disabled"):
            publisher._require_public_creator_approval()

    def test_public_upload_entrypoint_blocks_before_any_network_or_file_access(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(publisher.PublishBlocked, "Public YouTube publishing is disabled"):
                publisher.upload_public_short(
                    root / "output",
                    root / "creative_plan.json",
                    run_id="123456",
                    expected_slot_id="music-secrets",
                    production_date="2026-11-22",
                )


if __name__ == "__main__":
    unittest.main()
