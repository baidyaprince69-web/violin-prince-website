"""Offline tests for direct public YouTube publication of daily Shorts."""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import publish_daily_short as daily


class DailyPublicPublisherTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = self.root / "output"
        self.output.mkdir()
        self.plan_path = self.root / "creative_plan.json"
        self.video = self.output / "violin-prince-short.mp4"
        self.video.write_bytes(b"test h264 mp4 payload" * 1000)
        digest = hashlib.sha256(self.video.read_bytes()).hexdigest()
        size = self.video.stat().st_size
        self.run_id = "1234567890"
        self.slot_id = "production-tech"
        self.title = "One Sample, Thirty Sound Modes"
        self.script = (
            "What if one recording could become a playable instrument? "
            "Steinberg’s free Chromaspheres turns samples into sounds. "
            "Four engines wavetable granular spectral and sample offer thirty modes. "
            "It’s a sound-design tool, not an automatic finished song."
        )
        self.plan = {
            "production_date": "2026-11-21",
            "slot_id": self.slot_id,
            "title": self.title,
            "narration_script": self.script,
            "sources": [
                {"source_id": "S001", "publisher_domain": "production-expert.com"},
                {"source_id": "S002", "publisher_domain": "synth-news.com"},
            ],
        }
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        self.manifest = {
            "schema_version": 1,
            "status": "rendered",
            "run_id": self.run_id,
            "title": self.title,
            "description": "A sourced explainer about sample-based synthesis.",
            "tags": ["Violin", "Synthesis", "Music Technology"],
            "category_id": "10",
            "default_language": "en",
            "youtube_privacy": "public",
            "made_for_kids": False,
            "contains_synthetic_media": True,
            "duration_seconds": 24.0,
            "format": "9:16",
            "video_type": "short",
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
                    {"source_id": "S001", "publisher_domain": "production-expert.com"},
                    {"source_id": "S002", "publisher_domain": "synth-news.com"},
                ],
                "narration_claim_evidence": [
                    {"sentence_number": 2, "source_id": "S001"},
                    {"sentence_number": 3, "source_id": "S002"},
                    {"sentence_number": 4, "source_id": "S002"},
                ],
            },
            "assets": {
                "soundtrack": {"rights_status": "cc0_license_recorded_from_pinned_sample_manifest"},
                "final_video": {
                    "sha256": digest,
                    "size_bytes": size,
                    "quality_validation": {
                        "width": 720, "height": 1280, "video_codec": "h264",
                        "duration_seconds": 24.0, "audio_sample_rate": 24000,
                    },
                },
            },
            "synthetic_media": {"contains_synthetic_media": True},
        }
        (self.output / "publish-manifest.json").write_text(
            json.dumps(self.manifest), encoding="utf-8"
        )
        (self.output / "asset-provenance.json").write_text(
            json.dumps(self.provenance), encoding="utf-8"
        )
        self.quality = {
            "status": "passed",
            "duration_seconds": 24.0,
            "width": 720,
            "height": 1280,
            "video_codec": "h264",
            "audio_sample_rate": 24000,
        }

    def tearDown(self):
        self.temp.cleanup()

    def validate(self):
        return daily.validate_daily_bundle(
            self.output,
            self.plan_path,
            run_id=self.run_id,
            expected_slot_id=self.slot_id,
            production_date="2026-11-21",
            video_probe=self.quality,
        )

    def test_valid_public_release_bundle_is_accepted(self):
        manifest, provenance, plan, video, audit = self.validate()
        self.assertEqual(manifest["title"], self.title)
        self.assertEqual(video, self.video)
        self.assertEqual(plan["publish_metadata"]["privacy_status"], "public")
        self.assertIs(plan["publish_metadata"]["made_for_kids"], False)
        self.assertTrue(plan["contains_synthetic_media"])
        self.assertEqual(audit["sha256"], self.provenance["assets"]["final_video"]["sha256"])

    def test_private_visibility_is_rejected(self):
        self.manifest["youtube_privacy"] = "private"
        (self.output / "publish-manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        with self.assertRaisesRegex(daily.PublishBlocked, "public YouTube visibility"):
            self.validate()

    def test_missing_independent_source_evidence_is_rejected(self):
        self.provenance["factual_provenance"]["independent_publisher_count"] = 1
        (self.output / "asset-provenance.json").write_text(json.dumps(self.provenance), encoding="utf-8")
        with self.assertRaisesRegex(daily.PublishBlocked, "two independent publisher sources"):
            self.validate()

    def test_hash_mismatch_is_rejected(self):
        self.provenance["assets"]["final_video"]["sha256"] = "0" * 64
        (self.output / "asset-provenance.json").write_text(json.dumps(self.provenance), encoding="utf-8")
        with self.assertRaisesRegex(daily.PublishBlocked, "SHA-256"):
            self.validate()

    def test_bad_narration_contract_is_rejected(self):
        self.plan["narration_script"] = "Only one short sentence."
        self.plan_path.write_text(json.dumps(self.plan), encoding="utf-8")
        with self.assertRaisesRegex(daily.PublishBlocked, "35-word/four-sentence"):
            self.validate()

    @patch("publish_daily_short._git_commit")
    @patch("publish_daily_short.youtube_upload")
    @patch("publish_daily_short.assert_title_absent")
    @patch("publish_daily_short.probe_video")
    def test_public_upload_saves_attempt_and_success_receipt(
        self, probe, duplicate_audit, upload, commit
    ):
        probe.return_value = self.quality
        duplicate_audit.return_value = {
            "status": "passed", "match_count": 0,
            "channel_id": "UCGCfZij4Fn3Ga2j2HiCT45w",
            "uploads_checked_pages": 3, "uploads_examined": 120,
        }
        upload.return_value = {
            "ok": True, "id": "publicVideoId123",
            "url": "https://www.youtube.com/watch?v=publicVideoId123",
            "privacy_status": "public",
        }
        with patch.object(daily, "ROOT", self.root), patch.dict(os.environ, {
            "GITHUB_REF_NAME": "main",
            "YOUTUBE_PRIVACY_STATUS": "public",
            "YOUTUBE_EXPECTED_CHANNEL_ID": "UCGCfZij4Fn3Ga2j2HiCT45w",
        }, clear=False):
            receipt = daily.publish_daily_short(
                self.output, self.plan_path,
                run_id=self.run_id,
                expected_slot_id=self.slot_id,
                production_date="2026-11-21",
            )
        self.assertEqual(receipt["status"], "uploaded")
        self.assertEqual(receipt["privacy_status"], "public")
        self.assertEqual(receipt["youtube_video_id"], "publicVideoId123")
        attempts = list((self.root / ".autopilot/publication-attempts").glob("*.json"))
        receipts = list((self.root / ".autopilot/publication-receipts").glob("*.json"))
        self.assertEqual(len(attempts), 1)
        self.assertEqual(len(receipts), 1)
        self.assertEqual(commit.call_count, 2)
        self.assertEqual(upload.call_args.args[0], self.video)

    @patch("publish_daily_short._git_commit")
    @patch("publish_daily_short.youtube_upload")
    @patch("publish_daily_short.assert_title_absent")
    @patch("publish_daily_short.probe_video")
    def test_non_public_response_is_recorded_and_never_reported_as_published(
        self, probe, duplicate_audit, upload, commit
    ):
        probe.return_value = self.quality
        duplicate_audit.return_value = {
            "status": "passed", "match_count": 0,
            "channel_id": "UCGCfZij4Fn3Ga2j2HiCT45w",
            "uploads_checked_pages": 3, "uploads_examined": 120,
        }
        upload.return_value = {
            "ok": True, "id": "videoWithWrongPrivacy",
            "url": "https://www.youtube.com/watch?v=videoWithWrongPrivacy",
            "privacy_status": "private",
        }
        with patch.object(daily, "ROOT", self.root), patch.dict(os.environ, {
            "GITHUB_REF_NAME": "main",
            "YOUTUBE_PRIVACY_STATUS": "public",
            "YOUTUBE_EXPECTED_CHANNEL_ID": "UCGCfZij4Fn3Ga2j2HiCT45w",
        }, clear=False):
            with self.assertRaisesRegex(daily.PublishBlocked, "did not confirm public visibility"):
                daily.publish_daily_short(
                    self.output, self.plan_path,
                    run_id=self.run_id,
                    expected_slot_id=self.slot_id,
                    production_date="2026-11-21",
                )
        attempts = list((self.root / ".autopilot/publication-attempts").glob("*.json"))
        receipts = list((self.root / ".autopilot/publication-receipts").glob("*.json"))
        self.assertEqual(len(attempts), 1)
        self.assertEqual(len(receipts), 1)
        receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "uploaded_visibility_mismatch")
        self.assertIs(receipt["retry_allowed"], False)
        self.assertEqual(commit.call_count, 2)

    @patch("publish_daily_short.assert_title_absent", side_effect=daily.DuplicateVideoFound([
        {"video_id": "existing", "title": "One Sample, Thirty Sound Modes", "published_at": ""}
    ]))
    @patch("publish_daily_short.youtube_upload")
    @patch("publish_daily_short._git_commit")
    @patch("publish_daily_short.probe_video")
    def test_duplicate_title_blocks_before_upload_and_marker(self, probe, commit, upload, duplicate_audit):
        probe.return_value = self.quality
        with patch.object(daily, "ROOT", self.root), patch.dict(os.environ, {
            "GITHUB_REF_NAME": "main",
            "YOUTUBE_PRIVACY_STATUS": "public",
            "YOUTUBE_EXPECTED_CHANNEL_ID": "UCGCfZij4Fn3Ga2j2HiCT45w",
        }, clear=False):
            with self.assertRaisesRegex(daily.PublishBlocked, "already exists"):
                daily.publish_daily_short(
                    self.output, self.plan_path,
                    run_id=self.run_id,
                    expected_slot_id=self.slot_id,
                    production_date="2026-11-21",
                )
        upload.assert_not_called()
        commit.assert_not_called()


if __name__ == "__main__":
    unittest.main()
