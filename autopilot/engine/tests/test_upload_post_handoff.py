"""Offline tests for the Upload-Post publisher and scheduled-readiness guard."""
from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from daily_readiness import evaluate_daily_readiness
from upload_post_handoff import (
    UploadPostHandoffError,
    build_release_url,
    build_upload_fields,
    load_validated_bundle,
    submit_to_upload_post,
)


class FakeResponse:
    def __init__(self, payload, status_code=202):
        self.payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class FakeSession:
    def __init__(self, post_response=None, get_responses=None):
        self.post_response = post_response or FakeResponse(
            {
                "success": True,
                "job_id": "job-123",
                "scheduled_date": "2026-11-19T13:30:00+00:00",
                "queue_slot": "2026-11-19T13:30:00+00:00",
            }
        )
        self.get_responses = list(get_responses or [])
        self.post_calls = []
        self.get_calls = []

    def post(self, url, **kwargs):
        self.post_calls.append((url, kwargs))
        return self.post_response

    def get(self, url, **kwargs):
        self.get_calls.append((url, kwargs))
        if not self.get_responses:
            raise AssertionError("Unexpected status poll.")
        return self.get_responses.pop(0)


class UploadPostHandoffTests(unittest.TestCase):
    def _bundle_files(self, root: Path):
        video = root / "violin-prince-short.mp4"
        video.write_bytes(b"V" * 8192)
        digest = hashlib.sha256(video.read_bytes()).hexdigest()
        plan = {
            "production_date": "2026-11-19",
            "title": "A verified Violin Prince Short",
            "hook": "Could your room change your violin mix?",
            "description": "A clear explanation of monitor correction.",
            "hashtags": ["#Violin", "MusicProduction"],
            "sources": [{"title": "Independent source", "url": "https://example.com/article"}],
        }
        manifest = {
            "status": "rendered",
            "publish_ready": True,
            "duration_seconds": 24,
            "publisher_preflight": {"status": "ready", "blockers": []},
        }
        provenance = {
            "factual_provenance": {"status": "passed", "independent_publisher_count": 2},
            "assets": {"final_video": {"sha256": digest}},
        }
        plan_path = root / "plan.json"
        manifest_path = root / "manifest.json"
        provenance_path = root / "provenance.json"
        for path, payload in (
            (plan_path, plan),
            (manifest_path, manifest),
            (provenance_path, provenance),
        ):
            path.write_text(json.dumps(payload), encoding="utf-8")
        return video, plan_path, manifest_path, provenance_path

    def test_release_url_is_specific_to_the_workflow_release_asset(self):
        url = build_release_url("baidyaprince69-web/violin-prince-website", "12345")
        self.assertEqual(
            url,
            "https://github.com/baidyaprince69-web/violin-prince-website/releases/download/"
            "violin-prince-short-12345/violin-prince-short.mp4",
        )
        with self.assertRaises(UploadPostHandoffError):
            build_release_url("bad repository", "12345")

    def test_bundle_requires_render_ready_manifest_and_matching_provenance(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self._bundle_files(Path(temporary))
            bundle = load_validated_bundle(*paths)
            self.assertEqual(bundle["title"], "A verified Violin Prince Short")
            self.assertEqual(bundle["sha256"], hashlib.sha256(paths[0].read_bytes()).hexdigest())

            provenance = json.loads(paths[3].read_text(encoding="utf-8"))
            provenance["assets"]["final_video"]["sha256"] = "0" * 64
            paths[3].write_text(json.dumps(provenance), encoding="utf-8")
            with self.assertRaisesRegex(UploadPostHandoffError, "SHA-256"):
                load_validated_bundle(*paths)

    def test_unready_manifest_is_rejected_before_any_network_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            paths = self._bundle_files(Path(temporary))
            manifest = json.loads(paths[2].read_text(encoding="utf-8"))
            manifest["publish_ready"] = False
            paths[2].write_text(json.dumps(manifest), encoding="utf-8")
            with self.assertRaisesRegex(UploadPostHandoffError, "not marked publish_ready"):
                load_validated_bundle(*paths)

    def test_upload_fields_target_only_youtube_and_the_configured_queue(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = load_validated_bundle(*self._bundle_files(Path(temporary)))
            fields, request_id, external_id = build_upload_fields(
                bundle,
                "default",
                "https://github.com/owner/repo/releases/download/release/video.mp4",
            )
        values = dict(fields)
        self.assertEqual(values["user"], "default")
        self.assertEqual(values["platform[]"], "youtube")
        self.assertEqual(values["add_to_queue"], "true")
        self.assertEqual(values["privacyStatus"], "public")
        self.assertEqual(values["video"], "https://github.com/owner/repo/releases/download/release/video.mp4")
        self.assertEqual(len(request_id), 32)
        self.assertEqual(external_id, "violin-prince-youtube-2026-11-19")
        self.assertIn("#MusicProduction", values["description"])

    def test_queue_submission_uses_stable_idempotency_and_returns_job_id(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = load_validated_bundle(*self._bundle_files(Path(temporary)))
            session = FakeSession()
            result = submit_to_upload_post(
                bundle,
                api_key="test-key-never-real",
                profile="default",
                release_url="https://github.com/owner/repo/releases/download/release/video.mp4",
                session=session,
            )
        self.assertEqual(result["status"], "queued")
        self.assertEqual(result["job_id"], "job-123")
        self.assertIn("2026-11-19", result["idempotency_key"])
        url, kwargs = session.post_calls[0]
        self.assertEqual(url, "https://api.upload-post.com/api/upload")
        self.assertEqual(kwargs["headers"]["Authorization"], "Apikey test-key-never-real")
        self.assertEqual(kwargs["headers"]["Idempotency-Key"], result["idempotency_key"])

    def test_missing_api_key_never_sends_a_request(self):
        with tempfile.TemporaryDirectory() as temporary:
            bundle = load_validated_bundle(*self._bundle_files(Path(temporary)))
            session = FakeSession()
            result = submit_to_upload_post(
                bundle,
                api_key="",
                profile="default",
                release_url="https://github.com/owner/repo/releases/download/release/video.mp4",
                session=session,
            )
        self.assertEqual(result["status"], "blocked_missing_secret")
        self.assertEqual(session.post_calls, [])


class DailyReadinessTests(unittest.TestCase):
    def _write(self, root: Path, relative: str, content: str):
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return path

    def test_scheduled_run_skips_when_voice_and_provider_gates_are_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write(
                root,
                ".autopilot/prepare-request.json",
                json.dumps({"mode": "chatgpt_daily_production", "plan_path": ".autopilot/daily-production-plan.json"}),
            )
            self._write(
                root,
                ".autopilot/daily-production-plan.json",
                json.dumps({"production_date": "2026-11-19"}),
            )
            self._write(
                root,
                "autopilot/engine/voiceover.py",
                'def require_approved_own_voice():\n    """Keep closed."""\n    raise RuntimeError("locked")\n',
            )
            self._write(
                root,
                "autopilot/engine/run.py",
                'def require_approved_text_provider():\n    raise RuntimeError("locked")\n'
                'def require_approved_illustration_provider():\n    raise RuntimeError("locked")\n',
            )
            result = evaluate_daily_readiness(
                root,
                today="2026-11-19",
                upload_post_api_key="",
            )
        self.assertFalse(result["ready"])
        self.assertTrue(any("own-voice" in item.casefold() for item in result["blockers"]))
        self.assertTrue(any("illustration" in item.casefold() for item in result["blockers"]))
        self.assertFalse(any("UPLOAD_POST_API_KEY" in item for item in result["blockers"]))

    def test_scheduled_run_is_ready_only_when_all_gates_and_plan_are_ready(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write(
                root,
                ".autopilot/prepare-request.json",
                json.dumps({"mode": "chatgpt_daily_production", "plan_path": ".autopilot/daily-production-plan.json"}),
            )
            self._write(
                root,
                ".autopilot/daily-production-plan.json",
                json.dumps({"production_date": "2026-11-19"}),
            )
            self._write(
                root,
                "autopilot/engine/voiceover.py",
                'def require_approved_own_voice():\n    return True\n',
            )
            self._write(
                root,
                "autopilot/engine/run.py",
                'def require_approved_text_provider():\n    return True\n'
                'def require_approved_illustration_provider():\n    return True\n',
            )
            approval_source = Path(__file__).resolve().parents[1] / "voice-approval.json"
            self._write(
                root,
                "autopilot/engine/voice-approval.json",
                approval_source.read_text(encoding="utf-8"),
            )
            result = evaluate_daily_readiness(
                root,
                today="2026-11-19",
                upload_post_api_key="configured-test-secret",
            )
        self.assertTrue(result["ready"])
        self.assertEqual(result["blockers"], [])

    def test_plan_for_a_different_day_is_not_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write(
                root,
                ".autopilot/prepare-request.json",
                json.dumps({"mode": "chatgpt_daily_production", "plan_path": ".autopilot/daily-production-plan.json"}),
            )
            self._write(
                root,
                ".autopilot/daily-production-plan.json",
                json.dumps({"production_date": "2026-11-18"}),
            )
            self._write(root, "autopilot/engine/voiceover.py", "def require_approved_own_voice():\n    return True\n")
            self._write(
                root,
                "autopilot/engine/run.py",
                "def require_approved_text_provider():\n    return True\ndef require_approved_illustration_provider():\n    return True\n",
            )
            result = evaluate_daily_readiness(
                root,
                today="2026-11-19",
                upload_post_api_key="configured-test-secret",
            )
        self.assertFalse(result["ready"])
        self.assertTrue(any("production_date must be 2026-11-19" in item for item in result["blockers"]))


if __name__ == "__main__":
    unittest.main()
