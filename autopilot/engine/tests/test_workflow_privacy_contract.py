"""Privacy regression checks for the public Autopilot workflow."""
from __future__ import annotations

import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "violin-prince-autopilot.yml"


class WorkflowPrivacyContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow_text = WORKFLOW.read_text(encoding="utf-8")

    def test_public_workflow_never_uploads_actions_artifacts(self):
        self.assertNotIn("actions/upload-artifact", self.workflow_text)
        self.assertNotIn("actions/download-artifact", self.workflow_text)
        self.assertNotIn("Upload finished video", self.workflow_text)
        self.assertNotIn("Preserve stage diagnostics", self.workflow_text)

    def test_voice_bearing_preview_uses_only_private_voice_vault_handoff(self):
        self.assertIn("Transfer finished preview to the private Voice Vault", self.workflow_text)
        self.assertIn("PRIVATE_VOICE_REPO_TOKEN", self.workflow_text)
        self.assertIn("private-preview-video-$SOURCE_RUN_ID", self.workflow_text)
        self.assertIn("private-preview-$SOURCE_RUN_ID", self.workflow_text)

    def test_expensive_production_requires_fast_preflight(self):
        self.assertIn("fast_preflight:", self.workflow_text)
        self.assertIn("needs: [daily_readiness, fast_preflight]", self.workflow_text)
        self.assertIn("needs.fast_preflight.result == 'success'", self.workflow_text)
        self.assertIn("ruff check --select F821,F822,F823 autopilot/engine", self.workflow_text)
        self.assertIn("test_hyperframes_pipeline.py", self.workflow_text)

    def test_draft_release_cleanup_does_not_delete_a_nonexistent_tag(self):
        self.assertNotIn(
            'gh release delete "$release_tag" --repo "$PRIVATE_REPO" --yes --cleanup-tag',
            self.workflow_text,
        )

    def test_private_preview_handoff_uses_the_actual_draft_release_tag(self):
        self.assertIn('release_url="$(gh release create "$release_tag" "$video"', self.workflow_text)
        self.assertIn('release_tag="${release_url##*/}"', self.workflow_text)
        self.assertIn('^untagged-[0-9a-f]{16,64}
    def test_private_handoff_write_access_is_checked_before_expensive_production(self):
        self.assertIn("Verify private Voice Vault draft-release write access", self.workflow_text)
        self.assertIn("gh release create", self.workflow_text)
        self.assertIn("PRIVATE_VOICE_REPO_TOKEN is missing", self.workflow_text)
        self.assertIn("private-handoff-preflight-$GITHUB_RUN_ID", self.workflow_text)
        self.assertLess(
            self.workflow_text.index("Verify private Voice Vault draft-release write access"),
            self.workflow_text.index("  produce:"),
        )

    def test_publishing_is_hard_disabled_in_the_workflow(self):
        self.assertIn('PUBLISH_ENABLED: "false"', self.workflow_text)
        self.assertIn("env.PUBLISH_ENABLED == 'true'", self.workflow_text)
        self.assertIn("Only the complete preview-only run is enabled", self.workflow_text)

    def test_private_handoff_waits_for_artifact_and_cleanup_confirmation(self):
        self.assertIn("private-video-preview-intake.yml/runs?", self.workflow_text)
        self.assertIn("private_artifact_id", self.workflow_text)
        self.assertIn("Private intake artifact exists", self.workflow_text)
        self.assertIn("temporary draft release remains", self.workflow_text)

    def test_stage_recovery_inputs_cannot_request_public_intermediate_artifacts(self):
        self.assertNotIn("inputs.source_run_id", self.workflow_text)
        self.assertNotIn("inputs.visual_feedback", self.workflow_text)
        self.assertNotIn("source_run_id:", self.workflow_text)
        self.assertNotIn("visual_feedback:", self.workflow_text)


if __name__ == "__main__":
    unittest.main()
, self.workflow_text)
        self.assertIn('Resolved private draft-release tag:', self.workflow_text)

    def test_private_handoff_write_access_is_checked_before_expensive_production(self):
        self.assertIn("Verify private Voice Vault draft-release write access", self.workflow_text)
        self.assertIn("gh release create", self.workflow_text)
        self.assertIn("PRIVATE_VOICE_REPO_TOKEN is missing", self.workflow_text)
        self.assertIn("private-handoff-preflight-$GITHUB_RUN_ID", self.workflow_text)
        self.assertLess(
            self.workflow_text.index("Verify private Voice Vault draft-release write access"),
            self.workflow_text.index("  produce:"),
        )

    def test_publishing_is_hard_disabled_in_the_workflow(self):
        self.assertIn('PUBLISH_ENABLED: "false"', self.workflow_text)
        self.assertIn("env.PUBLISH_ENABLED == 'true'", self.workflow_text)
        self.assertIn("Only the complete preview-only run is enabled", self.workflow_text)

    def test_private_handoff_waits_for_artifact_and_cleanup_confirmation(self):
        self.assertIn("private-video-preview-intake.yml/runs?", self.workflow_text)
        self.assertIn("private_artifact_id", self.workflow_text)
        self.assertIn("Private intake artifact exists", self.workflow_text)
        self.assertIn("temporary draft release remains", self.workflow_text)

    def test_stage_recovery_inputs_cannot_request_public_intermediate_artifacts(self):
        self.assertNotIn("inputs.source_run_id", self.workflow_text)
        self.assertNotIn("inputs.visual_feedback", self.workflow_text)
        self.assertNotIn("source_run_id:", self.workflow_text)
        self.assertNotIn("visual_feedback:", self.workflow_text)


if __name__ == "__main__":
    unittest.main()
