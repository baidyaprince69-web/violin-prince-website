from __future__ import annotations
import json
import tempfile
import unittest
from pathlib import Path
from slot_registry import SLOT_CATALOG, SlotContractError, load_daily_batch, production_identity, slot_workspace, write_slot_receipt

class FourSlotContractTests(unittest.TestCase):
    def batch(self):
        date = "2026-11-21"
        return {"production_date": date, "plans": [
            {"production_date": date, "slot_id": slot, "title": SLOT_CATALOG[slot],
             "narration_script": "A distinct narration."} for slot in SLOT_CATALOG
        ]}

    def test_accepts_exactly_four_slots(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "batch.json"
            path.write_text(json.dumps(self.batch()), encoding="utf-8")
            plans = load_daily_batch(path, expected_date="2026-11-21")
        self.assertEqual([p["slot_id"] for p in plans], list(SLOT_CATALOG))

    def test_rejects_duplicate_slot(self):
        batch = self.batch()
        batch["plans"][-1]["slot_id"] = batch["plans"][0]["slot_id"]
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "batch.json"
            path.write_text(json.dumps(batch), encoding="utf-8")
            with self.assertRaisesRegex(SlotContractError, "Duplicate"):
                load_daily_batch(path)

    def test_accepts_a_blocked_slot_with_reason_without_placeholder_script(self):
        batch = self.batch()
        blocked = batch["plans"][-1]
        blocked["slot_status"] = "blocked"
        blocked["blocked_reason"] = "No independent source pair was verified."
        blocked.pop("narration_script")
        blocked.pop("title")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "batch.json"
            path.write_text(json.dumps(batch), encoding="utf-8")
            plans = load_daily_batch(path)
        self.assertEqual(plans[-1]["slot_status"], "blocked")

    def test_each_slot_gets_distinct_identity_and_workspace(self):
        identities = {production_identity("2026-11-21", slot) for slot in SLOT_CATALOG}
        paths = {slot_workspace("work/slots", "2026-11-21", slot) for slot in SLOT_CATALOG}
        self.assertEqual(len(identities), 4)
        self.assertEqual(len(paths), 4)

    def test_receipt_persists_slot_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "receipt.json"
            receipt = write_slot_receipt(path, production_date="2026-11-21",
                slot_id="melody-stories", run_id="123", status="preview_rendered",
                output_dir="work/slots/2026-11-21/melody-stories")
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), receipt)
            self.assertEqual(receipt["production_identity"], "2026-11-21:melody-stories")


    def test_committed_next_day_batch_meets_ready_plan_contract_when_present(self):
        """Catch incomplete ChatGPT batches before the next scheduled slot starts."""
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        import re

        root = Path(__file__).resolve().parents[3]
        next_day = (
            datetime.now(ZoneInfo("Asia/Kolkata")).date() + timedelta(days=1)
        ).isoformat()
        batch_path = root / ".autopilot" / "daily-batches" / f"{next_day}.json"
        if not batch_path.is_file():
            self.skipTest(f"No committed next-day batch exists for {next_day}.")
        plans = load_daily_batch(batch_path, expected_date=next_day)
        self.assertEqual(len(plans), 4)
        for plan in plans:
            if plan.get("slot_status", "ready") != "ready":
                continue
            script = str(plan.get("narration_script") or "").strip()
            self.assertEqual(len(re.findall(r"\b[\w’'-]+\b", script)), 35,
                             f"{plan['slot_id']} must have exactly 35 narration words")
            self.assertEqual(len(re.findall(r"[^.!?]+[.!?]+(?=\s|$)", script)), 4,
                             f"{plan['slot_id']} must have exactly four narration sentences")
            self.assertGreaterEqual(len(plan.get("sources") or []), 2,
                                    f"{plan['slot_id']} must select two direct publisher sources")
            self.assertEqual(len(plan.get("narration_evidence") or []), 3,
                             f"{plan['slot_id']} must map evidence to narration sentences 2–4")
            self.assertEqual(len(plan.get("scenes") or []), 3,
                             f"{plan['slot_id']} must define three scenes")
            self.assertTrue(str(plan.get("cover_payoff") or "").strip(),
                            f"{plan['slot_id']} must define its original violin payoff")

if __name__ == "__main__":
    unittest.main()
