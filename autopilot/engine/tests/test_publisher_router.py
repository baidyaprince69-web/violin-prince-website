"""Offline tests for the Metricool-to-direct-YouTube fallback router."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from publisher_router import (
    RouterError,
    prepare_attempt,
    route_to_youtube,
    validate_release_bundle,
)
from youtube_channel_audit import ChannelAuditError, DuplicateVideoFound


class PublisherRouterTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.release = self.root / "release"
        self.release.mkdir()
        self.video = self.release / "violin-prince-short.mp4"
        self.video.write_bytes(b"V" * 8192)
        digest = hashlib.sha256(self.video.read_bytes()).hexdigest()
        self.run_id = "44739181917"
        self.release_tag = "violin-prince-short-" + self.run_id
        self.repository = "owner/repo"
        self.request_id = "metricool-fallback-2026-11-20"
        self.request_path = self.root / "publisher-fallback-request.json"
        self.request = {
            "schema_version": 1,
            "mode": "metricool_quota_fallback",
            "request_id": self.request_id,
            "production_run_id": self.run_id,
            "release_tag": self.release_tag,
            "reason": "metricool_monthly_limit_reached",
        }
        self.request_path.write_text(json.dumps(self.request), encoding="utf-8")
        self.manifest = {
            "schema_version": 1,
            "status": "rendered",
            "run_id": self.run_id,
            "release_tag": self.release_tag,
            "public_video_url": (
                f"https://github.com/{self.repository}/releases/download/"
                f"{self.release_tag}/violin-prince-short.mp4"
            ),
            "title": "A verified Violin Prince Short",
            "description": "A factual, verified Short description.",
            "tags": ["Violin", "Music", "Acoustics"],
            "hashtags": ["#Violin", "#Music"],
            "category_id": "10",
            "default_language": "en",
            "youtube_privacy": "public",
            "made_for_kids": False,
            "contains_synthetic_media": True,
            "duration_seconds": 24,
            "format": "9:16",
            "video_type": "short",
            "sources": [
                {"title": "Publisher A", "url": "https://a.example/article"},
                {"title": "Publisher B", "url": "https://b.example/article"},
            ],
            "publish_ready": True,
            "publisher_preflight": {"status": "ready", "blockers": []},
        }
        self.provenance = {
            "schema_version": 1,
            "run_id": self.run_id,
            "factual_provenance": {
                "status": "passed",
                "independent_publisher_count": 2,
                "sources": [
                    {"source_id": "S1", "url": "https://a.example/article"},
                    {"source_id": "S2", "url": "https://b.example/article"},
                ],
                "narration_claim_evidence": [
                    {"sentence_number": 2},
                    {"sentence_number": 3},
                    {"sentence_number": 4},
                ],
            },
            "synthetic_media": {"contains_synthetic_media": True},
            "assets": {
                "final_video": {
                    "sha256": digest,
                    "size_bytes": self.video.stat().st_size,
                }
            },
        }
        (self.release / "publish-manifest.json").write_text(
            json.dumps(self.manifest), encoding="utf-8"
        )
        (self.release / "asset-provenance.json").write_text(
            json.dumps(self.provenance), encoding="utf-8"
        )
        self.audit_patcher = patch(
            "publisher_router.assert_title_absent",
            return_value={
                "status": "passed",
                "match_count": 0,
                "channel_id": "UCGCfZij4Fn3Ga2j2HiCT45w",
                "uploads_checked_pages": 4,
                "uploads_examined": 173,
            },
        )
        self.audit_patcher.start()

    def tearDown(self):
        self.audit_patcher.stop()
        self.temporary.cleanup()

    def test_valid_release_bundle_uses_exact_manifest_metadata(self):
        manifest, plan, video_path = validate_release_bundle(
            self.request, self.release, self.repository
        )
        self.assertEqual(manifest["run_id"], self.run_id)
        self.assertEqual(video_path, self.video)
        self.assertEqual(plan["publish_metadata"]["title"], self.manifest["title"])
        self.assertEqual(plan["publish_metadata"]["tags"], ["Violin", "Music", "Acoustics"])
        self.assertIs(plan["publish_metadata"]["made_for_kids"], False)
        self.assertIs(plan["contains_synthetic_media"], True)

    def test_non_quota_fallback_request_is_rejected(self):
        request = dict(self.request, reason="metricool_temporary_network_error")
        with self.assertRaisesRegex(RouterError, "confirmed Metricool monthly-limit"):
            validate_release_bundle(request, self.release, self.repository)

    def test_manifest_url_must_match_the_exact_release(self):
        self.manifest["public_video_url"] = "https://example.com/another-video.mp4"
        (self.release / "publish-manifest.json").write_text(
            json.dumps(self.manifest), encoding="utf-8"
        )
        with self.assertRaisesRegex(RouterError, "does not identify this exact"):
            validate_release_bundle(self.request, self.release, self.repository)

    def test_hash_mismatch_blocks_publication(self):
        self.provenance["assets"]["final_video"]["sha256"] = "0" * 64
        (self.release / "asset-provenance.json").write_text(
            json.dumps(self.provenance), encoding="utf-8"
        )
        with self.assertRaisesRegex(RouterError, "SHA-256"):
            validate_release_bundle(self.request, self.release, self.repository)

    def test_guard_writes_durable_attempt_marker(self):
        result = prepare_attempt(
            self.request_path, self.release, self.repository, "123456-1"
        )
        self.assertFalse(result["skip"])
        marker = json.loads(
            (self.release / "publisher-attempt.json").read_text(encoding="utf-8")
        )
        self.assertEqual(marker["status"], "attempting")
        self.assertEqual(marker["attempt_id"], "123456-1")
        self.assertEqual(marker["youtube_channel_audit"]["status"], "passed")
        self.assertEqual(marker["youtube_channel_audit"]["uploads_checked_pages"], 4)

    def test_duplicate_title_blocks_before_attempt_marker_is_created(self):
        with patch(
            "publisher_router.assert_title_absent",
            side_effect=DuplicateVideoFound([{
                "video_id": "existingVideo123",
                "title": self.manifest["title"],
                "published_at": "2026-11-20T18:53:17Z",
            }]),
        ):
            with self.assertRaisesRegex(RouterError, "already exists"):
                prepare_attempt(
                    self.request_path, self.release, self.repository, "123456-1"
                )
        self.assertFalse((self.release / "publisher-attempt.json").exists())

    def test_incomplete_channel_audit_blocks_before_attempt_marker(self):
        with patch(
            "publisher_router.assert_title_absent",
            side_effect=ChannelAuditError("YouTube returned HTTP 403"),
        ):
            with self.assertRaisesRegex(RouterError, "duplicate verification failed"):
                prepare_attempt(
                    self.request_path, self.release, self.repository, "123456-1"
                )
        self.assertFalse((self.release / "publisher-attempt.json").exists())

    def test_old_attempt_marker_blocks_a_new_workflow_attempt(self):
        prepare_attempt(self.request_path, self.release, self.repository, "123456-1")
        with self.assertRaisesRegex(RouterError, "outcome may be unknown"):
            prepare_attempt(self.request_path, self.release, self.repository, "123456-2")

    def test_existing_receipt_prevents_duplicate_publication(self):
        (self.release / "publisher-receipt.json").write_text(
            json.dumps({
                "status": "uploaded",
                "release_tag": self.release_tag,
                "youtube_video_id": "video123",
            }),
            encoding="utf-8",
        )
        result = prepare_attempt(
            self.request_path, self.release, self.repository, "123456-1"
        )
        self.assertTrue(result["skip"])
        self.assertFalse((self.release / "publisher-attempt.json").exists())

    @patch("publisher_router.youtube_upload")
    def test_direct_upload_writes_verified_receipt(self, upload):
        upload.return_value = {
            "platform": "youtube",
            "ok": True,
            "id": "youtubeVideo123",
            "url": "https://www.youtube.com/watch?v=youtubeVideo123",
        }
        prepare_attempt(self.request_path, self.release, self.repository, "123456-1")
        receipt = route_to_youtube(
            self.request_path, self.release, self.repository, "123456-1"
        )
        self.assertEqual(receipt["status"], "uploaded")
        self.assertEqual(receipt["provider"], "youtube_data_api")
        self.assertEqual(receipt["youtube_video_id"], "youtubeVideo123")
        plan = upload.call_args.args[1]
        self.assertEqual(plan["publish_metadata"]["privacy_status"], "public")

    @patch("publisher_router.youtube_upload")
    def test_uncertain_upload_failure_persists_no_retry_receipt(self, upload):
        upload.side_effect = TimeoutError("connection ended after upload request")
        prepare_attempt(self.request_path, self.release, self.repository, "123456-1")
        with self.assertRaisesRegex(RouterError, "outcome is uncertain"):
            route_to_youtube(
                self.request_path, self.release, self.repository, "123456-1"
            )
        receipt = json.loads(
            (self.release / "publisher-receipt.json").read_text(encoding="utf-8")
        )
        self.assertEqual(receipt["status"], "outcome_unknown")
        self.assertIs(receipt["retry_allowed"], False)


if __name__ == "__main__":
    unittest.main()
