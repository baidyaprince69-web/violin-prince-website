from __future__ import annotations
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "violin-prince-autopilot.yml"


class BlockedSlotWorkflowTests(unittest.TestCase):
    def test_blocked_slot_never_enters_production_job(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        match = re.search(
            r"(?ms)^  produce:\n(.*?)(?=^  [A-Za-z_][A-Za-z0-9_-]*:\n|\\Z)",
            content,
        )
        self.assertIsNotNone(match, "Could not locate the top-level production job.")
        self.assertIn("needs.daily_readiness.outputs.slot_status == 'ready'", match.group(1))

    def test_blocked_slot_has_a_summary_without_private_transfer(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("  report_blocked_slot:", content)
        self.assertIn("No narration, MP4, private release or public upload was attempted.", content)
        self.assertIn("  report_readiness_blocked:", content)

    def test_private_transfer_runs_only_inside_the_gated_production_job(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("- name: Transfer finished preview to the private Voice Vault", content)
        self.assertIn("needs.daily_readiness.outputs.slot_status == 'ready'", content)


if __name__ == "__main__":
    unittest.main()
