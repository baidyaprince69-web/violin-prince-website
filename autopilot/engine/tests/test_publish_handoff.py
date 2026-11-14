"""Offline tests for YouTube publisher metadata and asset provenance."""
import sys
import tempfile
import unittest
from pathlib import Path

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

from publish_handoff import (
    build_asset_provenance,
    build_publish_manifest,
    validate_publish_metadata,
    write_handoff_files,
)


class PublishMetadataTests(unittest.TestCase):
    def test_normalizes_hashtags_tags_and_preserves_supported_upload_fields(self):
        result = validate_publish_metadata({
            "title": "Why Violin Strings Vibrate",
            "description": "A short explanation of violin acoustics.\n\nSources in the video notes.",
            "hashtags": ["#Violin", "#Music", "#Acoustics", "#violin"],
            "made_for_kids": False,
        })
        value = result["value"]
        self.assertEqual(value["title"], "Why Violin Strings Vibrate")
        self.assertEqual(value["tags"], ["Violin", "Music", "Acoustics"])
        self.assertEqual(value["category_id"], "10")
        self.assertEqual(value["default_language"], "en")
        self.assertEqual(value["privacy_status"], "public")
        self.assertIs(value["made_for_kids"], False)
        self.assertTrue(result["audience_confirmed"])
        self.assertTrue(result["valid"])

    def test_normalizes_nested_publish_metadata(self):
        result = validate_publish_metadata({
            "title": "Fallback title",
            "publish_metadata": {
                "title": "Chosen title",
                "description": "Description",
                "tags": ["Violin", "Music", "Sound"],
                "category_id": "10",
                "default_language": "en-IN",
                "privacy_status": "unlisted",
                "made_for_kids": True,
            },
        })
        self.assertEqual(result["value"]["title"], "Chosen title")
        self.assertEqual(result["value"]["default_language"], "en-IN")
        self.assertEqual(result["value"]["privacy_status"], "unlisted")
        self.assertIs(result["value"]["made_for_kids"], True)

    def test_rejects_title_over_youtube_limit(self):
        with self.assertRaisesRegex(ValueError, "title exceeds 100"):
            validate_publish_metadata({
                "title": "V" * 101,
                "description": "Description",
            })

    def test_rejects_description_over_youtube_limit(self):
        with self.assertRaisesRegex(ValueError, "description exceeds 5000"):
            validate_publish_metadata({
                "title": "Valid title",
                "description": "D" * 5001,
            })

    def test_deduplicates_and_caps_tag_count(self):
        result = validate_publish_metadata({
            "title": "Valid title",
            "description": "Description",
            "tags": [f"tag-{index}" for index in range(35)] + ["TAG-1"],
        })
        self.assertEqual(len(result["value"]["tags"]), 30)

    def test_rejects_invalid_language_and_privacy(self):
        with self.assertRaisesRegex(ValueError, "valid language tag"):
            validate_publish_metadata({
                "title": "Valid title",
                "description": "Description",
                "default_language": "english language",
            })
        with self.assertRaisesRegex(ValueError, "privacy status"):
            validate_publish_metadata({
                "title": "Valid title",
                "description": "Description",
                "privacy_status": "everyone",
            })

    def test_missing_audience_classification_uses_the_preconfirmed_channel_default(self):
        result = validate_publish_metadata({
            "title": "Valid title",
            "description": "Description",
            "tags": ["Violin", "Music", "Sound"],
        })
        self.assertTrue(result["valid"])
        self.assertTrue(result["audience_confirmed"])
        self.assertIs(result["value"]["made_for_kids"], False)

    def test_invalid_audience_value_is_not_silently_coerced(self):
        result = validate_publish_metadata({
            "title": "Valid title",
            "description": "Description",
            "tags": ["Violin", "Music", "Sound"],
            "made_for_kids": "false",
        })
        self.assertFalse(result["audience_confirmed"])
        self.assertIsNone(result["value"]["made_for_kids"])


class AssetProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.audio = self.root / "soundtrack.wav"
        self.narration = self.root / "narration.wav"
        self.video = self.root / "short.mp4"
        self.images = []
        self.audio.write_bytes(b"cc0 sample audio bytes" * 300)
        self.narration.write_bytes(b"kokoro narration bytes" * 200)
        self.video.write_bytes(b"validated h264 mp4 bytes" * 5000)
        for index in range(3):
            path = self.root / f"scene-{index + 1}.jpg"
            path.write_bytes((f"generated scene {index + 1}" * 1000).encode())
            self.images.append(path)

        self.plan = {
            "title": "How a Violin String Vibrates",
            "topic": "Violin string vibration",
            "story_type": "violin_physics",
            "made_for_kids": False,
            "narration_script": (
                "Why does a violin string vibrate? "
                "A string moves in a repeating pattern. "
                "The bridge transfers that movement to the body. "
                "The body helps create the sound we hear."
            ),
            "narration_evidence": [
                {
                    "sentence_number": 2,
                    "source_id": "S001",
                    "publisher_domain": "example.org",
                    "quote": "A string moves in a repeating pattern.",
                }
            ],
            "source_group": {"independent_publisher_count": 2},
            "quality_control": {"status": "passed"},
            "scenes": [
                {"visual_mode": "macro_3d", "image_prompt": "A macro violin string."},
                {"visual_mode": "mechanism_3d", "image_prompt": "A violin bridge cutaway."},
                {"visual_mode": "cover_performance", "image_prompt": "Violin and bow."},
            ],
        }
        self.sources = [{
            "source_id": "S001",
            "title": "How violin strings vibrate",
            "publisher_name": "Acoustics Example",
            "publisher_domain": "example.org",
            "url": "https://example.org/violin-strings",
            "published_at_utc": "2026-11-14T10:00:00Z",
        }]
        self.audio_asset = {
            "audio_source": "sampled_violin_cc0",
            "license": "CC0-1.0",
            "source_library": "VSCO 2 Community Edition",
            "attribution": "Versilian Studios",
            "sample_bank_revision": "1e4e0ca",
        }
        self.narration_info = {
            "engine": "Kokoro-82M",
            "model_license": "Apache-2.0",
            "voice_type": "synthetic_not_voice_cloned",
            "voice": "af_heart",
        }
        self.video_quality = {
            "duration_seconds": 24.0,
            "width": 720,
            "height": 1280,
            "video_codec": "h264",
            "fps": 25.0,
            "audio_sample_rate": 24000,
        }

    def tearDown(self):
        self.temp.cleanup()

    def _provenance(self, audio_asset=None):
        return build_asset_provenance(
            plan=self.plan,
            verified_sources=self.sources,
            audio_asset=audio_asset or self.audio_asset,
            audio_path=self.audio,
            narration_info=self.narration_info,
            narration_path=self.narration,
            image_paths=self.images,
            final_video_path=self.video,
            video_quality=self.video_quality,
            run_id="test-run",
        )

    def test_records_verified_claims_sources_and_asset_hashes(self):
        provenance = self._provenance()
        self.assertEqual(provenance["factual_provenance"]["status"], "passed")
        self.assertEqual(
            provenance["factual_provenance"]["sources"][0]["verification"],
            "direct_publisher_article_verified",
        )
        self.assertEqual(
            provenance["factual_provenance"]["narration_claim_evidence"][0]["verification"],
            "exact_quote_found_in_verified_publisher_article",
        )
        self.assertEqual(
            provenance["assets"]["soundtrack"]["rights_status"],
            "cc0_license_recorded_from_pinned_sample_manifest",
        )
        self.assertEqual(
            provenance["assets"]["narration"]["model_license"], "Apache-2.0"
        )
        self.assertEqual(len(provenance["assets"]["scene_images"]), 3)
        self.assertEqual(len(provenance["assets"]["scene_images"][0]["sha256"]), 64)
        self.assertTrue(provenance["synthetic_media"]["contains_synthetic_media"])

    def test_publish_manifest_is_ready_only_with_explicit_audience_setting(self):
        check = validate_publish_metadata({
            "title": self.plan["title"],
            "description": "Verified source-led music explanation.",
            "tags": ["Violin", "Music", "Acoustics"],
            "made_for_kids": False,
        })
        manifest = build_publish_manifest(
            plan=self.plan,
            metadata_check=check,
            video_quality=self.video_quality,
            provenance=self._provenance(),
            run_id="test-run",
        )
        self.assertTrue(manifest["publish_ready"])
        self.assertEqual(manifest["publisher_preflight"]["status"], "ready")
        self.assertIs(manifest["made_for_kids"], False)

    def test_missing_audience_value_uses_preconfirmed_setting_in_publish_manifest(self):
        plan = {key: value for key, value in self.plan.items() if key != "made_for_kids"}
        check = validate_publish_metadata({
            "title": plan["title"],
            "description": "Verified source-led music explanation.",
            "tags": ["Violin", "Music", "Acoustics"],
        })
        manifest = build_publish_manifest(
            plan=plan,
            metadata_check=check,
            video_quality=self.video_quality,
            provenance=self._provenance(),
            run_id="test-run",
        )
        self.assertTrue(manifest["publish_ready"])
        self.assertEqual(manifest["publisher_preflight"]["status"], "ready")
        self.assertIs(manifest["made_for_kids"], False)

    def test_writes_publish_manifest_and_asset_provenance_files(self):
        check = validate_publish_metadata({
            "title": self.plan["title"],
            "description": "Verified source-led music explanation.",
            "tags": ["Violin", "Music", "Acoustics"],
            "made_for_kids": False,
        })
        self.plan["publish_metadata"] = check["value"]
        manifest, provenance = write_handoff_files(
            self.root / "handoff",
            plan=self.plan,
            verified_sources=self.sources,
            audio_asset=self.audio_asset,
            audio_path=self.audio,
            narration_info=self.narration_info,
            narration_path=self.narration,
            image_paths=self.images,
            final_video_path=self.video,
            video_quality=self.video_quality,
            run_id="test-run",
        )
        manifest_path = self.root / "handoff" / "publish-manifest.json"
        provenance_path = self.root / "handoff" / "asset-provenance.json"
        self.assertTrue(manifest_path.is_file())
        self.assertTrue(provenance_path.is_file())
        self.assertTrue(manifest["publish_ready"])
        self.assertEqual(len(provenance["assets"]["scene_images"]), 3)

    def test_unknown_soundtrack_license_blocks_publication(self):
        check = validate_publish_metadata({
            "title": self.plan["title"],
            "description": "Verified source-led music explanation.",
            "tags": ["Violin", "Music", "Acoustics"],
            "made_for_kids": False,
        })
        manifest = build_publish_manifest(
            plan=self.plan,
            metadata_check=check,
            video_quality=self.video_quality,
            provenance=self._provenance({
                "audio_source": "uploaded_recording",
                "filename": "unknown.wav",
            }),
            run_id="test-run",
        )
        self.assertFalse(manifest["publish_ready"])
        self.assertTrue(any("Soundtrack origin" in item for item in manifest["publisher_preflight"]["blockers"]))


if __name__ == "__main__":
    unittest.main()
