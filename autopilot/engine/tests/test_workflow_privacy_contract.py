"""Privacy and direct-publication regression checks for the Autopilot workflow."""
from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "violin-prince-autopilot.yml"


class WorkflowPublicationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow_text = WORKFLOW.read_text(encoding="utf-8")

    def test_scheduled_private_preview_artifact_is_retained_for_recovery(self):
        self.assertIn("actions/upload-artifact@v4", self.workflow_text)
        self.assertIn("Retain scheduled private-preview artifact for recovery", self.workflow_text)
        self.assertIn("retention-days: 3", self.workflow_text)
        self.assertNotIn("actions/download-artifact", self.workflow_text)
        self.assertNotIn("Upload finished video", self.workflow_text)
        self.assertNotIn("Preserve stage diagnostics", self.workflow_text)

    def test_scheduled_ready_slots_upload_private_previews_only(self):
        self.assertIn("Upload validated daily slot as a PRIVATE YouTube preview via Upload-Post", self.workflow_text)
        self.assertIn("upload_private_preview_uploadpost.py", self.workflow_text)
        self.assertNotIn("upload_private_preview.py", self.workflow_text)
        self.assertIn('YOUTUBE_PRIVACY_STATUS: "private"', self.workflow_text)
        self.assertNotIn("publish_daily_short.py", self.workflow_text)
        self.assertNotIn('YOUTUBE_PRIVACY_STATUS: "public"', self.workflow_text)
        self.assertIn("needs.daily_readiness.outputs.slot_status == 'ready'", self.workflow_text)

    def test_legacy_public_upload_requests_are_rejected_during_commissioning(self):
        self.assertIn("Public YouTube publishing is disabled during private-preview commissioning", self.workflow_text)
        self.assertIn("publish_to_youtube=false", self.workflow_text)

    def test_private_voice_bridge_is_separate_from_video_delivery(self):
        self.assertIn("PRIVATE_VOICE_REPO_TOKEN", self.workflow_text)
        self.assertIn("Run the selected ChatGPT-directed slot through Motion + HyperFrames", self.workflow_text)
        self.assertNotIn("PRIVATE_REPO: baidyaprince69-web/violin-prince-private-voice", self.workflow_text)

    def test_expensive_production_requires_fast_preflight(self):
        self.assertIn("fast_preflight:", self.workflow_text)
        self.assertIn("needs: [daily_readiness, fast_preflight]", self.workflow_text)
        self.assertIn("needs.fast_preflight.result == 'success'", self.workflow_text)
        self.assertIn("ruff check --select F821,F822,F823 autopilot/engine", self.workflow_text)
        self.assertIn("test_hyperframes_pipeline.py", self.workflow_text)

    def test_publication_is_private_preview_only_and_generic_publishers_stay_disabled(self):
        self.assertIn("github.event_name == 'schedule'", self.workflow_text)
        self.assertNotIn('PUBLISH_ENABLED: "true"', self.workflow_text)
        self.assertNotIn("publish_daily_short.py", self.workflow_text)

    def test_no_generic_publication_flag_is_enabled_during_rendering(self):
        self.assertIn('PUBLISH_ENABLED: "false"', self.workflow_text)
        self.assertNotIn('PUBLISH_DESTINATIONS: "youtube,instagram,facebook"', self.workflow_text)

    def test_stage_recovery_inputs_cannot_request_public_intermediate_artifacts(self):
        self.assertNotIn("inputs.source_run_id", self.workflow_text)
        self.assertNotIn("inputs.visual_feedback", self.workflow_text)
        self.assertNotIn("source_run_id:", self.workflow_text)
        self.assertNotIn("visual_feedback:", self.workflow_text)


if __name__ == "__main__":
    unittest.main()
