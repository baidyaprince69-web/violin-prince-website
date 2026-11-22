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

    def test_blocked_slot_has_a_summary_and_no_publication_attempt(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("  report_blocked_slot:", content)
        self.assertIn("No narration, MP4 render or YouTube upload was attempted.", content)
        self.assertIn("  report_readiness_blocked:", content)

    def test_ready_scheduled_slot_uses_private_preview_route_only(self):
        content = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("select_public_queue.py", content)
        self.assertIn("Select the next unused ready story from the scheduled date's batch", content)
        self.assertIn("group: violin-prince-private-preview-queue", content)
        self.assertIn("production_date: ${{ steps.batch.outputs.production_date }}", content)
        self.assertIn("- name: Upload the scheduled slot as a PRIVATE YouTube preview via Upload-Post", content)
        self.assertIn("python autopilot/engine/upload_private_preview_uploadpost.py", content)
        self.assertIn('YOUTUBE_PRIVACY_STATUS: "private"', content)
        self.assertIn('PUBLISH_ENABLED: "false"', content)
        self.assertIn("needs.daily_readiness.outputs.slot_status == 'ready'", content)
        self.assertIn("Retain scheduled private-preview artifact for recovery", content)
        self.assertIn("creative_plan.json", content)
        self.assertNotIn("upload_public_short_uploadpost.py", content)
        self.assertNotIn('YOUTUBE_PRIVACY_STATUS: "public"', content)


if __name__ == "__main__":
    unittest.main()
