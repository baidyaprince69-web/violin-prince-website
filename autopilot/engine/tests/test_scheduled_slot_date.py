from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from scheduled_slot_date import resolve_scheduled_production_date

IST = ZoneInfo("Asia/Kolkata")


class ScheduledSlotDateTests(unittest.TestCase):
    def test_late_2330_ist_trigger_after_midnight_keeps_previous_local_date(self):
        now = datetime(2026, 11, 22, 0, 12, tzinfo=IST)
        result = resolve_scheduled_production_date("30 23 * * *", now=now)

        self.assertEqual(result["production_date"], "2026-11-21")
        self.assertEqual(result["scheduled_slot_ist"], "2026-11-21 23:30 IST")
        self.assertEqual(result["delay_minutes"], 42)

    def test_late_daytime_trigger_keeps_its_local_date(self):
        now = datetime(2026, 11, 22, 17, 42, tzinfo=IST)
        result = resolve_scheduled_production_date("30 17 * * *", now=now)

        self.assertEqual(result["production_date"], "2026-11-22")
        self.assertEqual(result["scheduled_slot_ist"], "2026-11-22 17:30 IST")
        self.assertEqual(result["delay_minutes"], 12)

    def test_all_four_cron_expressions_map_to_their_ist_slots(self):
        cases = (
            ("30 5 * * *", datetime(2026, 11, 22, 5, 35, tzinfo=IST), "05:30", "music-secrets"),
            ("30 11 * * *", datetime(2026, 11, 22, 11, 35, tzinfo=IST), "11:30", "production-tech"),
            ("30 17 * * *", datetime(2026, 11, 22, 17, 35, tzinfo=IST), "17:30", "melody-stories"),
            ("30 23 * * *", datetime(2026, 11, 22, 23, 35, tzinfo=IST), "23:30", "real-performance"),
        )
        for cron, now, expected_time, expected_slot in cases:
            with self.subTest(cron=cron):
                result = resolve_scheduled_production_date(cron, now=now)
                self.assertEqual(result["production_date"], "2026-11-22")
                self.assertEqual(result["slot_id"], expected_slot)
                self.assertTrue(str(result["scheduled_slot_ist"]).endswith(expected_time + " IST"))

    def test_run_six_hours_late_fails_closed(self):
        now = datetime(2026, 11, 22, 11, 30, tzinfo=IST)
        with self.assertRaisesRegex(ValueError, "at least six hours old"):
            resolve_scheduled_production_date("30 5 * * *", now=now)

    def test_unknown_schedule_expression_fails_closed(self):
        now = datetime(2026, 11, 22, 0, 12, tzinfo=IST)
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            resolve_scheduled_production_date("15 18 * * *", now=now)

    def test_naive_clock_value_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            resolve_scheduled_production_date(
                "30 23 * * *", now=datetime(2026, 11, 22, 0, 12)
            )


if __name__ == "__main__":
    unittest.main()
