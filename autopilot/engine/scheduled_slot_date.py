#!/usr/bin/env python3
"""Resolve the intended Asia/Kolkata batch date for a delayed scheduled run.

GitHub's schedule event exposes the cron expression, not the original scheduled
timestamp. The four offset cron expressions map to fixed IST slots six hours apart.
The nearest preceding slot is therefore unambiguous only while the run is less
than six hours late. Older/ambiguous runs fail closed instead of choosing a
different day's batch.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

TIMEZONE = "Asia/Kolkata"
IST = ZoneInfo(TIMEZONE)
SLOT_INTERVAL = timedelta(hours=6)
CRON_TO_IST_SLOT = {
    "30 5 * * *": time(5, 30),
    "30 11 * * *": time(11, 30),
    "30 17 * * *": time(17, 30),
    "30 23 * * *": time(23, 30),
}


def resolve_scheduled_production_date(
    schedule_cron: str,
    *,
    now: datetime | None = None,
) -> dict[str, str | int]:
    """Resolve the date of the cron slot, rejecting runs delayed by six hours."""
    cron = " ".join(str(schedule_cron or "").split())
    slot_time = CRON_TO_IST_SLOT.get(cron)
    if slot_time is None:
        raise ValueError(
            "Unsupported GitHub schedule cron expression; refusing to guess a production date."
        )

    instant = now or datetime.now(timezone.utc)
    if instant.tzinfo is None or instant.utcoffset() is None:
        raise ValueError("now must be timezone-aware.")

    local_now = instant.astimezone(IST)
    scheduled_local = datetime.combine(local_now.date(), slot_time, tzinfo=IST)
    if scheduled_local > local_now:
        scheduled_local -= timedelta(days=1)

    delay = local_now - scheduled_local
    if delay >= SLOT_INTERVAL:
        raise ValueError(
            f"Scheduled slot {cron!r} is at least six hours old "
            f"({int(delay.total_seconds() // 60)} minutes late). "
            "The original occurrence is ambiguous; no production batch was selected."
        )

    return {
        "production_date": scheduled_local.date().isoformat(),
        "scheduled_slot_ist": scheduled_local.strftime("%Y-%m-%d %H:%M %Z"),
        "delay_minutes": int(delay.total_seconds() // 60),
        "schedule_cron": cron,
        "timezone": TIMEZONE,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cron", required=True, help="Exact value of github.event.schedule.")
    parser.add_argument(
        "--now",
        default=None,
        help="Optional timezone-aware ISO timestamp for deterministic tests.",
    )
    args = parser.parse_args(argv)

    now = datetime.fromisoformat(args.now) if args.now else None
    result = resolve_scheduled_production_date(args.cron, now=now)

    output_path = os.environ.get("GITHUB_OUTPUT", "").strip()
    if output_path:
        with open(output_path, "a", encoding="utf-8") as output:
            for key, value in result.items():
                output.write(f"{key}={value}\n")

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as summary:
            summary.write(
                "## Scheduled slot date resolution\n\n"
                f"- **Cron:** {result['schedule_cron']}\n"
                f"- **Intended IST slot:** {result['scheduled_slot_ist']}\n"
                f"- **Production batch date:** {result['production_date']}\n"
                f"- **Delay:** {result['delay_minutes']} minutes\n"
                "- The selector is pinned to this exact date and cannot fall forward.\n"
            )

    print(
        f"Resolved {result['schedule_cron']} to {result['scheduled_slot_ist']} "
        f"(batch {result['production_date']}; {result['delay_minutes']} minutes late)."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
