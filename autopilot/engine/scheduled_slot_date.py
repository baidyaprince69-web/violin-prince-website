#!/usr/bin/env python3
"""Resolve the intended Asia/Kolkata batch date for a delayed scheduled run.

GitHub's schedule event exposes the cron expression, not the original scheduled
timestamp. Each of the four cron expressions is unique to one production slot and
repeats once per local day. The intended batch date is therefore the date of the
most recent occurrence of that exact cron in Asia/Kolkata. A delay of several
hours does not make the date ambiguous; rejecting it at the six-hour distance
between different slots incorrectly discards valid delayed runs.

GitHub does not expose the original enqueue timestamp in the schedule payload.
This resolver assumes a delayed event is less than one full daily recurrence old;
the durable date/slot attempt and research-history checks provide the duplicate
protection after resolution.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

TIMEZONE = "Asia/Kolkata"
IST = ZoneInfo(TIMEZONE)
MAX_UNAMBIGUOUS_DELAY = timedelta(days=1)
CRON_TO_IST_SLOT = {
    "30 5 * * *": time(5, 30),
    "30 11 * * *": time(11, 30),
    "30 17 * * *": time(17, 30),
    "30 23 * * *": time(23, 30),
}

CRON_TO_SLOT_ID = {
    "30 5 * * *": "music-secrets",
    "30 11 * * *": "production-tech",
    "30 17 * * *": "melody-stories",
    "30 23 * * *": "real-performance",
}


def resolve_scheduled_production_date(
    schedule_cron: str,
    *,
    now: datetime | None = None,
) -> dict[str, str | int]:
    """Resolve the most recent daily occurrence of the exact cron expression."""
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
    if delay >= MAX_UNAMBIGUOUS_DELAY:
        raise ValueError(
            f"Scheduled slot {cron!r} is at least one daily recurrence old "
            f"({int(delay.total_seconds() // 60)} minutes late). "
            "The original occurrence cannot be distinguished from a newer daily event."
        )

    return {
        "production_date": scheduled_local.date().isoformat(),
        "scheduled_slot_ist": scheduled_local.strftime("%Y-%m-%d %H:%M %Z"),
        "delay_minutes": int(delay.total_seconds() // 60),
        "schedule_cron": cron,
        "slot_id": CRON_TO_SLOT_ID[cron],
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
