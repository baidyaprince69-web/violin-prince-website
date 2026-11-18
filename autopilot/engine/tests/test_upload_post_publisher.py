import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock

from upload_post_publisher import UploadPostError, queue_video


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload


class UploadPostQueueTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.video = self.root / "short.mp4"
        self.video.write_bytes(b"0" * 8192)
        self.manifest = self.root / "manifest.json"
        self.manifest.write_text(json.dumps({
            "status": "rendered",
            "publish_ready": True,
            "publisher_preflight": {"status": "ready", "blockers": []},
            "run_id": "123456",
            "title": "A Violin Prince Short",
            "description": "A short description.",
        }), encoding="utf-8")

    def tearDown(self):
        self.temp.cleanup()

    def fake_session(self, post_payload=None):
        session = Mock()
        session.get.return_value = FakeResponse({
            "success": True,
            "queue_settings": {
                "timezone": "Asia/Kolkata",
                "slots": [{"hour": 19, "minute": 0}],
                "days_of_week": [0, 1, 2, 3, 4, 5, 6],
                "max_posts_per_slot": 1,
            },
        })
        session.post.return_value = FakeResponse(post_payload or {
            "success": True,
            "job_id": "queue-job-123",
            "scheduled_date": "2026-11-19T13:30:00Z",
        }, status_code=202)
        return session

    def test_queues_validated_mp4_in_default_daily_slot(self):
        session = self.fake_session()
        receipt = queue_video(
            self.video, self.manifest,
            api_key="test-key", profile="default", session=session,
        )

        self.assertTrue(receipt["success"])
        self.assertEqual(receipt["platform"], "youtube")
        self.assertEqual(receipt["profile"], "default")
        self.assertEqual(receipt["job_id"], "queue-job-123")
        self.assertEqual(receipt["queue_timezone"], "Asia/Kolkata")

        get_call = session.get.call_args
        self.assertEqual(get_call.kwargs["params"], {"profile_username": "default"})
        post_call = session.post.call_args
        self.assertEqual(post_call.kwargs["data"]["add_to_queue"], "true")
        self.assertEqual(post_call.kwargs["data"]["platform[]"], "youtube")
        self.assertEqual(post_call.kwargs["data"]["privacyStatus"], "public")
        self.assertEqual(post_call.kwargs["headers"]["Idempotency-Key"], "violin-prince-run-123456")
        self.assertEqual(post_call.kwargs["headers"]["Authorization"], "Apikey test-key")

    def test_blocks_unready_manifest_before_network_calls(self):
        payload = json.loads(self.manifest.read_text(encoding="utf-8"))
        payload["publish_ready"] = False
        self.manifest.write_text(json.dumps(payload), encoding="utf-8")
        session = self.fake_session()

        with self.assertRaisesRegex(UploadPostError, "publish_ready"):
            queue_video(self.video, self.manifest, api_key="test-key", session=session)
        session.get.assert_not_called()
        session.post.assert_not_called()

    def test_blocks_wrong_queue_timezone(self):
        session = self.fake_session()
        session.get.return_value = FakeResponse({
            "success": True,
            "queue_settings": {
                "timezone": "America/New_York",
                "slots": [{"hour": 19, "minute": 0}],
                "days_of_week": list(range(7)),
                "max_posts_per_slot": 1,
            },
        })

        with self.assertRaisesRegex(UploadPostError, "timezone mismatch"):
            queue_video(self.video, self.manifest, api_key="test-key", session=session)
        session.post.assert_not_called()

    def test_blocks_empty_api_key(self):
        session = self.fake_session()
        with self.assertRaisesRegex(UploadPostError, "UPLOAD_POST_API_KEY"):
            queue_video(self.video, self.manifest, api_key="", session=session)
        session.get.assert_not_called()

    def test_rejects_missing_video(self):
        session = self.fake_session()
        with self.assertRaisesRegex(UploadPostError, "missing or unexpectedly small"):
            queue_video(self.root / "missing.mp4", self.manifest, api_key="test-key", session=session)
        session.get.assert_not_called()


if __name__ == "__main__":
    unittest.main()
