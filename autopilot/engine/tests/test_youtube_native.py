import base64
import json
import tempfile
import unittest
from pathlib import Path

from autopilot.engine.youtube_native.engine import (
    EncryptedCheckpointStore,
    MetadataError,
    PublishingDisabled,
    YouTubeNativeClient,
    build_metadata,
    metadata_candidates_from_plan,
    research_keywords,
)


GOOD_PLAN = {
    "title": "How Violin Bow Control Shapes Emotion",
    "seo_title": "How Violin Bow Control Shapes Emotion",
    "topic": "violin bow control",
    "primary_keyword": "violin bow control",
    "hook": "A small change can transform the phrase.",
    "description": "Learn how violin bow control changes articulation, dynamics and expression.",
    "hashtags": ["#Violin", "#BowControl", "#MusicEducation"],
    "tags": ["violin bowing", "bow technique", "violin expression"],
    "made_for_kids": False,
    "contains_synthetic_media": True,
    "seo_metadata_approved": True,
}


class FakeResponse:
    def __init__(self, status_code=200, payload=None, headers=None):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeUploadSession:
    def __init__(self):
        self.headers = {}
        self.calls = []
        self.put_count = 0

    def post(self, url, **kwargs):
        self.calls.append(("POST", url, kwargs))
        if url.endswith("/token"):
            return FakeResponse(payload={"access_token": "token-test"})
        if url.endswith("/channels"):
            return FakeResponse(payload={"items": [{"id": "channel-123"}]})
        if url.endswith("/videos") and "uploadType" in kwargs.get("params", {}):
            return FakeResponse(
                status_code=200,
                headers={"Location": "https://upload.example/session/secret-session-uri"},
            )
        raise AssertionError("Unexpected POST " + url)

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        if url.endswith("/channels"):
            return FakeResponse(payload={"items": [{"id": "channel-123"}]})
        if url.endswith("/videos"):
            return FakeResponse(payload={"items": [{
                "id": "video-987",
                "snippet": {"title": "Test video"},
                "status": {"privacyStatus": "private", "uploadStatus": "processed"},
                "processingDetails": {"processingStatus": "succeeded"},
            }]})
        raise AssertionError("Unexpected GET " + url)

    def put(self, url, **kwargs):
        self.calls.append(("PUT", url, kwargs))
        self.put_count += 1
        if url.startswith("https://upload.example/"):
            if self.put_count == 1:
                return FakeResponse(status_code=308, headers={"Range": "bytes=0-262143"})
            return FakeResponse(status_code=200, payload={"id": "video-987"})
        raise AssertionError("Unexpected PUT " + url)


class YouTubeMetadataTests(unittest.TestCase):
    def test_metadata_separates_hashtags_from_keyword_tags(self):
        result = build_metadata(GOOD_PLAN)
        body = result["body"]
        self.assertEqual(body["snippet"]["tags"], ["violin bowing", "bow technique", "violin expression"])
        self.assertIn("#Violin", body["snippet"]["description"])
        self.assertEqual(result["audit"]["hashtag_count"], 3)
        self.assertEqual(body["status"]["privacyStatus"], "private")

    def test_title_over_100_characters_is_rejected_not_truncated(self):
        plan = dict(GOOD_PLAN, seo_title="x" * 101)
        with self.assertRaises(MetadataError):
            build_metadata(plan)

    def test_description_is_checked_in_utf8_bytes(self):
        plan = dict(GOOD_PLAN, seo_description="é" * 2501)
        with self.assertRaises(MetadataError):
            build_metadata(plan)

    def test_ordinary_tags_have_500_character_total_limit(self):
        plan = dict(GOOD_PLAN, seo_tags=["x" * 501])
        with self.assertRaises(MetadataError):
            build_metadata(plan)

    def test_public_visibility_is_blocked_without_separate_approval(self):
        with self.assertRaises(PublishingDisabled):
            build_metadata(GOOD_PLAN, privacy_status="public", allow_public=False)
        with self.assertRaises(PublishingDisabled):
            build_metadata(GOOD_PLAN, privacy_status="unlisted", allow_public=False)

    def test_more_than_three_hashtags_is_rejected_for_review(self):
        plan = dict(GOOD_PLAN, hashtags=["#one", "#two", "#three", "#four"])
        with self.assertRaises(MetadataError):
            build_metadata(plan)

    def test_query_seeds_are_deduplicated_and_limited(self):
        values = metadata_candidates_from_plan({
            "topic": "Violin Bow Control",
            "title": "Violin Bow Control",
            "hook": "A different hook",
        })
        self.assertEqual(values, ["Violin Bow Control", "A different hook"])


class EncryptedCheckpointTests(unittest.TestCase):
    def test_encrypted_state_round_trip(self):
        key = base64.urlsafe_b64encode(b"k" * 32).decode("ascii")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.enc"
            store = EncryptedCheckpointStore(path, key)
            expected = {"version": 1, "releases": {"r1": {"upload_url": "secret"}}}
            store.save(expected)
            raw = path.read_text(encoding="utf-8")
            self.assertNotIn("secret", raw)
            self.assertEqual(store.load(), expected)

    def test_wrong_key_fails_closed(self):
        key_a = base64.urlsafe_b64encode(b"a" * 32).decode("ascii")
        key_b = base64.urlsafe_b64encode(b"b" * 32).decode("ascii")
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.enc"
            EncryptedCheckpointStore(path, key_a).save({"version": 1, "releases": {}})
            with self.assertRaises(Exception):
                EncryptedCheckpointStore(path, key_b).load()


class YouTubeClientTests(unittest.TestCase):
    def test_publishing_disabled_makes_zero_network_calls(self):
        fake = FakeUploadSession()
        client = YouTubeNativeClient(env={"PUBLISH_ENABLED": "false"}, session=fake)
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "video.mp4"
            video.write_bytes(b"video")
            with self.assertRaises(PublishingDisabled):
                client.upload_video(video, GOOD_PLAN, release_id="release-1")
        self.assertEqual(fake.calls, [])

    def test_resumable_upload_uses_acknowledged_ranges_and_encrypted_state(self):
        fake = FakeUploadSession()
        key = base64.urlsafe_b64encode(b"z" * 32).decode("ascii")
        with tempfile.TemporaryDirectory() as directory:
            video = Path(directory) / "video.mp4"
            video.write_bytes(b"x" * 300000)
            state_path = Path(directory) / "checkpoint.enc"
            env = {
                "PUBLISH_ENABLED": "true",
                "YOUTUBE_UPLOAD_APPROVED": "true",
                "YOUTUBE_PUBLICATION_APPROVED": "false",
                "YOUTUBE_PRIVACY_STATUS": "private",
                "YOUTUBE_CLIENT_ID": "client-id",
                "YOUTUBE_CLIENT_SECRET": "client-secret",
                "YOUTUBE_REFRESH_TOKEN": "refresh-token",
                "YOUTUBE_EXPECTED_CHANNEL_ID": "channel-123",
                "YOUTUBE_STATE_ENCRYPTION_KEY": key,
                "YOUTUBE_UPLOAD_STATE_PATH": str(state_path),
            }
            client = YouTubeNativeClient(
                env=env, session=fake, chunk_size=256 * 1024, sleep=lambda _: None
            )
            result = client.upload_video(video, GOOD_PLAN, release_id="release-1")
            self.assertEqual(result["video_id"], "video-987")
            self.assertFalse(result["already_uploaded"])
            saved = EncryptedCheckpointStore(state_path, key).load()
            self.assertEqual(saved["releases"]["release-1"]["state"], "uploaded")
            self.assertNotIn("secret-session-uri", state_path.read_text(encoding="utf-8"))

            second = client.upload_video(video, GOOD_PLAN, release_id="release-1")
            self.assertTrue(second["already_uploaded"])
            self.assertEqual(second["video_id"], "video-987")
            self.assertEqual(fake.put_count, 2)

    def test_visibility_changes_are_blocked_without_global_publish_gate(self):
        fake = FakeUploadSession()
        client = YouTubeNativeClient(env={"PUBLISH_ENABLED": "false"}, session=fake)
        with self.assertRaises(PublishingDisabled):
            client.set_visibility("video-987", "unlisted")
        self.assertEqual(fake.calls, [])

    def test_status_tracking_reads_processing_state(self):
        fake = FakeUploadSession()
        client = YouTubeNativeClient(env={}, session=fake)
        result = client.get_video_status("video-987", "token-test")
        self.assertEqual(result["processing_status"], "succeeded")
        self.assertEqual(result["privacy_status"], "private")

    def test_processing_completion_is_confirmed(self):
        fake = FakeUploadSession()
        client = YouTubeNativeClient(
            env={
                "YOUTUBE_CLIENT_ID": "client-id",
                "YOUTUBE_CLIENT_SECRET": "client-secret",
                "YOUTUBE_REFRESH_TOKEN": "refresh-token",
            },
            session=fake,
            sleep=lambda _: None,
        )
        result = client.wait_for_processing("video-987", timeout_seconds=1, interval_seconds=0)
        self.assertEqual(result["upload_status"], "processed")


class FakeResearchSession:
    def __init__(self):
        self.headers = {}

    def get(self, url, **kwargs):
        if url.endswith("/search"):
            return FakeResponse(payload={"items": [{
                "id": {"videoId": "abc"},
                "snippet": {"title": "Violin Bow Control Tutorial", "channelTitle": "Example"},
            }]})
        if url.endswith("/videos"):
            return FakeResponse(payload={"items": [{
                "id": "abc",
                "snippet": {
                    "title": "Violin Bow Control Tutorial",
                    "channelTitle": "Example",
                    "publishedAt": "2026-10-01T00:00:00Z",
                },
                "statistics": {"viewCount": "5000"},
            }]})
        raise AssertionError("Unexpected URL " + url)


class YouTubeResearchTests(unittest.TestCase):
    def test_keyword_research_labels_samples_not_search_volume(self):
        result = research_keywords(
            ["violin bow control"],
            api_key="api-key",
            session=FakeResearchSession(),
        )
        self.assertIsNone(result["search_volume"])
        self.assertIn("not exposed", result["search_volume_note"].casefold())
        self.assertEqual(result["candidates"][0]["results_returned"], 1)
        self.assertEqual(result["candidates"][0]["top_results"][0]["view_count"], 5000)


if __name__ == "__main__":
    unittest.main()
