import io
import tempfile
import unittest
import zipfile
from pathlib import Path

from autopilot.engine.youtube_native.checkpoint_artifacts import (
    CheckpointArtifactError,
    restore_latest_checkpoint,
)


class FakeResponse:
    def __init__(self, payload=None, content=b""):
        self._payload = payload or {}
        self.content = content

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class FakeSession:
    def __init__(self, artifacts, archive):
        self.artifacts = artifacts
        self.archive = archive
        self.calls = []

    def get(self, url, headers, params=None, timeout=None):
        self.calls.append((url, params, headers))
        if url.endswith("/actions/artifacts"):
            return FakeResponse({"artifacts": self.artifacts})
        return FakeResponse(content=self.archive)


def make_zip(name="work/youtube-upload-state.enc", payload=b"ciphertext-only"):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as package:
        package.writestr(name, payload)
    return output.getvalue()


class CheckpointArtifactTests(unittest.TestCase):
    def test_restores_latest_unexpired_encrypted_state_from_previous_run(self):
        artifacts = [
            {
                "id": 11,
                "name": "youtube-native-upload-state",
                "expired": False,
                "created_at": "2026-11-12T00:00:00Z",
                "archive_download_url": "https://github.test/artifacts/11",
                "workflow_run": {"id": 100, "head_branch": "v3-motion-prototype"},
            },
            {
                "id": 12,
                "name": "youtube-native-upload-state",
                "expired": False,
                "created_at": "2026-11-13T00:00:00Z",
                "archive_download_url": "https://github.test/artifacts/12",
                "workflow_run": {"id": 101, "head_branch": "v3-motion-prototype"},
            },
            {
                "id": 14,
                "name": "youtube-native-upload-state",
                "expired": False,
                "created_at": "2026-11-14T00:00:00Z",
                "archive_download_url": "https://github.test/artifacts/14",
                "workflow_run": {"id": 103, "head_branch": "seo-intelligence-engine"},
            },
            {
                "id": 13,
                "name": "youtube-native-upload-state",
                "expired": True,
                "created_at": "2026-11-14T00:00:00Z",
                "archive_download_url": "https://github.test/artifacts/13",
                "workflow_run": {"id": 102, "head_branch": "v3-motion-prototype"},
            },
        ]
        session = FakeSession(artifacts, make_zip())
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "youtube-upload-state.enc"
            result = restore_latest_checkpoint(
                "owner/repo", "test-token", target, current_run_id="900",
                session=session,
            )
            self.assertTrue(result["restored"])
            self.assertEqual(result["artifact_id"], 12)
            self.assertEqual(target.read_bytes(), b"ciphertext-only")
        self.assertEqual(len(session.calls), 2)
        self.assertEqual(session.calls[0][2]["Authorization"], "Bearer test-token")

    def test_no_previous_artifact_is_a_safe_empty_start(self):
        with tempfile.TemporaryDirectory() as directory:
            result = restore_latest_checkpoint(
                "owner/repo", "test-token", Path(directory) / "state.enc",
                session=FakeSession([], b""),
            )
        self.assertFalse(result["restored"])
        self.assertEqual(result["reason"], "no_previous_checkpoint")

    def test_missing_encrypted_state_file_fails_closed(self):
        session = FakeSession(
            [{
                "id": 1,
                "name": "youtube-native-upload-state",
                "expired": False,
                "created_at": "2026-11-14T00:00:00Z",
                "archive_download_url": "https://github.test/artifacts/1",
                "workflow_run": {"id": 100, "head_branch": "v3-motion-prototype"},
            }],
            make_zip("unrelated.txt", b"not-state"),
        )
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(CheckpointArtifactError):
                restore_latest_checkpoint(
                    "owner/repo", "test-token", Path(directory) / "state.enc",
                    session=session,
                )


if __name__ == "__main__":
    unittest.main()
