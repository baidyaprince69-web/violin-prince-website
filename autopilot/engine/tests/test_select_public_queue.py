from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from select_public_queue import select_next_private_preview_plan
from slot_registry import SLOT_CATALOG


class ExactProductionDateQueueTests(unittest.TestCase):
    def _batch(self, production_date: str, ready_slot: str) -> dict:
        plans = []
        for slot_id, slot_title in SLOT_CATALOG.items():
            if slot_id == ready_slot:
                plans.append({
                    "production_date": production_date,
                    "slot_id": slot_id,
                    "slot_status": "ready",
                    "title": f"{slot_title} story for {production_date}",
                    "narration_script": "A complete four-sentence narration script.",
                    "publish_metadata": {
                        "privacy_status": "public",
                        "title": f"{slot_title} story for {production_date}",
                    },
                })
            else:
                plans.append({
                    "production_date": production_date,
                    "slot_id": slot_id,
                    "slot_status": "blocked",
                    "blocked_reason": "The slot is not ready.",
                })
        return {"production_date": production_date, "plans": plans}

    def _write_batch(self, root: Path, production_date: str, ready_slot: str) -> None:
        path = root / ".autopilot" / "daily-batches" / f"{production_date}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self._batch(production_date, ready_slot)),
            encoding="utf-8",
        )

    def test_exact_date_selection_does_not_fall_forward_to_next_day(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_batch(root, "2026-11-21", "production-tech")
            self._write_batch(root, "2026-11-22", "melody-stories")

            attempt = (
                root / ".autopilot" / "public-youtube-attempts"
                / "2026-11-21-production-tech.json"
            )
            attempt.parent.mkdir(parents=True, exist_ok=True)
            attempt.write_text('{"status":"attempted"}', encoding="utf-8")

            result = select_next_private_preview_plan(root, production_date="2026-11-21")

        self.assertFalse(result["ready"])
        self.assertEqual(result["slot_status"], "blocked")
        self.assertEqual(result["production_date"], "2026-11-21")
        self.assertEqual(result["checked_batches"], 1)
        self.assertIn("exact 2026-11-21 batch", result["blocked_reason"])
        self.assertNotEqual(result.get("slot_id"), "melody-stories")

    def test_exact_date_selects_a_ready_plan_from_that_date(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_batch(root, "2026-11-21", "production-tech")
            self._write_batch(root, "2026-11-22", "melody-stories")

            result = select_next_public_plan(root, production_date="2026-11-21")

        self.assertTrue(result["ready"])
        self.assertEqual(result["production_date"], "2026-11-21")
        self.assertEqual(result["slot_id"], "production-tech")
        self.assertEqual(result["batch_path"], ".autopilot/daily-batches/2026-11-21.json")

    def test_exact_date_and_rolling_lower_bound_cannot_be_combined(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "Use either production_date"):
                select_next_public_plan(
                    temporary,
                    after_date="2026-11-21",
                    production_date="2026-11-21",
                )


if __name__ == "__main__":
    unittest.main()
