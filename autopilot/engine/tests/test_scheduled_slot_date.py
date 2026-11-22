from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from scheduled_slot_date import resolve_scheduled_production_date

IST = ZoneInfo("Asia/Kolkata")


class ScheduledSlotDateTests(unittest.TestCase):
    def test_late_2341_ist_trigger_after_midnight_keeps_previous_local_date(self):
        now = datetime(2026, 11, 22, 0, 24, tzinfo=IST)
        result = resolve_scheduled_production_date("11 18 * * *", now=now)

        self.assertEqual(result["production_date"], "2026-11-21")
        self.assertEqual(result["scheduled_slot_ist"], "2026-11-21 23:41 IST")
        self.assertEqual(result["delay_minutes"], 43)

    def test_late_daytime_trigger_keeps_its_local_date(self):
        now = datetime(2026, 11, 22, 17, 53, tzinfo=IST)
        result = resolve_scheduled_production_date("11 12 * * *", now=now)

        self.assertEqual(result["production_date"], "2026-11-22")
        self.assertEqual(result["scheduled_slot_ist"], "2026-11-22 17:41 IST")
        self.assertEqual(result["delay_minutes"], 12)

    def test_all_four_cron_expressions_map_to_their_ist_slots(self):
        cases = (
            ("11 0 * * *", datetime(2026, 11, 22, 5, 46, tzinfo=IST), "05:41"),
            ("11 6 * * *", datetime(2026, 11, 22, 11, 46, tzinfo=IST), "11:41"),
            ("11 12 * * *", datetime(2026, 11, 22, 17, 46, tzinfo=IST), "17:41"),
            ("11 18 * * *", datetime(2026, 11, 22, 23, 46, tzinfo=IST), "23:41"),
        )
        for cron, now, expected_time in cases:
            with self.subTest(cron=cron):
                result = resolve_scheduled_production_date(cron, now=now)
                self.assertEqual(result["production_date"], "2026-11-22")
                self.assertTrue(str(result["scheduled_slot_ist"]).endswith(expected_time + " IST"))

    def test_run_six_hours_late_fails_closed(self):
        now = datetime(2026, 11, 22, 11, 41, tzinfo=IST)
        with self.assertRaisesRegex(ValueError, "at least six hours old"):
            resolve_scheduled_production_date("11 0 * * *", now=now)

    def test_unknown_schedule_expression_fails_closed(self):
        now = datetime(2026, 11, 22, 0, 24, tzinfo=IST)
        with self.assertRaisesRegex(ValueError, "Unsupported"):
            resolve_scheduled_production_date("15 18 * * *", now=now)

    def test_naive_clock_value_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "timezone-aware"):
            resolve_scheduled_production_date(
                "11 18 * * *", now=datetime(2026, 11, 22, 0, 24)
            )


if __name__ == "__main__":
    unittest.main()
