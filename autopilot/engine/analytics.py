"""Scheduled, read-only YouTube report collection and SEO-only learning.

This module is invoked by Phase 5's weekly/manual report workflow. It does not poll
continuously and is intentionally not invoked by the video-render stage.
"""
from __future__ import annotations

import json
import os
from datetime import date, timedelta
from typing import Any

import requests

try:
    from .seo_intelligence import learn as learn_seo
except ImportError:  # Direct script execution from the engine directory.
    from seo_intelligence import learn as learn_seo


TOKEN_URL = "https://oauth2.googleapis.com/token"
ANALYTICS_URL = "https://youtubeanalytics.googleapis.com/v2/reports"
VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
USER_AGENT = "ViolinPrinceAutopilot/Phase5-SEO-Learn"


def _report_rows(report: dict[str, Any]) -> list[dict[str, Any]]:
    headers = [item.get("name") for item in report.get("columnHeaders", [])]
    return [dict(zip(headers, raw)) for raw in report.get("rows", [])]


def _number(row: dict[str, Any], field: str) -> float | None:
    value = row.get(field)
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _video_metadata(
    session: requests.Session,
    access_token: str,
    video_ids: list[str],
) -> dict[str, dict[str, Any]]:
    """Read the exact uploaded metadata to associate report rows with SEO context."""
    if not video_ids:
        return {}
    response = session.get(
        VIDEOS_URL,
        headers={"Authorization": "Bearer " + access_token},
        params={
            "part": "snippet",
            "id": ",".join(video_ids[:50]),
            "maxResults": min(50, len(video_ids)),
        },
        timeout=30,
    )
    response.raise_for_status()
    output = {}
    for item in response.json().get("items", []):
        snippet = item.get("snippet") or {}
        tags = snippet.get("tags") or []
        clean_tags = [str(tag).strip()[:60] for tag in tags if str(tag).strip()][:5]
        output[str(item.get("id") or "")] = {
            "title": str(snippet.get("title") or "")[:140],
            "default_language": str(
                snippet.get("defaultLanguage") or snippet.get("defaultAudioLanguage") or ""
            )[:12],
            "tags": clean_tags,
            "primary_keyword": clean_tags[0] if clean_tags else "",
        }
    return output


def _language_code(video: dict[str, Any]) -> str:
    declared = str(video.get("default_language") or "").lower()
    for code in ("en", "hi", "bn"):
        if declared.startswith(code):
            return code
    title = str(video.get("title") or "")
    if any(0x0980 <= ord(char) <= 0x09FF for char in title):
        return "bn"
    if any(0x0900 <= ord(char) <= 0x097F for char in title):
        return "hi"
    # Latin characters alone do not prove that a video is English.
    return "unknown"


def _youtube_search_terms(
    session: requests.Session,
    access_token: str,
    period_start: str,
    period_end: str,
    videos: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Collect YouTube search terms with accurate distinct-video support counts."""
    ids_by_language: dict[str, list[str]] = {"en": [], "hi": [], "bn": []}
    for video in videos:
        video_id = str(video.get("video_id") or "").strip()
        language = _language_code(video)
        if video_id and language in ids_by_language:
            ids_by_language[language].append(video_id)

    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    errors = []
    queries_executed = 0
    auth_headers = {"Authorization": "Bearer " + access_token}
    for language, raw_video_ids in ids_by_language.items():
        distinct_ids = list(dict.fromkeys(raw_video_ids))
        if len(distinct_ids) < 3:
            continue
        # Query three videos individually to prove each search phrase's support count.
        for video_id in distinct_ids[:3]:
            try:
                response = session.get(
                    ANALYTICS_URL,
                    headers=auth_headers,
                    params={
                        "ids": "channel==MINE",
                        "startDate": period_start,
                        "endDate": period_end,
                        "metrics": "views",
                        "dimensions": "insightTrafficSourceDetail",
                        "filters": "video==" + video_id + ";insightTrafficSourceType==YT_SEARCH",
                        "maxResults": 25,
                        "sort": "-views",
                    },
                    timeout=45,
                )
                queries_executed += 1
                response.raise_for_status()
                for row in _report_rows(response.json()):
                    term = re.sub(r"\s+", " ", str(row.get("insightTrafficSourceDetail") or "")).strip()[:160]
                    views = _number(row, "views")
                    if not term or views is None or views <= 0:
                        continue
                    key = (language, term.casefold())
                    item = grouped.setdefault(key, {
                        "language": language,
                        "search_term": term,
                        "views": 0.0,
                        "video_ids": set(),
                    })
                    item["views"] += views
                    item["video_ids"].add(video_id)
            except Exception as exc:
                errors.append({
                    "language": language,
                    "video_id": video_id,
                    "error": str(exc)[:250],
                })

    output = [
        {
            "language": item["language"],
            "search_term": item["search_term"],
            "views": item["views"],
            "video_sample_count": len(item["video_ids"]),
        }
        for item in grouped.values()
    ]
    output.sort(key=lambda item: item["views"], reverse=True)
    return output[:18], {
        "available": bool(output),
        "language_groups_queried": [
            language for language, ids in ids_by_language.items() if len(set(ids)) >= 3
        ],
        "queries_executed": queries_executed,
        "errors": errors[:9],
        "note": (
            "Each eligible language samples three videos individually. A term's support count "
            "is the number of separate video reports that returned the exact term. Only terms "
            "reported for all three sampled videos can influence Discover. These are reported "
            "traffic sources, not total search demand."
        ),
    }


def collect_and_send(api_url: str, job_token: str) -> dict[str, Any]:
    required = ("YOUTUBE_CLIENT_ID", "YOUTUBE_CLIENT_SECRET", "YOUTUBE_REFRESH_TOKEN")
    if not all(os.environ.get(name) for name in required):
        print("Phase 5 SEO learning skipped: YouTube OAuth credentials are not configured.")
        return {"connected": False, "reason": "credentials_missing"}

    session = requests.Session()
    session.headers["User-Agent"] = USER_AGENT
    try:
        token_response = session.post(
            TOKEN_URL,
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
        channel_start = end_day - timedelta(days=6)
        video_start = end_day - timedelta(days=27)
        auth_headers = {"Authorization": "Bearer " + access_token}

        channel_response = session.get(
            ANALYTICS_URL,
            headers=auth_headers,
            params={
                "ids": "channel==MINE",
                "startDate": channel_start.isoformat(),
                "endDate": end_day.isoformat(),
                "metrics": "views,estimatedMinutesWatched,averageViewDuration,subscribersGained,likes,comments,shares",
                "dimensions": "day",
                "sort": "day",
                "maxResults": 30,
            },
            timeout=45,
        )
        channel_response.raise_for_status()
        channel_rows = _report_rows(channel_response.json())

        def total(metric: str) -> float:
            return round(sum(float(row.get(metric) or 0) for row in channel_rows), 2)

        channel_views = total("views")
        channel_watch_minutes = total("estimatedMinutesWatched")
        weighted_duration = 0.0
        if channel_views:
            weighted_duration = sum(
                float(row.get("averageViewDuration") or 0) * float(row.get("views") or 0)
                for row in channel_rows
            ) / channel_views

        # Phase 5 uses one bounded 28-day per-video report, not continuous polling.
        video_report = {
            "rows": [],
            "available": False,
            "reason": "",
        }
        try:
            response = session.get(
                ANALYTICS_URL,
                headers=auth_headers,
                params={
                    "ids": "channel==MINE",
                    "startDate": video_start.isoformat(),
                    "endDate": end_day.isoformat(),
                    "metrics": "views,estimatedMinutesWatched,averageViewDuration,averageViewPercentage,likes,comments,shares,subscribersGained",
                    "dimensions": "video",
                    "sort": "-views",
                    "maxResults": 15,
                },
                timeout=45,
            )
            response.raise_for_status()
            video_report["rows"] = _report_rows(response.json())
            video_report["available"] = True
        except Exception as exc:
            video_report["reason"] = str(exc)[:300]
            print("Per-video SEO learning report unavailable: " + video_report["reason"])

        raw_video_rows = video_report["rows"][:15]
        video_ids = [
            str(row.get("video") or "").strip()
            for row in raw_video_rows
            if str(row.get("video") or "").strip()
        ]
        video_metadata = {}
        if video_ids:
            try:
                video_metadata = _video_metadata(session, access_token, video_ids)
            except Exception as exc:
                print("Video metadata enrichment unavailable: " + str(exc)[:220])

        per_video = []
        for row in raw_video_rows:
            video_id = str(row.get("video") or "").strip()
            meta = video_metadata.get(video_id, {})
            tags = meta.get("tags", [])
            per_video.append({
                "video_id": video_id,
                "title": meta.get("title", ""),
                "default_language": meta.get("default_language", ""),
                "language": _language_code(meta),
                "primary_keyword": meta.get("primary_keyword", ""),
                "seo_context": {
                    "primary_keyword": meta.get("primary_keyword", ""),
                    "tags": tags,
                },
                "views": _number(row, "views"),
                "watch_minutes": _number(row, "estimatedMinutesWatched"),
                "average_view_duration_seconds": _number(row, "averageViewDuration"),
                "average_view_percentage": _number(row, "averageViewPercentage"),
                "likes": _number(row, "likes"),
                "comments": _number(row, "comments"),
                "shares": _number(row, "shares"),
                "subscribers_gained": _number(row, "subscribersGained"),
            })

        search_terms, search_terms_report = _youtube_search_terms(
            session,
            access_token,
            video_start.isoformat(),
            end_day.isoformat(),
            per_video,
        )
        learning = learn_seo({
            "period": {
                "start": video_start.isoformat(),
                "end": end_day.isoformat(),
                "days": 28,
            },
            "videos": per_video,
            "search_terms": search_terms,
        }, minimum_group_size=3)

        payload = {
            "platform": "youtube",
            "period": {
                "start": channel_start.isoformat(),
                "end": end_day.isoformat(),
                "days": 7,
            },
            "totals": {
                "views": int(channel_views),
                "watch_minutes": round(channel_watch_minutes, 1),
                "average_view_duration_seconds": round(weighted_duration, 1),
                "subscribers_gained": int(total("subscribersGained")),
                "likes": int(total("likes")),
                "comments": int(total("comments")),
                "shares": int(total("shares")),
            },
            "daily_rows": channel_rows[:30],
            "seo_learning_period": {
                "start": video_start.isoformat(),
                "end": end_day.isoformat(),
                "days": 28,
            },
            "per_video_report_available": video_report["available"],
            "per_video_report_reason": video_report["reason"],
            "per_video": per_video,
            "search_terms_report": search_terms_report,
            "search_terms": search_terms,
            "seo_learning": learning,
            "captured_at": date.today().isoformat(),
        }
        serialized_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(serialized_payload) > 18000:
            # Keep the D1 payload safely below the Worker request ceiling.
            payload["per_video"] = payload["per_video"][:8]
            learning = learn_seo({
                "period": payload["seo_learning_period"],
                "videos": payload["per_video"],
                "search_terms": payload.get("search_terms", []),
            }, minimum_group_size=3)
            payload["seo_learning"] = learning
            serialized_payload = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(serialized_payload) > 20000:
            raise RuntimeError("SEO learning report is too large for the configured Worker storage limit.")

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
        print(
            "Phase 5 SEO learning report stored. "
            f"Per-video rows: {len(per_video)}; learning ready: {learning.get('learning_ready')}."
        )
        return {"connected": True, "payload": payload}
    except Exception as exc:
        # Analytics is optional and read-only; report failures never trigger upload retries.
        print("YouTube Analytics unavailable: " + str(exc)[:500])
        return {"connected": False, "reason": str(exc)[:500]}


if __name__ == "__main__":
    api_url = os.environ.get("AUTOPILOT_API_URL", "").strip()
    job_token = os.environ.get("AUTOPILOT_JOB_TOKEN", "").strip()
    if not api_url or not job_token:
        print("Phase 5 SEO learning skipped: AUTOPILOT_API_URL or AUTOPILOT_JOB_TOKEN is missing.")
        raise SystemExit(0)
    result = collect_and_send(api_url, job_token)
    raise SystemExit(0 if result.get("connected") or result.get("reason") == "credentials_missing" else 1)
