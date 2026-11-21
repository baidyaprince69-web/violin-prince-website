#!/usr/bin/env python3
"""Upload one fully validated Violin Prince daily slot as a PRIVATE preview.

This route is intentionally separate from publish_daily_short.py. It refuses
public visibility, verifies the authenticated channel and duplicate titles,
and persists a durable no-retry attempt before contacting YouTube.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from publisher import youtube_upload
from publish_daily_short import (
    PublishBlocked,
    _git_commit,
    _read_json,
    _summary,
    validate_daily_bundle,
)
from youtube_channel_audit import (
    ChannelAuditError,
    DuplicateVideoFound,
    assert_title_absent,
)

ROOT = Path(__file__).resolve().parents[2]


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _identity(run_id: str, slot_id: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_-]+", "-", f"{run_id}-{slot_id}").strip("-")
    if not value:
        raise PublishBlocked("A stable GitHub run/slot identity is required.")
    return value


def upload_private_preview(
    output_dir: str | Path,
    plan_path: str | Path,
    *,
    run_id: str,
    expected_slot_id: str,
    production_date: str | None = None,
) -> dict[str, Any]:
    """Validate and upload one scheduled slot with YouTube privacy set to private."""
    if os.environ.get("GITHUB_REF_NAME") != "main":
        raise PublishBlocked("Scheduled private previews must execute from main.")
    if os.environ.get("YOUTUBE_PRIVACY_STATUS", "").strip().lower() != "private":
        raise PublishBlocked("YOUTUBE_PRIVACY_STATUS must be explicitly set to private.")

    expected_channel = os.environ.get("YOUTUBE_EXPECTED_CHANNEL_ID", "").strip()
    if not expected_channel:
        raise PublishBlocked("YOUTUBE_EXPECTED_CHANNEL_ID is not configured.")

    manifest, provenance, plan, video, audit = validate_daily_bundle(
        output_dir,
        plan_path,
        run_id=run_id,
        expected_slot_id=expected_slot_id,
        production_date=production_date,
        expected_privacy_status="private",
    )
    title = str(plan["publish_metadata"]["title"]).strip()
    identity = _identity(run_id, expected_slot_id)
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
                f"- **YouTube:** {receipt.get('youtube_video_url', '')}\n"
                "- **Visibility:** Private\n"
                "- This exact production run will not be uploaded again."
            )
            return receipt
        raise PublishBlocked("An existing private-preview receipt conflicts with this production asset.")

    if attempt_path.is_file():
        raise PublishBlocked(
            "A durable private-preview attempt already exists without a confirmed receipt. "
            "Inspect YouTube manually; automatic retries are blocked."
        )

    os.environ["YOUTUBE_EXPECTED_CHANNEL_ID"] = expected_channel
    try:
        duplicate_check = assert_title_absent(title)
    except DuplicateVideoFound as exc:
        matches = json.dumps(exc.matches[:5], ensure_ascii=False)
        raise PublishBlocked(
            "A video with this exact title already exists in channel uploads; private preview blocked: " + matches
        ) from exc
    except ChannelAuditError as exc:
        raise PublishBlocked(
            "YouTube channel/duplicate audit failed; private preview blocked: " + str(exc)
        ) from exc

    attempt = {
        "schema_version": 1,
        "status": "attempting",
        "run_id": str(run_id),
        "production_date": str(plan.get("production_date") or ""),
        "slot_id": expected_slot_id,
        "production_identity": str(manifest.get("production_identity") or ""),
        "title": title,
        "youtube_channel_id": expected_channel,
        "privacy_status": "private",
        "sha256": audit["sha256"],
        "size_bytes": audit["size_bytes"],
        "duplicate_check": duplicate_check,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Committed before the YouTube API request. If the upload outcome is uncertain, "
            "the exact run is blocked from automatic retry."
        ),
    }
    _write_json(attempt_path, attempt)
    _git_commit(
        [str(attempt_path.relative_to(ROOT))],
        f"Record private YouTube preview attempt {identity}",
    )

    os.environ["YOUTUBE_PRIVACY_STATUS"] = "private"
    try:
        upload = youtube_upload(video, plan)
        video_id = str(upload.get("id") or "").strip()
        video_url = str(upload.get("url") or "").strip()
        if upload.get("ok") is False or not video_id or not video_url:
            raise PublishBlocked("YouTube did not confirm the uploaded private video ID and URL.")
    except Exception as exc:
        receipt = {
            "schema_version": 1,
            "status": "outcome_unknown",
            "provider": "youtube_data_api",
            "run_id": str(run_id),
            "production_date": str(plan.get("production_date") or ""),
            "slot_id": expected_slot_id,
            "title": title,
            "youtube_channel_id": expected_channel,
            "privacy_status": "private",
            "sha256": audit["sha256"],
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "error": " ".join(str(exc).split())[:500],
            "retry_allowed": False,
        }
        _write_json(receipt_path, receipt)
        attempt.update({"status": "outcome_unknown", "completed_at_utc": receipt["created_at_utc"]})
        _write_json(attempt_path, attempt)
        _git_commit(
            [str(attempt_path.relative_to(ROOT)), str(receipt_path.relative_to(ROOT))],
            f"Record uncertain private YouTube preview outcome {identity}",
        )
        raise PublishBlocked(
            "The private YouTube upload outcome is uncertain. A durable no-retry receipt was saved; inspect the channel manually."
        ) from exc

    actual_privacy = str(upload.get("privacy_status") or "").strip().lower()
    if actual_privacy != "private":
        receipt = {
            "schema_version": 1,
            "status": "uploaded_visibility_mismatch",
            "provider": "youtube_data_api",
            "run_id": str(run_id),
            "production_date": str(plan.get("production_date") or ""),
            "slot_id": expected_slot_id,
            "youtube_video_id": video_id,
            "youtube_video_url": video_url,
            "youtube_channel_id": expected_channel,
            "title": title,
            "requested_privacy_status": "private",
            "returned_privacy_status": actual_privacy or "not returned",
            "sha256": audit["sha256"],
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "retry_allowed": False,
            "note": "YouTube returned an upload ID but did not confirm private visibility. Inspect this exact video; do not retry.",
        }
        _write_json(receipt_path, receipt)
        attempt.update({
            "status": "uploaded_visibility_mismatch",
            "youtube_video_id": video_id,
            "youtube_video_url": video_url,
            "returned_privacy_status": actual_privacy or "not returned",
        })
        _write_json(attempt_path, attempt)
        _git_commit(
            [str(attempt_path.relative_to(ROOT)), str(receipt_path.relative_to(ROOT))],
            f"Record private YouTube preview visibility mismatch {identity}",
        )
        raise PublishBlocked(
            "YouTube accepted the upload but did not confirm private visibility. "
            "A no-retry receipt was saved; inspect this exact video manually."
        )

    receipt = {
        "schema_version": 1,
        "status": "uploaded_private",
        "provider": "youtube_data_api",
        "run_id": str(run_id),
        "production_date": str(plan.get("production_date") or ""),
        "slot_id": expected_slot_id,
        "production_identity": str(manifest.get("production_identity") or ""),
        "youtube_video_id": video_id,
        "youtube_video_url": video_url,
        "youtube_channel_id": expected_channel,
        "title": title,
        "privacy_status": "private",
        "sha256": audit["sha256"],
        "size_bytes": audit["size_bytes"],
        "duplicate_check": duplicate_check,
        "factual_provenance": {
            "independent_publisher_count": (provenance.get("factual_provenance") or {}).get("independent_publisher_count"),
            "source_count": len((provenance.get("factual_provenance") or {}).get("sources") or []),
        },
        "uploaded_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(receipt_path, receipt)
    attempt.update({
        "status": "uploaded_private",
        "youtube_video_id": video_id,
        "youtube_video_url": video_url,
        "completed_at_utc": receipt["uploaded_at_utc"],
    })
    _write_json(attempt_path, attempt)
    _git_commit(
        [str(attempt_path.relative_to(ROOT)), str(receipt_path.relative_to(ROOT))],
        f"Save confirmed private YouTube preview receipt {identity}",
    )
    _summary(
        "## Violin Prince private preview uploaded to YouTube\n\n"
        f"- **Title:** {title}\n"
        f"- **Preview:** {video_url}\n"
        f"- **Channel:** {expected_channel}\n"
        f"- **Slot:** {expected_slot_id}\n"
        f"- **SHA-256:** {audit['sha256']}\n"
        "- **YouTube visibility:** PRIVATE\n"
        "- **Public publishing:** disabled\n"
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description="Upload one validated Violin Prince slot as a private YouTube preview.")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--slot-id", required=True)
    args = parser.parse_args()
    try:
        upload_private_preview(
            args.output_dir,
            args.plan,
            run_id=args.run_id,
            expected_slot_id=args.slot_id,
        )
        return 0
    except (PublishBlocked, OSError, ValueError) as exc:
        message = " ".join(str(exc).split())
        print("PRIVATE_PREVIEW_BLOCKED=" + message[:1000], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
