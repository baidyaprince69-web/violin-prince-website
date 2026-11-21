#!/usr/bin/env python3
"""Upload one validated scheduled Violin Prince Short as a PRIVATE preview via Upload-Post.

The uploader is deliberately private-only. It verifies the complete production
bundle, checks the connected channel for an exact-title duplicate, commits a
date/slot attempt guard before contacting Upload-Post, and confirms YouTube's
returned title, channel and privacy status before saving a success receipt.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

import requests

from publish_daily_short import (
    PublishBlocked,
    _git_commit,
    _read_json,
    _summary,
    validate_daily_bundle,
)

ROOT = Path(__file__).resolve().parents[2]
API_ROOT = "https://api.upload-post.com"
DEFAULT_UPLOAD_POST_USER = "default"
MAX_MEDIA_PAGES = 40
POLL_SECONDS = 10
POLL_TIMEOUT_SECONDS = 600


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _normalise_title(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", str(value or ""))).strip().casefold()


def _identity(production_date: str, slot_id: str) -> str:
    raw = f"{production_date}-{slot_id}"
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", raw).strip("-")
    if not value:
        raise PublishBlocked("A stable production-date/slot identity is required.")
    return value


def _youtube_result(payload: dict[str, Any]) -> dict[str, Any] | None:
    results = payload.get("results") or {}
    if isinstance(results, dict):
        item = results.get("youtube")
        return item if isinstance(item, dict) else None
    if isinstance(results, list):
        return next(
            (
                item for item in results
                if isinstance(item, dict) and str(item.get("platform") or "").lower() == "youtube"
            ),
            None,
        )
    return None


def _scan_existing_titles(session: requests.Session, headers: dict[str, str], user: str) -> dict[str, Any]:
    """Read every page of the connected YouTube uploads list before starting a new upload."""
    cursor = ""
    pages = 0
    examined = 0
    titles: set[str] = set()
    while True:
        params: dict[str, Any] = {"platform": "youtube", "user": user, "limit": 50}
        if cursor:
            params["cursor"] = cursor
        response = session.get(
            API_ROOT + "/api/uploadposts/media",
            headers=headers,
            params=params,
            timeout=45,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or payload.get("success") is not True:
            raise PublishBlocked("Upload-Post could not verify the channel's existing YouTube uploads.")
        media = payload.get("media")
        pagination = payload.get("pagination")
        if not isinstance(media, list) or not isinstance(pagination, dict):
            raise PublishBlocked("The YouTube uploads audit returned incomplete pagination data.")
        for item in media:
            if not isinstance(item, dict):
                continue
            for candidate in (item.get("title"), item.get("caption")):
                normalised = _normalise_title(str(candidate or ""))
                if normalised:
                    titles.add(normalised)
            examined += 1
        pages += 1
        has_more = pagination.get("has_more") is True
        if not has_more:
            return {
                "status": "passed",
                "pages_checked": pages,
                "uploads_examined": examined,
                "title_count": len(titles),
                "_normalised_titles": titles,
            }
        next_cursor = str(pagination.get("next_cursor") or "")
        if not next_cursor or pages >= MAX_MEDIA_PAGES:
            raise PublishBlocked(
                "The channel uploads audit did not reach its final page; duplicate status is incomplete."
            )
        cursor = next_cursor


def _extract_video_id(youtube_result: dict[str, Any]) -> str:
    value = str(
        youtube_result.get("platform_post_id")
        or youtube_result.get("post_id")
        or youtube_result.get("video_id")
        or youtube_result.get("id")
        or ""
    ).strip()
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", value):
        return value

    post_url = str(youtube_result.get("post_url") or youtube_result.get("url") or "")
    parsed = urlparse(post_url)
    query_id = parse_qs(parsed.query).get("v", [""])[0]
    path_parts = [part for part in parsed.path.split("/") if part]
    candidate = query_id
    if not candidate and parsed.netloc.lower().endswith("youtu.be"):
        candidate = path_parts[-1] if path_parts else ""
    if not candidate and "youtube.com" in parsed.netloc.lower():
        for marker in ("shorts", "embed", "live"):
            if marker in path_parts:
                index = path_parts.index(marker)
                if index + 1 < len(path_parts):
                    candidate = path_parts[index + 1]
                    break
    if re.fullmatch(r"[A-Za-z0-9_-]{11}", candidate):
        return candidate
    raise PublishBlocked(
        "Upload-Post reported success without a verifiable YouTube video ID; do not retry this slot."
    )


def _poll_upload(
    session: requests.Session,
    headers: dict[str, str],
    request_id: str,
    initial_payload: dict[str, Any],
) -> dict[str, Any]:
    deadline = time.monotonic() + POLL_TIMEOUT_SECONDS
    initial_result = _youtube_result(initial_payload)
    state = str(initial_payload.get("status") or "").lower()
    if state == "completed" and initial_result and initial_result.get("success") is True:
        return initial_payload
    if not request_id:
        if initial_result and initial_result.get("success") is True:
            return initial_payload
        raise PublishBlocked(
            "Upload-Post accepted the request but did not return a pollable request ID or completed YouTube result."
        )

    while time.monotonic() < deadline:
        response = session.get(
            API_ROOT + "/api/uploadposts/status",
            headers=headers,
            params={"request_id": request_id},
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise PublishBlocked("Upload-Post returned an invalid upload-status response.")
        state = str(payload.get("status") or "").lower()
        result = _youtube_result(payload)
        platform_state = str((result or {}).get("status") or "").lower()
        if state == "completed":
            if not result or result.get("success") is not True:
                raise PublishBlocked("Upload-Post completed without a successful YouTube result.")
            return payload
        if state in {"failed", "error"} or platform_state in {"failed", "error"}:
            raise PublishBlocked("Upload-Post reported a failed YouTube upload; automatic retry is blocked.")
        time.sleep(POLL_SECONDS)

    raise PublishBlocked(
        "Upload-Post did not confirm completion before the polling deadline; inspect YouTube before retrying."
    )


def _record_unknown(
    *,
    attempt_path: Path,
    receipt_path: Path,
    attempt: dict[str, Any],
    run_id: str,
    production_date: str,
    slot_id: str,
    title: str,
    channel_id: str,
    sha256: str,
    size_bytes: int,
    error: Exception,
) -> None:
    completed_at = datetime.now(timezone.utc).isoformat()
    message = re.sub(r"\s+", " ", str(error))[:500]
    receipt = {
        "schema_version": 1,
        "status": "outcome_unknown",
        "provider": "upload_post",
        "run_id": str(run_id),
        "production_date": production_date,
        "slot_id": slot_id,
        "title": title,
        "youtube_channel_id": channel_id,
        "privacy_status": "private",
        "sha256": sha256,
        "size_bytes": size_bytes,
        "created_at_utc": completed_at,
        "error": message,
        "retry_allowed": False,
    }
    _write_json(receipt_path, receipt)
    attempt.update({"status": "outcome_unknown", "completed_at_utc": completed_at})
    _write_json(attempt_path, attempt)
    _git_commit(
        [
            str(attempt_path.relative_to(ROOT)),
            str(receipt_path.relative_to(ROOT)),
        ],
        f"Record uncertain Upload-Post private preview outcome {production_date}-{slot_id}",
    )


def upload_private_preview(
    output_dir: str | Path,
    plan_path: str | Path,
    *,
    run_id: str,
    expected_slot_id: str,
    production_date: str | None = None,
) -> dict[str, Any]:
    if os.environ.get("GITHUB_REF_NAME") != "main":
        raise PublishBlocked("Scheduled private previews must execute from main.")
    if os.environ.get("YOUTUBE_PRIVACY_STATUS", "").strip().lower() != "private":
        raise PublishBlocked("YOUTUBE_PRIVACY_STATUS must be explicitly set to private.")
    if os.environ.get("PUBLISH_ENABLED", "false").strip().lower() == "true":
        raise PublishBlocked("Generic publishing adapters must remain disabled for this private-preview route.")

    api_key = os.environ.get("UPLOAD_POST_API_KEY", "").strip()
    if not api_key:
        raise PublishBlocked("UPLOAD_POST_API_KEY is not configured; no upload was attempted.")
    expected_channel = os.environ.get("YOUTUBE_EXPECTED_CHANNEL_ID", "").strip()
    if not expected_channel:
        raise PublishBlocked("YOUTUBE_EXPECTED_CHANNEL_ID is not configured.")
    user = os.environ.get("UPLOAD_POST_USER", DEFAULT_UPLOAD_POST_USER).strip()
    if user != DEFAULT_UPLOAD_POST_USER:
        raise PublishBlocked("The Upload-Post profile differs from the verified Violin Prince profile.")

    manifest, provenance, plan, video, audit = validate_daily_bundle(
        output_dir,
        plan_path,
        run_id=run_id,
        expected_slot_id=expected_slot_id,
        production_date=production_date,
        expected_privacy_status="private",
    )
    title = str(plan["publish_metadata"]["title"]).strip()
    description = str(plan["publish_metadata"]["description"]).strip()
    tags = plan["publish_metadata"].get("tags") or []
    if not title or not description or not isinstance(tags, list) or len(tags) < 3:
        raise PublishBlocked("The validated YouTube title, description or tags are incomplete.")

    slot_date = str(plan.get("production_date") or "")
    identity = _identity(slot_date, expected_slot_id)
    attempt_dir = ROOT / ".autopilot/private-preview-attempts"
    receipt_dir = ROOT / ".autopilot/private-preview-receipts"
    attempt_path = attempt_dir / f"{identity}.json"
    receipt_path = receipt_dir / f"{identity}.json"

    if receipt_path.is_file():
        receipt = _read_json(receipt_path, "Existing private-preview receipt")
        if receipt.get("status") == "uploaded_private" and receipt.get("sha256") == audit["sha256"]:
            _summary(
                "## Private preview already uploaded\n\n"
                f"- **Title:** {title}\n"
                f"- **Slot:** {expected_slot_id}\n"
                "- **Visibility:** PRIVATE\n"
                "- This date/slot will not be uploaded again."
            )
            return receipt
        raise PublishBlocked("An existing private-preview receipt conflicts with this production asset.")
    if attempt_path.is_file():
        raise PublishBlocked(
            "A durable attempt already exists for this production date and slot without a matching success receipt. "
            "Inspect YouTube Studio manually; automatic retries are blocked."
        )

    headers = {"Authorization": "Apikey " + api_key}
    session = requests.Session()
    try:
        duplicate_audit = _scan_existing_titles(session, headers, user)
    except requests.RequestException as exc:
        raise PublishBlocked("Upload-Post could not complete the YouTube duplicate audit: " + str(exc)[:250]) from exc
    if _normalise_title(title) in duplicate_audit.pop("_normalised_titles"):
        raise PublishBlocked("A video with this exact title already exists on the connected YouTube channel.")

    request_id = "violin-prince-" + identity
    attempt = {
        "schema_version": 1,
        "status": "attempting",
        "provider": "upload_post",
        "run_id": str(run_id),
        "production_date": slot_date,
        "slot_id": expected_slot_id,
        "production_identity": str(manifest.get("production_identity") or ""),
        "title": title,
        "youtube_channel_id": expected_channel,
        "upload_post_user": user,
        "privacy_status": "private",
        "sha256": audit["sha256"],
        "size_bytes": audit["size_bytes"],
        "duplicate_check": duplicate_audit,
        "request_id": request_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "note": "Committed before the Upload-Post request; uncertain outcomes are never retried automatically.",
    }
    _write_json(attempt_path, attempt)
    _git_commit(
        [str(attempt_path.relative_to(ROOT))],
        f"Record Upload-Post private preview attempt {identity}",
    )

    form = [
        ("user", user),
        ("platform[]", "youtube"),
        ("title", title),
        ("description", description),
        ("categoryId", str(plan["publish_metadata"].get("category_id") or "10")),
        ("privacyStatus", "private"),
        ("defaultLanguage", str(plan["publish_metadata"].get("default_language") or "en")),
        ("defaultAudioLanguage", "en"),
        ("selfDeclaredMadeForKids", "false"),
        ("containsSyntheticMedia", "true"),
        ("youtube_notify_subscribers", "false"),
        ("async_upload", "true"),
        ("request_id", request_id),
        ("external_id", request_id),
    ]
    form.extend(("tags[]", str(tag)) for tag in tags)
    request_headers = {**headers, "Idempotency-Key": request_id}

    try:
        with video.open("rb") as stream:
            response = session.post(
                API_ROOT + "/api/upload",
                headers=request_headers,
                data=form,
                files={"video": (video.name, stream, "video/mp4")},
                timeout=(30, 300),
            )
        if response.status_code not in (200, 202):
            raise PublishBlocked(
                f"Upload-Post rejected the private request (HTTP {response.status_code}); automatic retry is blocked."
            )
        initial_payload = response.json()
        if not isinstance(initial_payload, dict) or initial_payload.get("success") is not True:
            raise PublishBlocked("Upload-Post did not accept the private YouTube upload.")
        returned_request_id = str(initial_payload.get("request_id") or "")
        final_payload = _poll_upload(session, request_headers, returned_request_id, initial_payload)
        youtube_result = _youtube_result(final_payload)
        if not youtube_result or youtube_result.get("success") is not True:
            raise PublishBlocked("Upload-Post did not return a successful YouTube upload result.")
        video_id = _extract_video_id(youtube_result)

        details_response = session.get(
            API_ROOT + "/api/uploadposts/youtube/videos",
            headers=request_headers,
            params={"user": user, "ids": video_id, "parts": "snippet,status"},
            timeout=45,
        )
        details_response.raise_for_status()
        details_payload = details_response.json()
        items = details_payload.get("items") or []
        item = next(
            (entry for entry in items if isinstance(entry, dict) and entry.get("id") == video_id),
            None,
        )
        if not item:
            raise PublishBlocked("Upload-Post reported success but YouTube details are not yet available.")
        snippet = item.get("snippet") or {}
        actual_privacy = str((item.get("status") or {}).get("privacyStatus") or "").lower()
        actual_title = str(snippet.get("title") or "")
        actual_channel = str(snippet.get("channelId") or "")
        if actual_privacy != "private" or actual_title != title or actual_channel != expected_channel:
            raise PublishBlocked(
                "YouTube details did not confirm the exact title, expected channel and PRIVATE visibility."
            )
    except Exception as exc:
        try:
            _record_unknown(
                attempt_path=attempt_path,
                receipt_path=receipt_path,
                attempt=attempt,
                run_id=run_id,
                production_date=slot_date,
                slot_id=expected_slot_id,
                title=title,
                channel_id=expected_channel,
                sha256=audit["sha256"],
                size_bytes=audit["size_bytes"],
                error=exc,
            )
        except Exception as record_exc:
            raise PublishBlocked(
                "Upload outcome is uncertain and the durable no-retry receipt could not be saved: "
                + str(record_exc)[:300]
            ) from exc
        raise PublishBlocked(
            "Upload outcome is uncertain or verification failed. A durable no-retry receipt was saved; inspect YouTube Studio before any retry."
        ) from exc

    uploaded_at = datetime.now(timezone.utc).isoformat()
    receipt = {
        "schema_version": 1,
        "status": "uploaded_private",
        "provider": "upload_post",
        "run_id": str(run_id),
        "production_date": slot_date,
        "slot_id": expected_slot_id,
        "production_identity": str(manifest.get("production_identity") or ""),
        "youtube_channel_id": expected_channel,
        "upload_post_user": user,
        "title": title,
        "privacy_status": "private",
        "sha256": audit["sha256"],
        "size_bytes": audit["size_bytes"],
        "duplicate_check": duplicate_audit,
        "factual_provenance": {
            "independent_publisher_count": (provenance.get("factual_provenance") or {}).get("independent_publisher_count"),
            "source_count": len((provenance.get("factual_provenance") or {}).get("sources") or []),
        },
        "youtube_details_verified": True,
        "uploaded_at_utc": uploaded_at,
    }
    _write_json(receipt_path, receipt)
    attempt.update({"status": "uploaded_private", "completed_at_utc": uploaded_at})
    _write_json(attempt_path, attempt)
    _git_commit(
        [
            str(attempt_path.relative_to(ROOT)),
            str(receipt_path.relative_to(ROOT)),
        ],
        f"Save confirmed Upload-Post private preview receipt {identity}",
    )
    _summary(
        "## Violin Prince private preview uploaded\n\n"
        f"- **Title:** {title}\n"
        f"- **Slot:** {expected_slot_id}\n"
        "- **Upload route:** Upload-Post\n"
        "- **Channel verification:** passed\n"
        "- **YouTube visibility:** PRIVATE\n"
        "- **Public publishing:** disabled\n"
    )
    print(
        "UPLOAD_POST_YOUTUBE_STATUS=completed\n"
        "YOUTUBE_CHANNEL_VERIFICATION=passed\n"
        "YOUTUBE_VISIBILITY_CONFIRMED=private"
    )
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument("--slot-id", required=True)
    parser.add_argument("--production-date", default="")
    args = parser.parse_args()
    try:
        if not re.fullmatch(r"\d{6,20}", str(args.run_id)):
            raise PublishBlocked("A numeric GitHub Actions run ID is required.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(args.slot_id)):
            raise PublishBlocked("A valid daily slot ID is required.")
        upload_private_preview(
            args.output_dir,
            args.plan,
            run_id=str(args.run_id),
            expected_slot_id=str(args.slot_id),
            production_date=args.production_date or None,
        )
        return 0
    except (PublishBlocked, OSError, ValueError, requests.RequestException, subprocess.CalledProcessError) as exc:
        message = " ".join(str(exc).split())
        print("PRIVATE_PREVIEW_BLOCKED=" + message[:1000], file=sys.stderr)
        _summary("## Private YouTube preview upload blocked\n\n" + message[:1000])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
