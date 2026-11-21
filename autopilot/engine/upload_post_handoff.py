#!/usr/bin/env python3
"""Validated, duplicate-safe handoff from a GitHub Release to Upload-Post.

This module never unlocks video production. It only queues an MP4 after the
existing renderer has produced a passing manifest and SHA-256 provenance.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

UPLOAD_URL = "https://api.upload-post.com/api/upload"
STATUS_URL = "https://api.upload-post.com/api/uploadposts/status"
DEFAULT_PROFILE = "default"
MAX_TITLE_LENGTH = 95


class UploadPostHandoffError(RuntimeError):
    """Raised when a validated release cannot be queued safely."""


def _read_json(path: str | Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise UploadPostHandoffError(f"{description} is missing or invalid JSON.") from exc
    if not isinstance(value, dict):
        raise UploadPostHandoffError(f"{description} must be a JSON object.")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_validated_bundle(
    video_path: str | Path,
    plan_path: str | Path,
    manifest_path: str | Path,
    provenance_path: str | Path,
) -> dict[str, Any]:
    """Validate the rendered MP4, publisher manifest and provenance before upload."""
    video = Path(video_path)
    if not video.is_file() or video.stat().st_size < 4096:
        raise UploadPostHandoffError("Final MP4 is missing or unexpectedly small.")

    plan = _read_json(plan_path, "Daily production plan")
    manifest = _read_json(manifest_path, "Publisher manifest")
    provenance = _read_json(provenance_path, "Asset provenance")

    production_date = str(plan.get("production_date") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", production_date):
        raise UploadPostHandoffError("The daily plan must include production_date in YYYY-MM-DD format.")

    title = re.sub(r"\s+", " ", str(plan.get("title") or "")).strip()
    if not title:
        raise UploadPostHandoffError("The daily plan has no YouTube title.")
    if len(title) > MAX_TITLE_LENGTH:
        raise UploadPostHandoffError(
            f"YouTube title is {len(title)} characters; the handoff limit is {MAX_TITLE_LENGTH}."
        )

    if manifest.get("status") != "rendered":
        raise UploadPostHandoffError("Publisher manifest status is not rendered.")
    if manifest.get("publish_ready") is not True:
        raise UploadPostHandoffError("Publisher manifest is not marked publish_ready.")
    preflight = manifest.get("publisher_preflight") or {}
    if preflight.get("status") != "ready" or preflight.get("blockers"):
        raise UploadPostHandoffError("Publisher preflight is not ready or contains blockers.")

    factual = provenance.get("factual_provenance") or {}
    if factual.get("status") != "passed" or int(factual.get("independent_publisher_count") or 0) < 2:
        raise UploadPostHandoffError("Factual provenance has not passed independent-source validation.")

    final_record = (provenance.get("assets") or {}).get("final_video") or {}
    actual_sha = _sha256(video)
    if final_record.get("sha256") != actual_sha:
        raise UploadPostHandoffError("Final MP4 SHA-256 does not match the provenance record.")

    duration = float(manifest.get("duration_seconds") or 0)
    if not 20 <= duration <= 25:
        raise UploadPostHandoffError("Final MP4 duration is outside the 20–25 second Shorts contract.")

    return {
        "video_path": video,
        "plan": plan,
        "manifest": manifest,
        "provenance": provenance,
        "production_date": production_date,
        "title": title,
        "sha256": actual_sha,
    }


def build_release_url(repository: str, run_id: str) -> str:
    """Build the public release-asset URL used by Upload-Post to fetch the MP4."""
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", str(repository or "")):
        raise UploadPostHandoffError("GITHUB_REPOSITORY is missing or malformed.")
    if not re.fullmatch(r"\d+", str(run_id or "")):
        raise UploadPostHandoffError("GITHUB_RUN_ID must be numeric.")
    tag = f"violin-prince-short-{run_id}"
    return f"https://github.com/{repository}/releases/download/{tag}/violin-prince-short.mp4"


def build_description(plan: dict[str, Any]) -> str:
    """Build a clean YouTube description from the already-approved daily plan."""
    parts: list[str] = []
    hook = str(plan.get("hook") or "").strip()
    description = str(plan.get("description") or "").strip()
    if hook:
        parts.append(hook)
    if description and description != hook:
        parts.append(description)

    hashtags = plan.get("hashtags") or []
    if isinstance(hashtags, list):
        clean_tags = []
        for value in hashtags:
            tag = re.sub(r"\s+", "", str(value or "").strip())
            if tag:
                clean_tags.append(tag if tag.startswith("#") else "#" + tag)
        if clean_tags:
            parts.append(" ".join(clean_tags[:12]))

    sources = plan.get("sources") or []
    source_lines = []
    if isinstance(sources, list):
        for source in sources[:8]:
            if isinstance(source, dict) and source.get("url"):
                label = str(source.get("title") or source.get("publisher_domain") or "Source").strip()
                source_lines.append(f"{label}: {source['url']}")
    if source_lines:
        parts.append("Research sources:\n" + "\n".join(source_lines))

    return "\n\n".join(parts)[:4900]


def build_upload_fields(bundle: dict[str, Any], profile: str, release_url: str) -> tuple[list[tuple[str, str]], str, str]:
    """Return multipart fields plus stable request and idempotency identifiers."""
    profile = str(profile or DEFAULT_PROFILE).strip()
    if not profile:
        raise UploadPostHandoffError("Upload-Post profile name is empty.")

    date_key = bundle["production_date"]
    slot_id = str(bundle["plan"].get("slot_id") or "legacy-single").strip()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slot_id):
        raise UploadPostHandoffError("The production plan slot_id is malformed.")
    production_identity = f"{date_key}:{slot_id}"
    request_id = uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"violin-prince:{profile}:youtube:{production_identity}",
    ).hex
    external_id = f"violin-prince-youtube-{production_identity}"
    fields = [
        ("user", profile),
        ("platform[]", "youtube"),
        ("video", release_url),
        ("title", bundle["title"]),
        ("description", build_description(bundle["plan"])),
        ("categoryId", "10"),
        ("privacyStatus", "public"),
        ("containsSyntheticMedia", "true"),
        ("defaultLanguage", "en"),
        ("add_to_queue", "true"),
        ("request_id", request_id),
        ("external_id", external_id),
    ]
    return fields, request_id, external_id


def _response_json(response: Any, stage: str) -> dict[str, Any]:
    try:
        payload = response.json()
    except (ValueError, TypeError) as exc:
        raise UploadPostHandoffError(f"Upload-Post returned non-JSON content during {stage}.") from exc
    if not isinstance(payload, dict):
        raise UploadPostHandoffError(f"Upload-Post returned an unexpected response during {stage}.")
    return payload


def _api_message(payload: dict[str, Any]) -> str:
    message = payload.get("message") or payload.get("error") or payload.get("detail") or "Unknown Upload-Post error."
    return re.sub(r"\s+", " ", str(message))[:500]


def _poll_for_job(
    session: requests.Session,
    api_key: str,
    request_id: str,
    *,
    timeout_seconds: int = 180,
    poll_interval: int = 5,
) -> dict[str, Any]:
    """Resolve an automatically asynchronous upload to its queued job_id."""
    deadline = time.monotonic() + timeout_seconds
    headers = {"Authorization": f"Apikey {api_key}"}
    last_payload: dict[str, Any] = {}

    while time.monotonic() < deadline:
        response = session.get(
            STATUS_URL,
            headers=headers,
            params={"request_id": request_id},
            timeout=(15, 30),
        )
        response.raise_for_status()
        payload = _response_json(response, "upload status")
        last_payload = payload
        job_id = payload.get("job_id")
        if job_id:
            return payload
        status = str(payload.get("status") or "").lower()
        if status in {"failed", "not_found"}:
            raise UploadPostHandoffError("Upload-Post processing failed: " + _api_message(payload))
        time.sleep(poll_interval)

    raise UploadPostHandoffError(
        "Upload-Post did not return a queue job ID before timeout. "
        "Check the Upload-Post schedule before retrying; the idempotency key prevents duplicate submissions. "
        f"Last status: {str(last_payload.get('status') or 'unknown')}."
    )


def submit_to_upload_post(
    bundle: dict[str, Any],
    *,
    api_key: str,
    profile: str = DEFAULT_PROFILE,
    release_url: str,
    session: requests.Session | None = None,
    poll_timeout_seconds: int = 180,
) -> dict[str, Any]:
    """Send a passing release MP4 to the next configured Upload-Post queue slot."""
    api_key = str(api_key or "").strip()
    if not api_key:
        return {
            "status": "blocked_missing_secret",
            "message": "UPLOAD_POST_API_KEY is not configured; video was not queued.",
        }

    client = session or requests.Session()
    fields, request_id, external_id = build_upload_fields(bundle, profile, release_url)
    slot_id = str(bundle["plan"].get("slot_id") or "legacy-single").strip()
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", slot_id):
        raise UploadPostHandoffError("The production plan slot_id is malformed.")
    idempotency_key = f"violin-prince-youtube-{bundle['production_date']}-{slot_id}-{profile}"
    headers = {
        "Authorization": f"Apikey {api_key}",
        "Idempotency-Key": idempotency_key,
    }

    response = client.post(
        UPLOAD_URL,
        headers=headers,
        data=fields,
        timeout=(20, 90),
    )
    response.raise_for_status()
    payload = _response_json(response, "video submission")
    if payload.get("success") is False:
        raise UploadPostHandoffError("Upload-Post rejected the video: " + _api_message(payload))

    job_id = payload.get("job_id")
    status_payload = payload
    if not job_id:
        returned_request_id = str(payload.get("request_id") or request_id)
        status_payload = _poll_for_job(
            client,
            api_key,
            returned_request_id,
            timeout_seconds=poll_timeout_seconds,
        )
        job_id = status_payload.get("job_id")

    if not job_id:
        raise UploadPostHandoffError("Upload-Post did not confirm a scheduled queue job.")

    scheduled_date = (
        status_payload.get("scheduled_date")
        or status_payload.get("queue_slot")
        or payload.get("scheduled_date")
        or payload.get("queue_slot")
        or ""
    )
    return {
        "status": "queued",
        "profile": profile,
        "platform": "youtube",
        "job_id": str(job_id),
        "request_id": str(payload.get("request_id") or request_id),
        "external_id": external_id,
        "scheduled_date": str(scheduled_date),
        "idempotency_key": idempotency_key,
        "video_url": release_url,
    }


def _write_report(path: str | Path, result: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _write_summary(result: dict[str, Any]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY", "").strip()
    if not summary_path:
        return
    status = str(result.get("status") or "unknown").upper()
    lines = ["## Upload-Post YouTube handoff", "", f"**Status:** {status}"]
    for key, label in (
        ("job_id", "Queue job"),
        ("scheduled_date", "Scheduled time"),
        ("message", "Details"),
    ):
        value = result.get(key)
        if value:
            lines.append(f"**{label}:** {value}")
    with open(summary_path, "a", encoding="utf-8") as handle:
        handle.write("\n".join(lines) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Queue a verified Violin Prince Short with Upload-Post.")
    parser.add_argument("--video", default="work/output/violin-prince-short.mp4")
    parser.add_argument("--plan", default=".autopilot/daily-production-plan.json")
    parser.add_argument("--manifest", default="work/output/publish-manifest.json")
    parser.add_argument("--provenance", default="work/output/asset-provenance.json")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument("--output", default="work/output/upload-post-result.json")
    args = parser.parse_args(argv)

    if not os.environ.get("UPLOAD_POST_API_KEY", "").strip():
        result = {
            "status": "blocked_missing_secret",
            "message": "UPLOAD_POST_API_KEY is not configured; video was not queued.",
        }
        _write_report(args.output, result)
        _write_summary(result)
        print("::warning::Upload-Post handoff skipped: add the UPLOAD_POST_API_KEY repository secret.")
        return 0

    try:
        bundle = load_validated_bundle(args.video, args.plan, args.manifest, args.provenance)
        release_url = build_release_url(args.repository, args.run_id)
        result = submit_to_upload_post(
            bundle,
            api_key=os.environ["UPLOAD_POST_API_KEY"],
            profile=os.environ.get("UPLOAD_POST_PROFILE", DEFAULT_PROFILE),
            release_url=release_url,
        )
        _write_report(args.output, result)
        _write_summary(result)
        print("Upload-Post queued the validated YouTube Short.")
        print("Queue job ID: " + result["job_id"])
        if result.get("scheduled_date"):
            print("Scheduled time: " + result["scheduled_date"])
        return 0
    except (UploadPostHandoffError, requests.RequestException, OSError, ValueError) as exc:
        print("::error::Upload-Post handoff failed: " + str(exc)[:700], file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
