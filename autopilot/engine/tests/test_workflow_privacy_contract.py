"""Regression checks that every automatic Violin Prince publication path is private-only."""
from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOWS = REPO_ROOT / ".github" / "workflows"
ENGINE = REPO_ROOT / "autopilot" / "engine"


class WorkflowPublicationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.autopilot = (WORKFLOWS / "violin-prince-autopilot.yml").read_text(encoding="utf-8")
        cls.direct_fallback = (WORKFLOWS / "publisher-fallback.yml").read_text(encoding="utf-8")
        cls.approved_preview = (WORKFLOWS / "publish-approved-private-preview.yml").read_text(encoding="utf-8")
        cls.public_upload_code = (ENGINE / "upload_public_short_uploadpost.py").read_text(encoding="utf-8")
        cls.router_code = (ENGINE / "publisher_router.py").read_text(encoding="utf-8")
        cls.approved_preview_code = (ENGINE / "publish_approved_private_preview.py").read_text(encoding="utf-8")
        cls.legacy_daily_publisher_code = (ENGINE / "publish_daily_short.py").read_text(encoding="utf-8")

    def test_scheduled_ready_slots_upload_private_previews_only(self):
        self.assertIn("group: violin-prince-private-preview-queue", self.autopilot)
        self.assertIn("select_public_queue.py", self.autopilot)
        self.assertIn("private-preview queue", self.autopilot.casefold())
        self.assertIn("Upload the scheduled slot as a PRIVATE YouTube preview via Upload-Post", self.autopilot)
        self.assertIn("upload_private_preview_uploadpost.py", self.autopilot)
        self.assertIn('YOUTUBE_PRIVACY_STATUS: "private"', self.autopilot)
        self.assertIn('PUBLISH_ENABLED: "false"', self.autopilot)
        self.assertNotIn("upload_public_short_uploadpost.py", self.autopilot)
        self.assertNotIn('YOUTUBE_PRIVACY_STATUS: "public"', self.autopilot)

    def test_scheduled_recovery_artifact_is_named_as_a_private_preview(self):
        self.assertIn("Retain scheduled private-preview artifact for recovery", self.autopilot)
        self.assertIn("violin-prince-private-preview-${{ github.run_number }}", self.autopilot)
        self.assertIn("retention-days: 3", self.autopilot)

    def test_legacy_direct_public_fallback_workflow_is_disabled(self):
        self.assertIn("direct_youtube_fallback:", self.direct_fallback)
        self.assertIn("if: false", self.direct_fallback)

    def test_legacy_public_release_from_private_preview_workflow_is_disabled(self):
        self.assertIn("publish_approved_preview:", self.approved_preview)
        self.assertIn("if: false", self.approved_preview)

    def test_legacy_public_upload_post_entrypoint_is_hard_disabled(self):
        self.assertIn("Public YouTube publishing is disabled", self.public_upload_code)
        self.assertIn("upload_private_preview_uploadpost.py instead", self.public_upload_code)

    def test_legacy_direct_youtube_router_is_hard_disabled(self):
        self.assertIn("Direct public YouTube publication is disabled", self.router_code)

    def test_legacy_approved_preview_publication_script_is_hard_disabled(self):
        self.assertIn("Public YouTube publication is disabled", self.approved_preview_code)

    def test_legacy_direct_daily_publisher_is_hard_disabled(self):
        self.assertIn("Direct public YouTube publication is disabled", self.legacy_daily_publisher_code)
        self.assertIn("private-preview-only", self.legacy_daily_publisher_code)

    def test_one_off_push_requests_cannot_enable_public_publishing(self):
        self.assertIn("Direct public publishing from this one-off handoff route is disabled", self.autopilot)
        self.assertIn("publish_to_youtube=false", self.autopilot)

    def test_private_voice_bridge_is_separate_from_video_delivery(self):
        self.assertIn("PRIVATE_VOICE_REPO_TOKEN", self.autopilot)
        self.assertIn("Run the selected ChatGPT-directed slot through Motion + HyperFrames", self.autopilot)
        self.assertNotIn("PRIVATE_REPO: baidyaprince69-web/violin-prince-private-voice", self.autopilot)

    def test_expensive_production_requires_fast_preflight(self):
        self.assertIn("fast_preflight:", self.autopilot)
        self.assertIn("needs: [daily_readiness, fast_preflight]", self.autopilot)
        self.assertIn("needs.fast_preflight.result == 'success'", self.autopilot)
        self.assertIn("ruff check --select F821,F822,F823 autopilot/engine", self.autopilot)
        self.assertIn("test_hyperframes_pipeline.py", self.autopilot)

    def test_generic_publishing_adapters_remain_disabled_during_rendering(self):
        self.assertIn('PUBLISH_ENABLED: "false"', self.autopilot)
        self.assertNotIn('PUBLISH_DESTINATIONS: "youtube,instagram,facebook"', self.autopilot)


if __name__ == "__main__":
    unittest.main()
