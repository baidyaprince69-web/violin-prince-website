import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from autopilot.engine.youtube_native.phase3_release import (
    ReleaseValidationError,
    prepare_review,
    validate_phase3_release,
)


class Phase3ReleaseTests(unittest.TestCase):
    def _fixture(self, root: Path):
        output = root / "output" / "motion-prototype"
        package = root / "package"
        output.mkdir(parents=True)
        package.mkdir(parents=True)
        video = output / "html-motion-prototype.mp4"
        video.write_bytes(b"verified-mp4-payload")
        manifest = {
            "publishing_enabled": False,
            "package_fingerprint": "fingerprint-1",
            "stages": {
                "audio_mix": {"output_sha256": hashlib.sha256(video.read_bytes()).hexdigest()},
                "quality_control": {"status": "passed"},
            },
        }
        qc = {
            "passed": True,
            "status": "passed",
            "checks": [{"name": "mp4", "passed": True}, {"name": "audio", "passed": True}],
        }
        (output / "recovery-manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
        (output / "quality-control-report.json").write_text(json.dumps(qc), encoding="utf-8")
        plan = {
            "title": "A Violin Cover",
            "topic": "violin cover",
            "description": "A short violin performance.",
            "hashtags": ["#Violin", "#Music", "#Cover"],
            "tags": ["violin", "cover"],
            "sources": [],
        }
        (package / "creative_plan.json").write_text(json.dumps(plan), encoding="utf-8")
        report = {
            "schema_version": 1,
            "phase": "phase3_release_handoff",
            "status": "prepared",
            "publishing_enabled": False,
            "provider_requests_made": 0,
            "source": {
                "phase2_run_id": "12345",
                "artifact_name": "v3-motion-prototype-12345",
            },
            "phase2": {
                "video_file": "html-motion-prototype.mp4",
                "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(),
                "manifest_sha256": hashlib.sha256((output / "recovery-manifest.json").read_bytes()).hexdigest(),
                "qc_report_sha256": hashlib.sha256((output / "quality-control-report.json").read_bytes()).hexdigest(),
                "package_fingerprint": "fingerprint-1",
                "qc_checks_passed": 2,
                "qc_checks_total": 2,
            },
            "metadata_sha256": "metadata-hash",
            "releases": [{"destination": "youtube", "release_id": "release-abc", "state": "READY"}],
        }
        report_path = root / "phase3-release-handoff.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return report_path, video

    def test_only_exact_hash_matched_ready_release_is_accepted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report, video = self._fixture(root)
            result = validate_phase3_release(report, root, "12345")
            self.assertEqual(result["release_id"], "release-abc")
            self.assertEqual(result["video_path"], str(video))
            self.assertEqual(result["qc_checks_passed"], 2)

    def test_mp4_tampering_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report, video = self._fixture(root)
            video.write_bytes(b"different")
            with self.assertRaises(ReleaseValidationError):
                validate_phase3_release(report, root, "12345")

    def test_wrong_run_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report, _video = self._fixture(root)
            with self.assertRaises(ReleaseValidationError):
                validate_phase3_release(report, root, "99999")

    def test_preview_never_self_approves_and_accepts_three_hashtags(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report, _video = self._fixture(root)
            release = validate_phase3_release(report, root, "12345")
            plan, review = prepare_review(
                release,
                metadata_overrides_json='{"seo_hashtags":["#Violin","#Cover"],"seo_title":"My reviewed violin cover"}',
                made_for_kids="false",
                contains_synthetic_media="true",
            )
            self.assertFalse(plan["seo_metadata_approved"])
            self.assertTrue(review["metadata_valid"])
            self.assertEqual(review["title_candidate"], "My reviewed violin cover")
            self.assertEqual(review["made_for_kids"], False)
            self.assertEqual(review["contains_synthetic_media"], True)

    def test_invalid_hashtag_count_is_reported_without_truncation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            report, _video = self._fixture(root)
            release = validate_phase3_release(report, root, "12345")
            plan_path = Path(release["creative_plan_path"])
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["hashtags"] = ["#one", "#two", "#three", "#four"]
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            plan_path = Path(release["creative_plan_path"])
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["hashtags"] = ["#one", "#two", "#three", "#four"]
            plan_path.write_text(json.dumps(plan), encoding="utf-8")
            _plan, review = prepare_review(release)
            self.assertFalse(review["metadata_valid"])
            self.assertIn("three precise hashtags", review["metadata_error"])


if __name__ == "__main__":
    unittest.main()
