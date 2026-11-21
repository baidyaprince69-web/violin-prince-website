from __future__ import annotations
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = ROOT / ".github" / "workflows" / "violin-prince-autopilot.yml"


def top_level_job_block(content: str, job_name: str) -> str:
    lines = content.splitlines()
    heading = f"  {job_name}:"
    try:
        start = lines.index(heading) + 1
    except ValueError as exc:
        raise AssertionError(f"Could not locate top-level job {job_name!r}.") from exc
    end = next(
        (
            index for index in range(start, len(lines))
            if lines[index].startswith("  ")
            and not lines[index].startswith("    ")
            and lines[index].strip().endswith(":")
        ),
        len(lines),
    )
    return "\n".join(lines[start:end])


class BlockedSlotWorkflowTests(unittest.TestCase):
    def test_blocked_slot_never_enters_production_job(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        produce = top_level_job_block(content, "produce")
        self.assertIn("needs.daily_readiness.outputs.slot_status == 'ready'", produce)

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
