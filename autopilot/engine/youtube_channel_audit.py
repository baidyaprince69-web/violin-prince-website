"""Read-only YouTube uploads-playlist audit used by the publisher duplicate guard."""
from __future__ import annotations

import os
import re
import unicodedata
from typing import Any

import requests


TOKEN_URL = "https://oauth2.googleapis.com/token"
API_ROOT = "https://www.googleapis.com/youtube/v3"
DEFAULT_MAX_PAGES = 30


class ChannelAuditError(RuntimeError):
    """The channel uploads list could not be verified completely."""


class DuplicateVideoFound(ChannelAuditError):
    """The target title already appears in the authenticated channel uploads."""

    def __init__(self, matches: list[dict[str, str]]):
        self.matches = matches
        super().__init__("A video with the target title already exists in channel uploads.")


def normalise_title(value: str) -> str:
    """Normalise Unicode and whitespace while retaining meaningful punctuation."""
    text = unicodedata.normalize("NFKC", str(value or ""))
    return re.sub(r"\\s+", " ", text).strip().casefold()


def _required(env: dict[str, str], name: str) -> str:
    value = str(env.get(name, "")).strip()
    if not value:
        raise ChannelAuditError("Missing required YouTube credential or variable: " + name)
    return value


def _request_json(response: requests.Response, label: str) -> dict[str, Any]:
    try:
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ChannelAuditError(label + " request failed: " + str(exc)[:300]) from exc
    if not isinstance(payload, dict):
        raise ChannelAuditError(label + " returned a non-object response.")
    return payload


def scan_uploads_playlist(
    *,
    env: dict[str, str] | None = None,
    session: requests.Session | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> dict[str, Any]:
    """Verify the target channel and read its complete uploads playlist.

    The scan intentionally includes public, unlisted and private uploads. That is
    stricter than a public-Shorts-only scan and prevents a previously uploaded
    private or unlisted copy from being published again under the same title.
    """
    config = dict(os.environ if env is None else env)
    client_id = _required(config, "YOUTUBE_CLIENT_ID")
    client_secret = _required(config, "YOUTUBE_CLIENT_SECRET")
    refresh_token = _required(config, "YOUTUBE_REFRESH_TOKEN")
    expected_channel_id = _required(config, "YOUTUBE_EXPECTED_CHANNEL_ID")
    if not isinstance(max_pages, int) or max_pages < 1:
        raise ChannelAuditError("max_pages must be a positive integer.")

    client = session or requests.Session()
    try:
        token_response = client.post(
            TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        token_payload = _request_json(token_response, "Google OAuth refresh")
    except requests.RequestException as exc:
        raise ChannelAuditError("Google OAuth refresh failed: " + str(exc)[:300]) from exc

    access_token = str(token_payload.get("access_token") or "").strip()
    if not access_token:
        raise ChannelAuditError("Google OAuth refresh returned no access token.")

    headers = {"Authorization": "Bearer " + access_token}
    try:
        channel_response = client.get(
            API_ROOT + "/channels",
            params={"part": "id,contentDetails", "mine": "true"},
            headers=headers,
            timeout=30,
        )
        channel_payload = _request_json(channel_response, "YouTube channel verification")
    except requests.RequestException as exc:
        raise ChannelAuditError("YouTube channel verification failed: " + str(exc)[:300]) from exc

    channels = channel_payload.get("items")
    if not isinstance(channels, list):
        raise ChannelAuditError("YouTube channel verification returned no channel list.")
    channel = next(
        (item for item in channels if isinstance(item, dict) and item.get("id") == expected_channel_id),
        None,
    )
    if channel is None:
        raise ChannelAuditError("OAuth did not verify the configured Violin Prince channel ID.")

    playlist_id = str(
        ((channel.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads") or ""
    ).strip()
    if not playlist_id:
        raise ChannelAuditError("The verified channel did not return its uploads playlist ID.")

    uploads: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    next_page_token = ""
    pages_checked = 0
    while True:
        params: dict[str, Any] = {
            "part": "snippet,contentDetails",
            "playlistId": playlist_id,
            "maxResults": 50,
        }
        if next_page_token:
            params["pageToken"] = next_page_token
        try:
            page_response = client.get(
                API_ROOT + "/playlistItems",
                params=params,
                headers=headers,
                timeout=45,
            )
            page_payload = _request_json(page_response, "YouTube uploads playlist")
        except requests.RequestException as exc:
            raise ChannelAuditError("YouTube uploads playlist scan failed: " + str(exc)[:300]) from exc

        items = page_payload.get("items")
        if not isinstance(items, list):
            raise ChannelAuditError("YouTube uploads playlist returned no valid item list.")
        for item in items:
            if not isinstance(item, dict):
                continue
            snippet = item.get("snippet") or {}
            details = item.get("contentDetails") or {}
            resource = snippet.get("resourceId") or {}
            video_id = str(details.get("videoId") or resource.get("videoId") or "").strip()
            if not video_id or video_id in seen_ids:
                continue
            seen_ids.add(video_id)
            uploads.append({
                "video_id": video_id,
                "title": str(snippet.get("title") or "").strip(),
                "published_at": str(
                    snippet.get("publishedAt") or details.get("videoPublishedAt") or ""
                ).strip(),
            })

        pages_checked += 1
        next_page_token = str(page_payload.get("nextPageToken") or "").strip()
        if not next_page_token:
            break
        if pages_checked >= max_pages:
            raise ChannelAuditError(
                "Uploads playlist exceeds the configured page limit; duplicate status is incomplete."
            )

    return {
        "channel_id": expected_channel_id,
        "uploads_playlist_id": playlist_id,
        "uploads_checked_pages": pages_checked,
        "uploads_examined": len(uploads),
        "uploads": uploads,
    }


def assert_title_absent(
    target_title: str,
    *,
    env: dict[str, str] | None = None,
    session: requests.Session | None = None,
    max_pages: int = DEFAULT_MAX_PAGES,
) -> dict[str, Any]:
    """Return an audit summary only when a complete scan finds no title match."""
    canonical_target = normalise_title(target_title)
    if not canonical_target:
        raise ChannelAuditError("The candidate YouTube title is empty.")

    audit = scan_uploads_playlist(env=env, session=session, max_pages=max_pages)
    matches = [
        {
            "video_id": item["video_id"],
            "title": item["title"],
            "published_at": item["published_at"],
        }
        for item in audit["uploads"]
        if normalise_title(item.get("title", "")) == canonical_target
    ]
    if matches:
        raise DuplicateVideoFound(matches)

    return {
        "status": "passed",
        "match_count": 0,
        "channel_id": audit["channel_id"],
        "uploads_checked_pages": audit["uploads_checked_pages"],
        "uploads_examined": audit["uploads_examined"],
    }
