#!/usr/bin/env python3
"""Publish one approved Violin Prince daily Short publicly through Upload-Post.

Public publishing is gated twice: this script verifies the creator's committed
public-YouTube approval, and the bundle validator requires public privacy in
both the creative plan and publisher manifest. It checks the connected channel
for duplicate titles and commits a durable no-blind-retry marker before upload.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests

from publish_daily_short import (
    PublishBlocked,
    _git_commit,
    _read_json,
    _summary,
    validate_daily_bundle,
)
from upload_private_preview_uploadpost import (
    API_ROOT,
    DEFAULT_UPLOAD_POST_USER,
    _extract_video_id,
    _normalise_title,
    _poll_upload,
    _scan_existing_titles,
    _write_json,
    _youtube_result,
)

ROOT = Path(__file__).resolve().parents[2]


def _require_public_creator_approval() -> dict[str, Any]:
    approval_path = ROOT / "autopilot" / "engine" / "illustration-approval.json"
    approval = _read_json(approval_path, "Creator public YouTube approval")
    public_approval = approval.get("creator_publication_approval")
    if not (
        approval.get("status") == "approved_for_publication"
        and approval.get("scope") == "public_youtube"
        and approval.get("publishing_enabled") is True
        and isinstance(public_approval, dict)
        and public_approval.get("approved") is True
        and public_approval.get("platform") == "youtube"
        and public_approval.get("privacy_status") == "public"
        and public_approval.get("no_private_preview_required") is True
        and str(public_approval.get("approval_statement") or "").strip()
    ):
        raise PublishBlocked(
            "Public YouTube upload blocked: the committed creator approval does not explicitly authorize public publishing."
        )
    return public_approval


def _identity(production_date: str, slot_id: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", f"{production_date}-{slot_id}").strip("-")
    if not value:
        raise PublishBlocked("A stable production-date/slot identity is required.")
    return value


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
        "privacy_status": "public",
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
        f"Record uncertain public YouTube upload outcome {production_date}-{slot_id}",
    )


def upload_public_short(
    output_dir: str | Path,
    plan_path: str | Path,
    *,
    run_id: str,
    expected_slot_id: str,
    production_date: str | None = None,
) -> dict[str, Any]:
    if os.environ.get("GITHUB_REF_NAME") != "main":
        raise PublishBlocked("Scheduled public uploads must execute from main.")
    if os.environ.get("YOUTUBE_PRIVACY_STATUS", "").strip().lower() != "public":
        raise PublishBlocked("YOUTUBE_PRIVACY_STATUS must be explicitly set to public.")
    if os.environ.get("PUBLISH_ENABLED", "false").strip().lower() == "true":
        raise PublishBlocked("Generic publishing adapters must remain disabled for this YouTube-only route.")

    from animation_production_gate import (
        AnimationProductionGateError,
        require_approved_animation_production,
    )
    try:
        require_approved_animation_production()
    except AnimationProductionGateError as exc:
        raise PublishBlocked(str(exc)) from exc

    _require_public_creator_approval()
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
        expected_privacy_status="public",
    )
    title = str(plan["publish_metadata"]["title"]).strip()
    description = str(plan["publish_metadata"]["description"]).strip()
    tags = plan["publish_metadata"].get("tags") or []
    if not title or not description or not isinstance(tags, list) or len(tags) < 3:
        raise PublishBlocked("The validated YouTube title, description or tags are incomplete.")

    slot_date = str(plan.get("production_date") or "")
    identity = _identity(slot_date, expected_slot_id)
    attempt_dir = ROOT / ".autopilot" / "public-youtube-attempts"
    receipt_dir = ROOT / ".autopilot" / "public-youtube-receipts"
    attempt_path = attempt_dir / f"{identity}.json"
    receipt_path = receipt_dir / f"{identity}.json"

    if receipt_path.is_file():
        receipt = _read_json(receipt_path, "Existing public YouTube receipt")
        if receipt.get("status") == "uploaded_public" and receipt.get("sha256") == audit["sha256"]:
            _summary(
                "## Public YouTube upload already confirmed\n\n"
                f"- **Title:** {title}\n"
                f"- **Slot:** {expected_slot_id}\n"
                "- **Visibility:** PUBLIC\n"
                "- This date/slot will not be uploaded again."
            )
            return receipt
        raise PublishBlocked("An existing public-upload receipt conflicts with this production asset.")
    if attempt_path.is_file():
        raise PublishBlocked(
            "A durable public-upload attempt already exists for this production date and slot without a matching success receipt. "
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

    request_id = "violin-prince-public-" + identity
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
        "privacy_status": "public",
        "sha256": audit["sha256"],
        "size_bytes": audit["size_bytes"],
        "duplicate_check": duplicate_audit,
        "request_id": request_id,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "note": "Committed before public upload; uncertain outcomes are never retried automatically.",
    }
    _write_json(attempt_path, attempt)
    _git_commit(
        [str(attempt_path.relative_to(ROOT))],
        f"Record public YouTube upload attempt {identity}",
    )

    form = [
        ("user", user),
        ("platform[]", "youtube"),
        ("title", title),
        ("description", description),
        ("categoryId", str(plan["publish_metadata"].get("category_id") or "10")),
        ("privacyStatus", "public"),
        ("defaultLanguage", str(plan["publish_metadata"].get("default_language") or "en")),
        ("defaultAudioLanguage", "en"),
        ("selfDeclaredMadeForKids", "false"),
        ("containsSyntheticMedia", "true"),
        ("youtube_notify_subscribers", "true"),
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
                f"Upload-Post rejected the public request (HTTP {response.status_code}); automatic retry is blocked."
            )
        initial_payload = response.json()
        if not isinstance(initial_payload, dict) or initial_payload.get("success") is not True:
            raise PublishBlocked("Upload-Post did not accept the public YouTube upload.")
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
        if actual_privacy != "public" or actual_title != title or actual_channel != expected_channel:
            raise PublishBlocked(
                "YouTube details did not confirm the exact title, expected channel and PUBLIC visibility."
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
                "Public upload outcome is uncertain and the durable no-retry receipt could not be saved: "
                + str(record_exc)[:300]
            ) from exc
        raise PublishBlocked(
            "Public upload outcome is uncertain or verification failed. A durable no-retry receipt was saved; inspect YouTube Studio before any retry."
        ) from exc

    uploaded_at = datetime.now(timezone.utc).isoformat()
    receipt = {
        "schema_version": 1,
        "status": "uploaded_public",
        "provider": "upload_post",
        "run_id": str(run_id),
        "production_date": slot_date,
        "slot_id": expected_slot_id,
        "production_identity": str(manifest.get("production_identity") or ""),
        "youtube_channel_id": expected_channel,
        "upload_post_user": user,
        "title": title,
        "privacy_status": "public",
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
    attempt.update({"status": "uploaded_public", "completed_at_utc": uploaded_at})
    _write_json(attempt_path, attempt)
    _git_commit(
        [
            str(attempt_path.relative_to(ROOT)),
            str(receipt_path.relative_to(ROOT)),
        ],
        f"Save confirmed public YouTube upload receipt {identity}",
    )
    _summary(
        "## Violin Prince Short uploaded publicly to YouTube\n\n"
        f"- **Title:** {title}\n"
        f"- **Slot:** {expected_slot_id}\n"
        "- **Upload route:** Upload-Post\n"
        "- **Channel verification:** passed\n"
        "- **YouTube visibility:** PUBLIC\n"
        "- **Subscriber notifications:** enabled\n"
    )
    print(
        "UPLOAD_POST_YOUTUBE_STATUS=completed\n"
        "YOUTUBE_CHANNEL_VERIFICATION=passed\n"
        "YOUTUBE_VISIBILITY_CONFIRMED=public"
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
        upload_public_short(
            args.output_dir,
            args.plan,
            run_id=str(args.run_id),
            expected_slot_id=str(args.slot_id),
            production_date=args.production_date or None,
        )
        return 0
    except (PublishBlocked, OSError, ValueError, requests.RequestException, subprocess.CalledProcessError) as exc:
        message = " ".join(str(exc).split())
        print("PUBLIC_YOUTUBE_UPLOAD_BLOCKED=" + message[:1000], file=sys.stderr)
        _summary("## Public YouTube upload blocked\n\n" + message[:1000])
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
