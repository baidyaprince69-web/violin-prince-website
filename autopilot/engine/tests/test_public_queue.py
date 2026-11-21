from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from select_public_queue import select_next_public_plan
from slot_registry import SLOT_CATALOG


def make_batch(production_date: str, ready: set[str]) -> dict:
    plans = []
    for slot_id in SLOT_CATALOG:
        plan = {
            "production_date": production_date,
            "slot_id": slot_id,
            "title": f"{production_date} {slot_id}",
            "narration_script": "A complete sample narration for the queue selector.",
        }
        if slot_id in ready:
            plan.update({
                "slot_status": "ready",
                "publish_metadata": {
                    "title": f"{production_date} {slot_id}",
                    "privacy_status": "public",
                    "description": "Source-checked test description.",
                    "tags": ["Violin Prince", "music", "test"],
                },
            })
        else:
            plan.update({
                "slot_status": "blocked",
                "blocked_reason": "The test plan is intentionally blocked.",
            })
        plans.append(plan)
    return {"production_date": production_date, "plans": plans}


class RollingPublicQueueTests(unittest.TestCase):
    def _write_batch(self, root: Path, production_date: str, ready: set[str]) -> Path:
        path = root / ".autopilot" / "daily-batches" / f"{production_date}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(make_batch(production_date, ready)), encoding="utf-8")
        return path

    def test_selects_first_ready_story_and_skips_blocked_slots(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_batch(root, "2026-11-22", {"production-tech", "melody-stories"})
            result = select_next_public_plan(root, after_date="2026-11-22")
        self.assertTrue(result["ready"])
        self.assertEqual(result["slot_id"], "production-tech")
        self.assertEqual(result["production_date"], "2026-11-22")
        self.assertEqual(result["remaining_ready_count"], 2)

    def test_advances_to_next_story_after_a_durable_attempt_marker(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_batch(root, "2026-11-22", {"production-tech", "melody-stories"})
            attempts = root / ".autopilot" / "public-youtube-attempts"
            attempts.mkdir(parents=True)
            (attempts / "2026-11-22-production-tech.json").write_text(
                json.dumps({"status": "outcome_unknown", "retry_allowed": False}),
                encoding="utf-8",
            )
            result = select_next_public_plan(root, after_date="2026-11-22")
        self.assertTrue(result["ready"])
        self.assertEqual(result["slot_id"], "melody-stories")

    def test_advances_to_next_dated_batch_after_current_ready_stories_are_used(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_batch(root, "2026-11-22", {"production-tech", "melody-stories"})
            self._write_batch(root, "2026-11-23", {"music-secrets", "real-performance"})
            attempts = root / ".autopilot" / "public-youtube-attempts"
            attempts.mkdir(parents=True)
            for identity in ("2026-11-22-production-tech", "2026-11-22-melody-stories"):
                (attempts / f"{identity}.json").write_text("{}", encoding="utf-8")
            result = select_next_public_plan(root, after_date="2026-11-22")
        self.assertTrue(result["ready"])
        self.assertEqual(result["production_date"], "2026-11-23")
        self.assertEqual(result["slot_id"], "music-secrets")

    def test_receipt_marker_also_prevents_reselection(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_batch(root, "2026-11-22", {"production-tech"})
            receipts = root / ".autopilot" / "public-youtube-receipts"
            receipts.mkdir(parents=True)
            (receipts / "2026-11-22-production-tech.json").write_text(
                json.dumps({"status": "uploaded_public"}),
                encoding="utf-8",
            )
            result = select_next_public_plan(root, after_date="2026-11-22")
        self.assertFalse(result["ready"])
        self.assertEqual(result["slot_status"], "blocked")

    def test_old_batches_are_not_reintroduced_into_the_queue(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_batch(root, "2026-11-21", {"production-tech"})
            result = select_next_public_plan(root, after_date="2026-11-22")
        self.assertFalse(result["ready"])

    def test_private_or_incomplete_metadata_is_not_queue_eligible(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = self._write_batch(root, "2026-11-22", {"production-tech"})
            batch = json.loads(path.read_text(encoding="utf-8"))
            plan = next(item for item in batch["plans"] if item["slot_id"] == "production-tech")
            plan["publish_metadata"]["privacy_status"] = "private"
            path.write_text(json.dumps(batch), encoding="utf-8")
            result = select_next_public_plan(root, after_date="2026-11-22")
        self.assertFalse(result["ready"])


if __name__ == "__main__":
    unittest.main()
