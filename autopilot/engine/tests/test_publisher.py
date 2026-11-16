"""Offline tests for the explicit GitHub Actions YouTube publisher."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import publisher  # noqa: E402


class PublisherTests(unittest.TestCase):
    def test_caption_prefers_validated_publish_metadata(self):
        plan = {
            "title": "Fallback",
            "description": "Fallback description",
            "publish_metadata": {
                "title": "Approved title",
                "description": "Approved source-linked description",
                "tags": ["violin", "audio"],
            },
            "sources": [{"publisher_domain": "example.com", "url": "https://example.com/article"}],
        }
        self.assertEqual(publisher.make_caption(plan), "Approved source-linked description")

    def test_youtube_upload_requires_its_separate_enable_switch(self):
        with patch.dict(os.environ, {
            "PUBLISH_ENABLED": "true",
            "YOUTUBE_PUBLISH_ENABLED": "false",
            "PUBLISH_DESTINATIONS": "youtube",
        }, clear=True), patch.object(publisher, "youtube_upload") as upload:
            result = publisher.publish_all(Path("not-used.mp4"), "", {})
        self.assertFalse(result["all_succeeded"])
        self.assertEqual(result["results"], [])
        self.assertIn("YOUTUBE_PUBLISH_ENABLED is false", result["failures"][0]["error"])
        upload.assert_not_called()

    def test_publish_all_calls_only_selected_youtube_destination(self):
        with patch.dict(os.environ, {
            "PUBLISH_ENABLED": "true",
            "YOUTUBE_PUBLISH_ENABLED": "true",
            "PUBLISH_DESTINATIONS": "youtube",
        }, clear=True), patch.object(
            publisher, "youtube_upload",
            return_value={"platform": "youtube", "ok": True, "id": "video123", "url": "https://youtube.com/watch?v=video123"},
        ) as upload:
            result = publisher.publish_all(Path("verified.mp4"), "", {})
        self.assertTrue(result["all_succeeded"])
        self.assertEqual([item["platform"] for item in result["results"]], ["youtube"])
        upload.assert_called_once()

    def test_youtube_upload_uses_validated_public_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            video = Path(temp) / "final.mp4"
            video.write_bytes(b"v" * 8192)

            token_response = MagicMock()
            token_response.json.return_value = {"access_token": "test-access"}
            init_response = MagicMock()
            init_response.headers = {"Location": "https://upload.example/resumable"}
            uploaded_response = MagicMock()
            uploaded_response.json.return_value = {"id": "video123"}

            plan = {
                "publish_metadata": {
                    "title": "Can Your Room Trick Your Violin Mix?",
                    "description": "Validated description with sources.",
                    "tags": ["violin", "room correction", "audio engineering"],
                    "category_id": "10",
                    "default_language": "en",
                    "default_audio_language": "en",
                    "privacy_status": "public",
                    "made_for_kids": False,
                }
            }
            with patch.dict(os.environ, {
                "YOUTUBE_CLIENT_ID": "client",
                "YOUTUBE_CLIENT_SECRET": "secret",
                "YOUTUBE_REFRESH_TOKEN": "refresh",
                "YOUTUBE_PRIVACY_STATUS": "public",
            }, clear=True), patch.object(
                publisher.HTTP, "post", side_effect=[token_response, init_response]
            ) as post, patch.object(
                publisher.HTTP, "put", return_value=uploaded_response
            ) as put:
                result = publisher.youtube_upload(video, plan)

            upload_body = post.call_args_list[1].kwargs["json"]
            self.assertEqual(upload_body["snippet"]["title"], plan["publish_metadata"]["title"])
            self.assertEqual(upload_body["snippet"]["description"], plan["publish_metadata"]["description"])
            self.assertEqual(upload_body["status"]["privacyStatus"], "public")
            self.assertIs(upload_body["status"]["selfDeclaredMadeForKids"], False)
            self.assertEqual(upload_body["snippet"]["defaultAudioLanguage"], "en")
            self.assertEqual(result["url"], "https://www.youtube.com/watch?v=video123")
            put.assert_called_once()


if __name__ == "__main__":
    unittest.main()
