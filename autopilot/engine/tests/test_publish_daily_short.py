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
                "scene_images": [
                    {
                        "origin": "locally_generated_vector_artwork",
                        "provider": "Violin Prince local vector illustrator",
                        "model": "violin-prince-vector-illustrator-v1",
                        "rights_status": "original_locally_generated_vector_artwork",
                        "sha256": f"{index + 1:064x}",
                    }
                    for index in range(3)
                ],
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

    def test_unverified_scene_illustration_provider_is_rejected(self):
        self.provenance["assets"]["scene_images"][0]["provider"] = "Cloudflare Workers AI"
        (self.output / "asset-provenance.json").write_text(json.dumps(self.provenance), encoding="utf-8")
        with self.assertRaisesRegex(daily.PublishBlocked, "Scene illustration provenance"):
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


    def _make_procedural_bundle(self):
        shots = [
            {
                "asset_type": "procedural_scene",
                "scene_number": index + 1,
                "shot_id": f"shot-{index + 1:02d}",
                "environment": "laboratory",
                "animated_object_count": 3,
                "character_visible": index < 5,
                "origin": "native_motion_hyperframes_procedural_scene",
                "provider": "Violin Prince procedural 2D renderer",
                "rights_status": "original_procedural_vector_animation",
            }
            for index in range(8)
        ]
        self.manifest.update({
            "render_mode": "procedural_2d",
            "shot_count": 8,
            "duration_seconds": 32.0,
        })
        self.provenance["assets"].update({
            "render_mode": "procedural_2d",
            "scene_images": [],
            "procedural_scenes": shots,
            "character_rig": {
                "character_count": 1,
                "approval_status": "approved",
                "bundle_sha256": "a" * 64,
                "approval_sha256": "b" * 64,
            },
            "music_sync": {
                "status": "passed",
                "motion_report_status": "passed",
                "cue_count": 2,
                "rendered_motion_track_count": 2,
                "measured_audio_sync_verified": True,
                "cues": [
                    {"time_seconds": 8.0, "event": "First beat", "reason": "The first reveal lands.", "timing_source": "decoded_audio_beat_grid", "alignment_error_seconds": 0.0},
                    {"time_seconds": 16.0, "event": "Second beat", "reason": "The second reveal lands.", "timing_source": "decoded_audio_beat_grid", "alignment_error_seconds": 0.02},
                ],
            },
        })
        self.manifest["music_sync_event_count"] = 2
        self.quality["duration_seconds"] = 32.0
        (self.output / "publish-manifest.json").write_text(json.dumps(self.manifest), encoding="utf-8")
        (self.output / "asset-provenance.json").write_text(json.dumps(self.provenance), encoding="utf-8")

    def test_public_publisher_accepts_procedural_animation_with_no_scene_images(self):
        self._make_procedural_bundle()
        manifest, provenance, _plan, video, _audit = self.validate()
        self.assertEqual(manifest["render_mode"], "procedural_2d")
        self.assertEqual(len(provenance["assets"]["procedural_scenes"]), 8)
        self.assertEqual(provenance["assets"]["scene_images"], [])
        self.assertEqual(video, self.video)

    def test_procedural_publisher_rejects_generated_still_image_fallback(self):
        self._make_procedural_bundle()
        self.provenance["assets"]["scene_images"] = [{
            "origin": "locally_generated_vector_artwork",
            "provider": "Violin Prince local vector illustrator",
            "model": "violin-prince-vector-illustrator-v1",
            "rights_status": "original_locally_generated_vector_artwork",
            "sha256": "c" * 64,
        }]
        (self.output / "asset-provenance.json").write_text(json.dumps(self.provenance), encoding="utf-8")
        with self.assertRaisesRegex(daily.PublishBlocked, "must not contain generated scene-image assets"):
            self.validate()

    def test_procedural_publisher_requires_creator_approved_rig_fingerprint(self):
        self._make_procedural_bundle()
        self.provenance["assets"]["character_rig"]["bundle_sha256"] = ""
        (self.output / "asset-provenance.json").write_text(json.dumps(self.provenance), encoding="utf-8")
        with self.assertRaisesRegex(daily.PublishBlocked, "creator-approved asset fingerprint"):
            self.validate()

    def test_procedural_publisher_rejects_missing_music_sync_motion_tracks(self):
        self._make_procedural_bundle()
        self.provenance["assets"]["music_sync"]["rendered_motion_track_count"] = 1
        (self.output / "asset-provenance.json").write_text(json.dumps(self.provenance), encoding="utf-8")
        with self.assertRaisesRegex(daily.PublishBlocked, "measured music-sync timing"):
            self.validate()

    def test_procedural_publisher_rejects_guessed_music_timing(self):
        self._make_procedural_bundle()
        self.provenance["assets"]["music_sync"]["cues"][0]["timing_source"] = "estimated_by_model"
        (self.output / "asset-provenance.json").write_text(json.dumps(self.provenance), encoding="utf-8")
        with self.assertRaisesRegex(daily.PublishBlocked, "not ordered, measured"):
            self.validate()

    def test_procedural_publisher_accepts_up_to_sixty_seconds(self):
        self._make_procedural_bundle()
        self.quality["duration_seconds"] = 60.0
        manifest, *_ = self.validate()
        self.assertEqual(manifest["duration_seconds"], 32.0)

    def test_procedural_publisher_rejects_over_sixty_seconds(self):
        self._make_procedural_bundle()
        self.quality["duration_seconds"] = 60.5
        with self.assertRaisesRegex(daily.PublishBlocked, "Shorts format contract"):
            self.validate()


class PrivatePreviewPublisherTests(unittest.TestCase):
    def setUp(self):
        self.fixture = DailyPublicPublisherTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.fixture.manifest["youtube_privacy"] = "private"
        self.fixture.plan["publish_metadata"] = {"privacy_status": "private"}
        self.fixture.plan_path.write_text(json.dumps(self.fixture.plan), encoding="utf-8")
        (self.fixture.output / "publish-manifest.json").write_text(
            json.dumps(self.fixture.manifest), encoding="utf-8"
        )

    def _environment(self, privacy="private"):
        return patch.dict(os.environ, {
            "GITHUB_REF_NAME": "main",
            "YOUTUBE_PRIVACY_STATUS": privacy,
            "YOUTUBE_EXPECTED_CHANNEL_ID": "UCGCfZij4Fn3Ga2j2HiCT45w",
        }, clear=False)

    def test_private_bundle_validation_accepts_only_explicit_private_metadata(self):
        manifest, _provenance, plan, video, audit = daily.validate_daily_bundle(
            self.fixture.output,
            self.fixture.plan_path,
            run_id=self.fixture.run_id,
            expected_slot_id=self.fixture.slot_id,
            production_date="2026-11-21",
            video_probe=self.fixture.quality,
            expected_privacy_status="private",
        )
        self.assertEqual(manifest["youtube_privacy"], "private")
        self.assertEqual(plan["publish_metadata"]["privacy_status"], "private")
        self.assertEqual(video, self.fixture.video)
        self.assertEqual(audit["sha256"], self.fixture.provenance["assets"]["final_video"]["sha256"])

    @patch("upload_private_preview._git_commit")
    @patch("upload_private_preview.youtube_upload")
    @patch("upload_private_preview.assert_title_absent")
    @patch("publish_daily_short.probe_video")
    def test_private_upload_persists_attempt_and_receipt_only_after_private_confirmation(
        self, probe, duplicate_audit, upload, commit
    ):
        import upload_private_preview as preview

        probe.return_value = self.fixture.quality
        duplicate_audit.return_value = {
            "status": "passed", "match_count": 0,
            "channel_id": "UCGCfZij4Fn3Ga2j2HiCT45w",
            "uploads_checked_pages": 3, "uploads_examined": 120,
        }
        upload.return_value = {
            "ok": True, "id": "privateVideoId123",
            "url": "https://www.youtube.com/watch?v=privateVideoId123",
            "privacy_status": "private",
        }
        with patch.object(preview, "ROOT", self.fixture.root), self._environment():
            receipt = preview.upload_private_preview(
                self.fixture.output, self.fixture.plan_path,
                run_id=self.fixture.run_id,
                expected_slot_id=self.fixture.slot_id,
                production_date="2026-11-21",
            )
        self.assertEqual(receipt["status"], "uploaded_private")
        self.assertEqual(receipt["privacy_status"], "private")
        self.assertNotIn("youtube_video_id", receipt)
        self.assertNotIn("youtube_video_url", receipt)
        attempts = list((self.fixture.root / ".autopilot/private-preview-attempts").glob("*.json"))
        receipts = list((self.fixture.root / ".autopilot/private-preview-receipts").glob("*.json"))
        self.assertEqual(len(attempts), 1)
        self.assertEqual(len(receipts), 1)
        attempt_record = json.loads(attempts[0].read_text(encoding="utf-8"))
        self.assertNotIn("youtube_video_id", attempt_record)
        self.assertNotIn("youtube_video_url", attempt_record)
        self.assertEqual(commit.call_count, 2)
        self.assertEqual(upload.call_args.args[0], self.fixture.video)

    @patch("upload_private_preview._git_commit")
    @patch("upload_private_preview.youtube_upload")
    @patch("upload_private_preview.assert_title_absent")
    @patch("publish_daily_short.probe_video")
    def test_wrong_visibility_response_is_recorded_and_never_retried(
        self, probe, duplicate_audit, upload, commit
    ):
        import upload_private_preview as preview

        probe.return_value = self.fixture.quality
        duplicate_audit.return_value = {
            "status": "passed", "match_count": 0,
            "channel_id": "UCGCfZij4Fn3Ga2j2HiCT45w",
            "uploads_checked_pages": 3, "uploads_examined": 120,
        }
        upload.return_value = {
            "ok": True, "id": "wrongVisibilityVideo",
            "url": "https://www.youtube.com/watch?v=wrongVisibilityVideo",
            "privacy_status": "public",
        }
        with patch.object(preview, "ROOT", self.fixture.root), self._environment():
            with self.assertRaisesRegex(preview.PublishBlocked, "did not confirm private visibility"):
                preview.upload_private_preview(
                    self.fixture.output, self.fixture.plan_path,
                    run_id=self.fixture.run_id,
                    expected_slot_id=self.fixture.slot_id,
                    production_date="2026-11-21",
                )
        receipts = list((self.fixture.root / ".autopilot/private-preview-receipts").glob("*.json"))
        self.assertEqual(len(receipts), 1)
        receipt = json.loads(receipts[0].read_text(encoding="utf-8"))
        self.assertEqual(receipt["status"], "uploaded_visibility_mismatch")
        self.assertIs(receipt["retry_allowed"], False)
        receipt_text = receipts[0].read_text(encoding="utf-8")
        self.assertNotIn("wrongVisibilityVideo", receipt_text)
        self.assertNotIn("youtube_video_url", receipt)
        attempt_files = list((self.fixture.root / ".autopilot/private-preview-attempts").glob("*.json"))
        self.assertEqual(len(attempt_files), 1)
        attempt_text = attempt_files[0].read_text(encoding="utf-8")
        self.assertNotIn("wrongVisibilityVideo", attempt_text)
        self.assertNotIn("youtube_video_url", attempt_text)
        upload.assert_called_once()
        self.assertEqual(commit.call_count, 2)

    @patch("publish_daily_short.probe_video")
    @patch("upload_private_preview.youtube_upload")
    def test_existing_attempt_without_receipt_blocks_automatic_retry(self, upload, probe):
        import upload_private_preview as preview

        probe.return_value = self.fixture.quality
        identity = f"{self.fixture.run_id}-{self.fixture.slot_id}"
        attempt_dir = self.fixture.root / ".autopilot/private-preview-attempts"
        attempt_dir.mkdir(parents=True)
        (attempt_dir / f"{identity}.json").write_text(
            json.dumps({"status": "attempting"}), encoding="utf-8"
        )
        with patch.object(preview, "ROOT", self.fixture.root), self._environment():
            with self.assertRaisesRegex(preview.PublishBlocked, "automatic retries are blocked"):
                preview.upload_private_preview(
                    self.fixture.output, self.fixture.plan_path,
                    run_id=self.fixture.run_id,
                    expected_slot_id=self.fixture.slot_id,
                    production_date="2026-11-21",
                )
        upload.assert_not_called()

    @patch("upload_private_preview.youtube_upload")
    def test_public_visibility_cannot_be_requested_from_private_uploader(self, upload):
        import upload_private_preview as preview

        with patch.dict(os.environ, {
            "GITHUB_REF_NAME": "main",
            "YOUTUBE_PRIVACY_STATUS": "public",
            "YOUTUBE_EXPECTED_CHANNEL_ID": "UCGCfZij4Fn3Ga2j2HiCT45w",
        }, clear=False):
            with self.assertRaisesRegex(preview.PublishBlocked, "explicitly set to private"):
                preview.upload_private_preview(
                    self.fixture.output, self.fixture.plan_path,
                    run_id=self.fixture.run_id,
                    expected_slot_id=self.fixture.slot_id,
                    production_date="2026-11-21",
                )
        upload.assert_not_called()


class DurableGitCommitTests(unittest.TestCase):
    def _run_with_return_codes(self, return_codes):
        commands = []
        remaining = iter(return_codes)

        def fake_run(command, **kwargs):
            commands.append(list(command))
            code = next(remaining, 0)
            return type("Completed", (), {"returncode": code, "stdout": "", "stderr": ""})()

        return commands, fake_run

    def test_commit_stages_and_commits_receipt_before_fetch_and_rebase(self):
        commands, fake_run = self._run_with_return_codes([0, 0, 0, 1, 0, 0, 0, 0])
        paths = [".autopilot/public-youtube-attempts/test.json", ".autopilot/public-youtube-receipts/test.json"]
        with patch.object(daily.subprocess, "run", side_effect=fake_run):
            daily._git_commit(paths, "Record public upload receipt")
        add_index = commands.index(["git", "add", "--", *paths])
        commit_index = commands.index(["git", "commit", "-m", "Record public upload receipt"])
        fetch_index = commands.index(["git", "fetch", "origin", "main"])
        rebase_index = commands.index(["git", "rebase", "origin/main"])
        push_index = commands.index(["git", "push", "origin", "HEAD:main"])
        self.assertLess(add_index, commit_index)
        self.assertLess(commit_index, fetch_index)
        self.assertLess(fetch_index, rebase_index)
        self.assertLess(rebase_index, push_index)

    def test_failed_push_retries_only_after_fetch_and_rebase(self):
        commands, fake_run = self._run_with_return_codes([0, 0, 0, 1, 0, 0, 0, 1, 0, 0, 0])
        with patch.object(daily.subprocess, "run", side_effect=fake_run):
            daily._git_commit([".autopilot/public-youtube-receipts/test.json"], "Record receipt")
        pushes = [index for index, command in enumerate(commands) if command[:2] == ["git", "push"]]
        self.assertEqual(len(pushes), 2)
        first_fetch = commands.index(["git", "fetch", "origin", "main"], 0)
        first_rebase = commands.index(["git", "rebase", "origin/main"], first_fetch)
        self.assertLess(first_rebase, pushes[0])
        retry_fetch = commands.index(["git", "fetch", "origin", "main"], pushes[0])
        retry_rebase = commands.index(["git", "rebase", "origin/main"], retry_fetch)
        self.assertLess(pushes[0], retry_fetch)
        self.assertLess(retry_fetch, retry_rebase)
        self.assertLess(retry_rebase, pushes[1])

    def test_no_staged_receipt_stops_before_fetch_or_push(self):
        commands, fake_run = self._run_with_return_codes([0, 0, 0, 0])
        with patch.object(daily.subprocess, "run", side_effect=fake_run):
            with self.assertRaisesRegex(daily.PublishBlocked, "No durable publication record was staged"):
                daily._git_commit([".autopilot/public-youtube-receipts/test.json"], "Record receipt")
        self.assertFalse(any(command[:2] in (["git", "fetch"], ["git", "rebase"], ["git", "push"]) for command in commands))


if __name__ == "__main__":
    unittest.main()
