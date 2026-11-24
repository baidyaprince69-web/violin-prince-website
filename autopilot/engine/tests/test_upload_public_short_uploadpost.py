from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import upload_public_short_uploadpost as publisher


class PublicUploadApprovalTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.approval_path = self.root / "autopilot" / "engine" / "illustration-approval.json"
        self.approval_path.parent.mkdir(parents=True)
        self.approval = {
            "schema_version": 1,
            "status": "approved_for_publication",
            "provider": "local_vector",
            "scope": "public_youtube",
            "publishing_enabled": True,
            "creator_publication_approval": {
                "approved": True,
                "platform": "youtube",
                "privacy_status": "public",
                "no_private_preview_required": True,
                "approval_statement": "Creator explicitly approves public YouTube publishing.",
            },
        }
        self.approval_path.write_text(json.dumps(self.approval), encoding="utf-8")
        self.root_patch = patch.object(publisher, "ROOT", self.root)
        self.root_patch.start()

    def tearDown(self):
        self.root_patch.stop()
        self.temp.cleanup()


    def test_blocks_same_mp4_hash_in_another_slot_receipt(self):
        history = self.root / ".autopilot" / "public-youtube-receipts"
        history.mkdir(parents=True)
        (history / "2026-11-21-production-tech.json").write_text(
            json.dumps({"status": "uploaded_public", "sha256": "abc123"}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(publisher.PublishBlocked, "exact MP4 asset already appears"):
            publisher._reject_reused_asset_hash("abc123", "2026-11-22-melody-stories")

    def test_blocks_same_mp4_hash_in_an_uncertain_attempt(self):
        history = self.root / ".autopilot" / "public-youtube-attempts"
        history.mkdir(parents=True)
        (history / "2026-11-21-production-tech.json").write_text(
            json.dumps({"status": "outcome_unknown", "sha256": "abc123"}),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(publisher.PublishBlocked, "exact MP4 asset already appears"):
            publisher._reject_reused_asset_hash("abc123", "2026-11-22-melody-stories")

    def test_ignores_same_identity_and_different_media_hash(self):
        history = self.root / ".autopilot" / "public-youtube-receipts"
        history.mkdir(parents=True)
        (history / "2026-11-22-melody-stories.json").write_text(
            json.dumps({"status": "uploaded_public", "sha256": "abc123"}),
            encoding="utf-8",
        )
        (history / "2026-11-21-production-tech.json").write_text(
            json.dumps({"status": "uploaded_public", "sha256": "different"}),
            encoding="utf-8",
        )
        publisher._reject_reused_asset_hash("abc123", "2026-11-22-melody-stories")
        publisher._reject_reused_asset_hash("new-hash", "2026-11-23-melody-stories")

    def test_corrupt_public_upload_history_fails_closed(self):
        history = self.root / ".autopilot" / "public-youtube-attempts"
        history.mkdir(parents=True)
        (history / "broken.json").write_text("{", encoding="utf-8")
        with self.assertRaisesRegex(publisher.PublishBlocked, "unreadable record"):
            publisher._reject_reused_asset_hash("abc123", "2026-11-22-melody-stories")
    def test_accepts_explicit_public_youtube_approval(self):
        result = publisher._require_public_creator_approval()
        self.assertEqual(result["platform"], "youtube")
        self.assertEqual(result["privacy_status"], "public")

    def test_rejects_preview_only_scope(self):
        self.approval["status"] = "approved_for_preview"
        self.approval["scope"] = "preview_video_only"
        self.approval["publishing_enabled"] = False
        self.approval_path.write_text(json.dumps(self.approval), encoding="utf-8")
        with self.assertRaisesRegex(publisher.PublishBlocked, "does not explicitly authorize public publishing"):
            publisher._require_public_creator_approval()

    def test_rejects_missing_no_private_preview_approval(self):
        self.approval["creator_publication_approval"]["no_private_preview_required"] = False
        self.approval_path.write_text(json.dumps(self.approval), encoding="utf-8")
        with self.assertRaisesRegex(publisher.PublishBlocked, "does not explicitly authorize public publishing"):
            publisher._require_public_creator_approval()


if __name__ == "__main__":
    unittest.main()
