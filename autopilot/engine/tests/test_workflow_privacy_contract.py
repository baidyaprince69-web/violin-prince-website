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

    def test_public_workflow_never_uploads_actions_artifacts(self):
        self.assertNotIn("actions/upload-artifact", self.workflow_text)
        self.assertNotIn("actions/download-artifact", self.workflow_text)
        self.assertNotIn("Upload finished video", self.workflow_text)
        self.assertNotIn("Preserve stage diagnostics", self.workflow_text)

    def test_scheduled_video_is_sent_directly_to_public_youtube_not_private_vault(self):
        self.assertIn("Publish validated daily slot directly to public YouTube", self.workflow_text)
        self.assertIn("publish_daily_short.py", self.workflow_text)
        self.assertIn('YOUTUBE_PRIVACY_STATUS: "public"', self.workflow_text)
        self.assertNotIn("Transfer finished preview to the private Voice Vault", self.workflow_text)
        self.assertNotIn("private-preview-video-$SOURCE_RUN_ID", self.workflow_text)
        self.assertNotIn("private-preview-$SOURCE_RUN_ID", self.workflow_text)

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

    def test_direct_publication_is_limited_to_ready_scheduled_slots_or_explicit_push_requests(self):
        self.assertIn("steps.daily_request.outputs.publish_to_youtube == 'true'", self.workflow_text)
        self.assertIn("needs.daily_readiness.outputs.slot_status == 'ready'", self.workflow_text)
        self.assertIn("github.event_name == 'schedule'", self.workflow_text)
        self.assertNotIn('PUBLISH_ENABLED: "true"', self.workflow_text)

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
