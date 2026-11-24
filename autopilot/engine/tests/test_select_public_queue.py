from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from select_public_queue import select_next_public_plan
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

            result = select_next_public_plan(root, production_date="2026-11-21")

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


    def test_skips_a_topic_already_researched_in_an_older_batch(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_batch(root, "2026-11-21", "production-tech")
            self._write_batch(root, "2026-11-22", "melody-stories")
            old_path = root / ".autopilot" / "daily-batches" / "2026-11-21.json"
            old_batch = json.loads(old_path.read_text(encoding="utf-8"))
            old_plan = next(p for p in old_batch["plans"] if p["slot_id"] == "production-tech")
            old_plan["topic"] = "How a violin bridge shapes resonance and tone"
            old_plan["core_claim"] = "A violin bridge shapes resonance and tone."
            old_path.write_text(json.dumps(old_batch), encoding="utf-8")

            current_path = root / ".autopilot" / "daily-batches" / "2026-11-22.json"
            current_batch = json.loads(current_path.read_text(encoding="utf-8"))
            current_plan = next(p for p in current_batch["plans"] if p["slot_id"] == "melody-stories")
            current_plan["topic"] = "How violin bridge resonance shapes the sound"
            current_path.write_text(json.dumps(current_batch), encoding="utf-8")

            result = select_next_public_plan(root, production_date="2026-11-22")

        self.assertFalse(result["ready"])
        self.assertEqual(len(result["duplicate_topic_matches"]), 1)
        self.assertIn("previous topic", result["duplicate_topic_matches"][0])

    def test_skips_repeated_topic_even_when_previous_slot_was_blocked(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_batch(root, "2026-11-22", "production-tech")
            path = root / ".autopilot" / "daily-batches" / "2026-11-22.json"
            batch = json.loads(path.read_text(encoding="utf-8"))
            previous = next(p for p in batch["plans"] if p["slot_id"] == "music-secrets")
            previous["topic"] = "Why violin bridge resonance shapes the sound"
            current = next(p for p in batch["plans"] if p["slot_id"] == "production-tech")
            current["topic"] = "How violin bridge resonance shapes the sound"
            path.write_text(json.dumps(batch), encoding="utf-8")

            result = select_next_public_plan(root, production_date="2026-11-22")

        self.assertFalse(result["ready"])
        self.assertEqual(len(result["duplicate_topic_matches"]), 1)
    def test_exact_date_and_rolling_lower_bound_cannot_be_combined(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ValueError, "Use either production_date"):
                select_next_public_plan(
                    temporary,
                    after_date="2026-11-21",
                    production_date="2026-11-21",
                )

    def test_channel_duplicate_is_skipped_before_production(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            self._write_batch(root, "2026-11-22", "production-tech")
            existing = {"production & audio tech story for 2026-11-22"}

            result = select_next_public_plan(
                root,
                production_date="2026-11-22",
                existing_titles=existing,
            )

        self.assertFalse(result["ready"])
        self.assertEqual(len(result["duplicate_channel_matches"]), 1)
        self.assertIn("already present", result["blocked_reason"].lower())

    def test_selector_moves_to_next_ready_story_when_first_title_already_exists(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            batch = self._batch("2026-11-22", "production-tech")
            for plan in batch["plans"]:
                if plan["slot_id"] == "melody-stories":
                    plan.update({
                        "slot_status": "ready",
                        "title": "Melody Stories story for 2026-11-22",
                        "narration_script": "A complete four-sentence narration script.",
                        "publish_metadata": {
                            "privacy_status": "public",
                            "title": "Melody Stories story for 2026-11-22",
                        },
                    })
            path = root / ".autopilot" / "daily-batches" / "2026-11-22.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(batch), encoding="utf-8")
            existing = {"production & audio tech story for 2026-11-22"}

            result = select_next_public_plan(
                root,
                production_date="2026-11-22",
                existing_titles=existing,
            )

        self.assertTrue(result["ready"])
        self.assertEqual(result["slot_id"], "melody-stories")
        self.assertEqual(len(result["duplicate_channel_matches"]), 1)


if __name__ == "__main__":
    unittest.main()
