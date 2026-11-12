"""Optional, read-only YouTube Analytics collector."""
import os
from datetime import date, timedelta

import requests


def collect_and_send(api_url: str, job_token: str) -> dict:
    required = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    if not all(os.environ.get(name) for name in required):
        print("YouTube Analytics skipped: OAuth credentials are not configured.")
        return {"connected": False, "reason": "credentials_missing"}

    session = requests.Session()
    session.headers["User-Agent"] = "ViolinPrinceAutopilot/0.1"
    try:
        token_response = session.post(
            "https://oauth2.googleapis.com/token",
            data={
                "client_id": os.environ["YOUTUBE_CLIENT_ID"],
                "client_secret": os.environ["YOUTUBE_CLIENT_SECRET"],
                "refresh_token": os.environ["YOUTUBE_REFRESH_TOKEN"],
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        token_response.raise_for_status()
        access_token = token_response.json().get("access_token")
        if not access_token:
            raise RuntimeError("Google OAuth did not return an access token.")

        end_day = date.today() - timedelta(days=1)
        start_day = end_day - timedelta(days=6)
        response = session.get(
            "https://youtubeanalytics.googleapis.com/v2/reports",
            headers={"Authorization": "Bearer " + access_token},
            params={
                "ids": "channel==MINE",
                "startDate": start_day.isoformat(),
                "endDate": end_day.isoformat(),
                "metrics": "views,estimatedMinutesWatched,averageViewDuration,subscribersGained,likes,comments,shares",
                "dimensions": "day",
                "sort": "day",
                "maxResults": 30,
            },
            timeout=45,
        )
        response.raise_for_status()
        report = response.json()
        headers = [item.get("name") for item in report.get("columnHeaders", [])]
        rows = []
        for raw in report.get("rows", []):
            row = dict(zip(headers, raw))
            rows.append(row)

        def total(metric):
            return round(sum(float(row.get(metric) or 0) for row in rows), 2)

        views = total("views")
        watched = total("estimatedMinutesWatched")
        weighted_duration = 0.0
        if views:
            weighted_duration = sum(
                float(row.get("averageViewDuration") or 0) * float(row.get("views") or 0)
                for row in rows
            ) / views

        payload = {
            "platform": "youtube",
            "period": {
                "start": start_day.isoformat(),
                "end": end_day.isoformat(),
                "days": 7,
            },
            "totals": {
                "views": int(views),
                "watch_minutes": round(watched, 1),
                "average_view_duration_seconds": round(weighted_duration, 1),
                "subscribers_gained": int(total("subscribersGained")),
                "likes": int(total("likes")),
                "comments": int(total("comments")),
                "shares": int(total("shares")),
            },
            "daily_rows": rows[:30],
            "captured_at": date.today().isoformat(),
        }
        stored = session.post(
            api_url.rstrip("/") + "/internal/insights",
            headers={
                "Authorization": "Bearer " + job_token,
                "Content-Type": "application/json",
            },
            json={"platform": "youtube", "payload": payload},
            timeout=30,
        )
        stored.raise_for_status()
        print("YouTube Analytics collected for the previous seven complete days.")
        return {"connected": True, "payload": payload}
    except Exception as exc:
        # Analytics is optional. Do not fail or consume another production attempt.
        print("YouTube Analytics unavailable: " + str(exc)[:500])
        return {"connected": False, "reason": str(exc)[:500]}
