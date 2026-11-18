#!/usr/bin/env python3
"""Queue a validated Violin Prince Short in the owner's Upload-Post YouTube queue.

This module deliberately does not unlock video production. It only accepts a
rendered, publish-ready MP4 plus its validated manifest. API credentials are
read from the runner environment and are never printed.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path
from typing import Any

import requests

API_BASE = "https://api.upload-post.com/api"
QUEUE_SETTINGS_PATH = "/uploadposts/queue/settings"
UPLOAD_PATH = "/upload"
STATUS_PATH = "/uploadposts/status"
DEFAULT_PROFILE = "default"
EXPECTED_TIMEZONE = "Asia/Kolkata"
EXPECTED_SLOT = {"hour": 19, "minute": 0}


class UploadPostError(RuntimeError):
    """Raised when Upload-Post rejects or cannot confirm a queue submission."""


def _load_json(path: str | Path) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UploadPostError(f"Cannot read JSON file: {path}") from exc
    if not isinstance(value, dict):
        raise UploadPostError(f"Expected a JSON object in {path}.")
    return value


def _validate_manifest(manifest: dict[str, Any]) -> tuple[str, str, str]:
    if manifest.get("status") != "rendered":
        raise UploadPostError("Publishing is blocked: manifest status must be rendered.")
    if manifest.get("publish_ready") is not True:
        raise UploadPostError("Publishing is blocked: publish_ready is not true.")
    preflight = manifest.get("publisher_preflight")
    if not isinstance(preflight, dict) or preflight.get("status") != "ready":
        raise UploadPostError("Publishing is blocked: publisher preflight is not ready.")
    if preflight.get("blockers"):
        raise UploadPostError("Publishing is blocked: publisher preflight still has blockers.")

    title = str(manifest.get("title") or "").strip()
    description = str(manifest.get("description") or "").strip()
    run_id = str(manifest.get("run_id") or "").strip()
    if not title:
        raise UploadPostError("Publishing is blocked: manifest title is missing.")
    if not run_id or not re.fullmatch(r"[A-Za-z0-9._-]{1,100}", run_id):
        raise UploadPostError("Publishing is blocked: manifest run_id is missing or invalid.")
    return title[:100], description[:5000], run_id


def _headers(api_key: str, run_id: str) -> dict[str, str]:
    if not api_key or not api_key.strip():
        raise UploadPostError(
            "Missing UPLOAD_POST_API_KEY. Add it as a repository Actions secret; "
            "do not put the key in source code or workflow files."
        )
    return {
        "Authorization": f"Apikey {api_key.strip()}",
        "Idempotency-Key": f"violin-prince-run-{run_id}",
        "Accept": "application/json",
    }


def verify_queue_settings(
    session: requests.Session,
    headers: dict[str, str],
    profile: str,
    timeout: int = 30,
) -> dict[str, Any]:
    response = session.get(
        API_BASE + QUEUE_SETTINGS_PATH,
        params={"profile_username": profile},
        headers=headers,
        timeout=timeout,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict) or payload.get("success") is not True:
        raise UploadPostError("Upload-Post did not confirm the queue settings.")
    settings = payload.get("queue_settings")
    if not isinstance(settings, dict):
        raise UploadPostError("Upload-Post returned no queue settings for the profile.")

    timezone = settings.get("timezone")
    slots = settings.get("slots") or []
    weekdays = settings.get("days_of_week") or []
    max_per_slot = settings.get("max_posts_per_slot")
    if timezone != EXPECTED_TIMEZONE:
        raise UploadPostError(
            f"Queue timezone mismatch: expected {EXPECTED_TIMEZONE}, found {timezone!r}."
        )
    if EXPECTED_SLOT not in slots:
        raise UploadPostError("The daily 7:00 PM Asia/Kolkata queue slot is not configured.")
    if sorted(set(weekdays)) != list(range(7)):
        raise UploadPostError("The Upload-Post queue is not enabled for all seven days.")
    if max_per_slot != 1:
        raise UploadPostError("The Upload-Post queue must allow only one post per slot.")
    return settings


def _poll_upload(
    session: requests.Session,
    headers: dict[str, str],
    request_id: str,
    *,
    poll_interval: float,
    max_wait: float,
) -> dict[str, Any]:
    deadline = time.monotonic() + max_wait
    last_status = ""
    while time.monotonic() < deadline:
        response = session.get(
            API_BASE + STATUS_PATH,
            params={"request_id": request_id},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise UploadPostError("Upload-Post returned an invalid status response.")
        last_status = str(payload.get("status") or "").lower()
        if last_status == "failed" or last_status == "not_found":
            message = str(payload.get("message") or "Upload-Post upload failed.")
            raise UploadPostError(message[:500])
        if last_status == "completed":
            results = payload.get("results") or []
            youtube_results = [
                item for item in results
                if isinstance(item, dict) and str(item.get("platform") or "").lower() == "youtube"
            ]
            if youtube_results and all(item.get("success") is True for item in youtube_results):
                return payload
            raise UploadPostError("Upload-Post did not confirm successful YouTube queueing.")
        time.sleep(poll_interval)
    raise UploadPostError(
        f"Timed out waiting for Upload-Post request {request_id}; last status: {last_status or 'unknown'}."
    )


def queue_video(
    video_path: str | Path,
    manifest_path: str | Path,
    *,
    api_key: str | None = None,
    profile: str | None = None,
    session: requests.Session | None = None,
    poll_interval: float = 5.0,
    max_wait: float = 600.0,
) -> dict[str, Any]:
    """Submit one validated MP4 to the profile's next daily YouTube queue slot."""
    video = Path(video_path)
    manifest = _load_json(manifest_path)
    title, description, run_id = _validate_manifest(manifest)
    if not video.is_file() or video.stat().st_size < 4096:
        raise UploadPostError("Final MP4 is missing or unexpectedly small.")
    if video.suffix.lower() != ".mp4":
        raise UploadPostError("The publishing handoff accepts MP4 files only.")

    secret = api_key if api_key is not None else os.environ.get("UPLOAD_POST_API_KEY", "")
    profile_name = (profile or os.environ.get("UPLOAD_POST_PROFILE") or DEFAULT_PROFILE).strip()
    if not profile_name:
        raise UploadPostError("Upload-Post profile name is empty.")
    headers = _headers(secret, run_id)
    client = session or requests.Session()

    queue_settings = verify_queue_settings(client, headers, profile_name)
    request_id = f"violin-prince-{run_id}"
    fields = {
        "user": profile_name,
        "platform[]": "youtube",
        "title": title,
        "description": description,
        "add_to_queue": "true",
        "async_upload": "true",
        "request_id": request_id,
        "categoryId": "10",
        "privacyStatus": "public",
        "selfDeclaredMadeForKids": "false",
        "containsSyntheticMedia": "true",
    }

    with video.open("rb") as handle:
        response = client.post(
            API_BASE + UPLOAD_PATH,
            headers=headers,
            data=fields,
            files={"video": (video.name, handle, "video/mp4")},
            timeout=(30, 600),
        )
    response.raise_for_status()
    submitted = response.json()
    if not isinstance(submitted, dict) or submitted.get("success") is not True:
        raise UploadPostError("Upload-Post did not confirm the YouTube upload request.")

    job_id = submitted.get("job_id")
    scheduled_date = submitted.get("scheduled_date") or submitted.get("queue_slot")
    request_id = str(submitted.get("request_id") or request_id)
    status_payload = submitted
    if not job_id:
        status_payload = _poll_upload(
            client, headers, request_id,
            poll_interval=poll_interval,
            max_wait=max_wait,
        )
        job_id = status_payload.get("job_id")
        scheduled_date = (
            status_payload.get("scheduled_date")
            or status_payload.get("queue_slot")
            or scheduled_date
        )

    if not job_id and not scheduled_date:
        raise UploadPostError(
            "Upload-Post accepted the upload but returned no queue job or scheduled slot."
        )

    return {
        "success": True,
        "profile": profile_name,
        "platform": "youtube",
        "run_id": run_id,
        "request_id": request_id,
        "job_id": str(job_id) if job_id else None,
        "scheduled_date": scheduled_date,
        "queue_timezone": queue_settings["timezone"],
        "queue_slot": EXPECTED_SLOT,
        "status": str(status_payload.get("status") or "queued"),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Queue a publish-ready Violin Prince MP4 in Upload-Post."
    )
    parser.add_argument("--video", required=True, help="Path to the final MP4.")
    parser.add_argument("--manifest", required=True, help="Path to publish-manifest.json.")
    parser.add_argument(
        "--receipt", default="work/output/upload-post-queue-receipt.json",
        help="Where to write the queue confirmation JSON.",
    )
    args = parser.parse_args()
    try:
        receipt = queue_video(args.video, args.manifest)
        target = Path(args.receipt)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(
            "UPLOAD_POST_QUEUE_CONFIRMED "
            + json.dumps(
                {key: value for key, value in receipt.items() if key not in ("request_id",)},
                ensure_ascii=False,
            ),
            flush=True,
        )
        return 0
    except (UploadPostError, requests.RequestException, ValueError, OSError) as exc:
        print("Upload-Post queue handoff failed: " + str(exc)[:800], file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
