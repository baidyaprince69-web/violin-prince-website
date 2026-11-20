"""Offline tests for the existing direct YouTube OAuth uploader."""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import publisher


class FakeResponse:
    def __init__(self, payload=None, *, headers=None):
        self.payload = payload or {}
        self.headers = headers or {}

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self):
        self.post_calls = []
        self.put_calls = []

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        if url == "https://oauth2.googleapis.com/token":
            return FakeResponse({"access_token": "test-access-token"})
        return FakeResponse({}, headers={"Location": "https://upload.example/resumable-session"})

    def put(self, url, **kwargs):
        self.put_calls.append((url, kwargs))
        return FakeResponse({"id": "youtube-video-123"})


class YouTubeUploaderTests(unittest.TestCase):
    def test_upload_uses_exact_publish_manifest_metadata_and_oauth_refresh(self):
        with tempfile.TemporaryDirectory() as temporary:
            video = Path(temporary) / "violin-prince-short.mp4"
            video.write_bytes(b"verified-video-bytes")

            session = FakeSession()
            plan = {
                "title": "Verified Short",
                "description": "Description from the signed-off publish manifest.",
                "contains_synthetic_media": True,
                "publish_metadata": {
                    "title": "Verified Short",
                    "description": "Description from the signed-off publish manifest.",
                    "tags": ["Violin", "Music", "Acoustics"],
                    "category_id": "10",
                    "default_language": "en",
                    "privacy_status": "public",
                    "made_for_kids": False,
                },
            }
            env = {
                "YOUTUBE_CLIENT_ID": "test-client-id",
                "YOUTUBE_CLIENT_SECRET": "test-client-secret",
                "YOUTUBE_REFRESH_TOKEN": "test-refresh-token",
                "YOUTUBE_PRIVACY_STATUS": "public",
            }
            with patch.dict(os.environ, env, clear=False), patch.object(publisher, "HTTP", session):
                result = publisher.youtube_upload(video, plan)

        self.assertEqual(result["id"], "youtube-video-123")
        self.assertEqual(result["url"], "https://www.youtube.com/watch?v=youtube-video-123")
        self.assertEqual(len(session.post_calls), 2)
        token_url, token_args = session.post_calls[0]
        self.assertEqual(token_url, "https://oauth2.googleapis.com/token")
        self.assertEqual(token_args["data"]["refresh_token"], "test-refresh-token")

        upload_url, upload_args = session.post_calls[1]
        self.assertEqual(upload_url, "https://www.googleapis.com/upload/youtube/v3/videos")
        self.assertEqual(upload_args["params"]["uploadType"], "resumable")
        body = upload_args["json"]
        self.assertEqual(body["snippet"]["title"], "Verified Short")
        self.assertEqual(body["snippet"]["description"], "Description from the signed-off publish manifest.")
        self.assertEqual(body["snippet"]["tags"], ["Violin", "Music", "Acoustics"])
        self.assertEqual(body["snippet"]["categoryId"], "10")
        self.assertEqual(body["status"]["privacyStatus"], "public")
        self.assertIs(body["status"]["selfDeclaredMadeForKids"], False)
        self.assertIs(body["status"]["containsSyntheticMedia"], True)

        put_url, put_args = session.put_calls[0]
        self.assertEqual(put_url, "https://upload.example/resumable-session")
        self.assertEqual(put_args["headers"]["Content-Type"], "video/mp4")


if __name__ == "__main__":
    unittest.main()
