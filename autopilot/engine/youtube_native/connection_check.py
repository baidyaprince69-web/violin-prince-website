"""Read-only OAuth connection check for the Violin Prince YouTube channel."""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta
from typing import Any

import requests

from .engine import API_ROOT, YouTubeNativeClient, YouTubeEngineError
from ..analytics import ANALYTICS_URL


def _summary(channel_title: str, channel_id: str, target_status: str, analytics_status: str) -> None:
    print("YouTube OAuth connection: SUCCESS")
    print("Authorized channel: " + channel_title)
    print("Channel ID: " + channel_id)
    print("Target-channel lock: " + target_status)
    print("YouTube Analytics read access: " + analytics_status)
    print("Upload performed: NO")
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "")
    if summary_path:
        with open(summary_path, "a", encoding="utf-8") as handle:
            handle.write("# YouTube connection check\n\n")
            handle.write("- **Connection:** successful\n")
            handle.write("- **Authorized channel:** " + channel_title.replace("\n", " ") + "\n")
            handle.write("- **Channel ID:** `" + channel_id + "`\n")
            handle.write("- **Target lock:** " + target_status + "\n")
            handle.write("- **Analytics access:** " + analytics_status + "\n")
            handle.write("- **Upload:** not attempted\n")


def main() -> int:
    client = YouTubeNativeClient()
    try:
        access_token = client.refresh_access_token()
        response = client.session.get(
            API_ROOT + "/channels",
            params={"part": "id,snippet", "mine": "true"},
            headers=client._auth(access_token),
            timeout=30,
        )
        response.raise_for_status()
        channels = response.json().get("items", [])
        if not channels:
            raise YouTubeEngineError(
                "Google OAuth succeeded, but the account returned no YouTube channel."
            )

        expected_id = str(os.environ.get("YOUTUBE_EXPECTED_CHANNEL_ID", "")).strip()
        selected = next(
            (item for item in channels if item.get("id") == expected_id),
            channels[0],
        )
        channel_id = str(selected.get("id") or "").strip()
        channel_title = str((selected.get("snippet") or {}).get("title") or "Untitled channel")
        if not channel_id:
            raise YouTubeEngineError("The authorized channel response did not include an ID.")

        if expected_id and expected_id != channel_id:
            raise YouTubeEngineError(
                "Authorized channel ID did not match YOUTUBE_EXPECTED_CHANNEL_ID. "
                "No upload was attempted."
            )
        target_status = (
            "verified against YOUTUBE_EXPECTED_CHANNEL_ID"
            if expected_id else
            "not locked yet; add this channel ID as the repository variable before any upload"
        )

        end_day = date.today() - timedelta(days=1)
        start_day = end_day - timedelta(days=6)
        analytics_response = client.session.get(
            ANALYTICS_URL,
            headers=client._auth(access_token),
            params={
                "ids": "channel==MINE",
                "startDate": start_day.isoformat(),
                "endDate": end_day.isoformat(),
                "metrics": "views",
                "dimensions": "day",
                "maxResults": 1,
            },
            timeout=30,
        )
        analytics_response.raise_for_status()
        _summary(channel_title, channel_id, target_status, "available")
        return 0
    except (requests.RequestException, YouTubeEngineError, ValueError, KeyError) as exc:
        print("YouTube connection check failed: " + str(exc)[:500], file=sys.stderr)
        print("Upload performed: NO")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
