"""Fail-closed direct YouTube fallback after a confirmed Metricool quota limit.

This is deliberately separate from the expensive production job. It consumes only
the exact, already-released MP4 and the publisher manifest/provenance that were
validated during production. A durable attempt marker is written to the Release
before the upload request so an uncertain retry cannot create a duplicate.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from publisher import youtube_upload


class RouterError(RuntimeError):
    """A publishing request failed its safety or validation contract."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    if not path.is_file():
        raise RouterError(f"Required {label} is missing: {path.name}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RouterError(f"Required {label} is not valid JSON: {path.name}") from exc
    if not isinstance(value, dict):
        raise RouterError(f"Required {label} must be a JSON object: {path.name}")
    return value


def _write_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _validate_request(request: dict[str, Any]) -> tuple[str, str, str]:
    if request.get("schema_version") != 1:
        raise RouterError("Fallback request schema_version must be 1.")
    if request.get("mode") != "metricool_quota_fallback":
        raise RouterError("Fallback request mode must be metricool_quota_fallback.")
    if request.get("reason") != "metricool_monthly_limit_reached":
        raise RouterError(
            "Direct fallback is armed only for a confirmed Metricool monthly-limit response."
        )

    run_id = str(request.get("production_run_id") or "").strip()
    if not re.fullmatch(r"\d{6,20}", run_id):
        raise RouterError("production_run_id must be a numeric GitHub Actions run ID.")
    release_tag = str(request.get("release_tag") or "").strip()
    expected_tag = "violin-prince-short-" + run_id
    if release_tag != expected_tag:
        raise RouterError("release_tag does not match the supplied production_run_id.")

    request_id = str(request.get("request_id") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{8,120}", request_id):
        raise RouterError("request_id must be a unique 8–120 character safe identifier.")
    return run_id, release_tag, request_id


def validate_release_bundle(
    request: dict[str, Any],
    release_dir: Path,
    repository: str,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    """Validate the exact release asset and its provenance before publication."""
    run_id, release_tag, _ = _validate_request(request)
    manifest = _read_json(release_dir / "publish-manifest.json", "publish manifest")
    provenance = _read_json(release_dir / "asset-provenance.json", "asset provenance")
    video_path = release_dir / "violin-prince-short.mp4"

    if manifest.get("status") != "rendered" or manifest.get("publish_ready") is not True:
        raise RouterError("Release manifest is not marked rendered and publish_ready.")
    preflight = manifest.get("publisher_preflight")
    if not isinstance(preflight, dict) or preflight.get("status") != "ready":
        raise RouterError("Publisher preflight is not ready.")
    if preflight.get("blockers"):
        raise RouterError("Publisher preflight still contains blockers.")
    if str(manifest.get("run_id")) != run_id or manifest.get("release_tag") != release_tag:
        raise RouterError("Manifest run ID or release tag does not match the fallback request.")

    expected_url = (
        f"https://github.com/{repository}/releases/download/{release_tag}/violin-prince-short.mp4"
    )
    if manifest.get("public_video_url") != expected_url:
        raise RouterError("Manifest public_video_url does not identify this exact GitHub Release asset.")

    if provenance.get("schema_version") != 1 or str(provenance.get("run_id")) != run_id:
        raise RouterError("Asset provenance schema or run ID does not match the release.")
    factual = provenance.get("factual_provenance")
    if not isinstance(factual, dict):
        raise RouterError("Factual provenance record is missing.")
    sources = factual.get("sources")
    evidence = factual.get("narration_claim_evidence")
    if (
        factual.get("status") != "passed"
        or int(factual.get("independent_publisher_count") or 0) < 2
        or not isinstance(sources, list)
        or len(sources) < 2
        or not isinstance(evidence, list)
        or len(evidence) < 3
    ):
        raise RouterError("Factual provenance does not meet the two-source and three-claim evidence contract.")

    made_for_kids = manifest.get("made_for_kids")
    if not isinstance(made_for_kids, bool):
        raise RouterError("Manifest must contain a confirmed boolean made_for_kids value.")
    if made_for_kids is not False:
        raise RouterError("The existing Violin Prince channel setting is not made for kids; refusing changed metadata.")
    if str(manifest.get("youtube_privacy") or "").lower() != "public":
        raise RouterError("The manifest does not authorise public YouTube publication.")
    if manifest.get("video_type") != "short" or manifest.get("format") != "9:16":
        raise RouterError("Manifest does not describe the approved vertical Shorts format.")
    duration = float(manifest.get("duration_seconds") or 0)
    if not 20 <= duration <= 25:
        raise RouterError("Manifest duration is outside the 20–25 second Short contract.")

    synthetic = provenance.get("synthetic_media")
    if not isinstance(synthetic, dict) or not isinstance(synthetic.get("contains_synthetic_media"), bool):
        raise RouterError("Synthetic-media declaration is missing or not boolean.")
    if manifest.get("contains_synthetic_media") is not synthetic["contains_synthetic_media"]:
        raise RouterError("Manifest and provenance synthetic-media declarations do not match.")

    final_video = (provenance.get("assets") or {}).get("final_video")
    if not isinstance(final_video, dict):
        raise RouterError("Final-video provenance record is missing.")
    if not video_path.is_file() or video_path.stat().st_size < 4096:
        raise RouterError("The released MP4 is missing or unexpectedly small.")
    digest, size = _sha256(video_path)
    if final_video.get("sha256") != digest:
        raise RouterError("Released MP4 SHA-256 does not match asset provenance.")
    expected_size = final_video.get("size_bytes")
    if expected_size is not None and int(expected_size) != size:
        raise RouterError("Released MP4 size does not match asset provenance.")

    metadata = {
        "title": str(manifest.get("title") or "").strip(),
        "description": str(manifest.get("description") or "").strip(),
        "tags": manifest.get("tags") if isinstance(manifest.get("tags"), list) else [],
        "category_id": str(manifest.get("category_id") or "10"),
        "default_language": str(manifest.get("default_language") or "en"),
        "privacy_status": "public",
        "made_for_kids": made_for_kids,
    }
    if not metadata["title"]:
        raise RouterError("The verified manifest does not contain a YouTube title.")
    plan = {
        "title": metadata["title"],
        "hook": metadata["title"],
        "description": metadata["description"],
        "hashtags": manifest.get("hashtags") or [],
        "sources": manifest.get("sources") or [],
        "made_for_kids": made_for_kids,
        "contains_synthetic_media": synthetic["contains_synthetic_media"],
        "publish_metadata": metadata,
    }
    return manifest, plan, video_path


def prepare_attempt(
    request_path: Path,
    release_dir: Path,
    repository: str,
    attempt_id: str,
) -> dict[str, Any]:
    """Create the durable one-attempt guard before any external upload request."""
    request = _read_json(request_path, "publisher fallback request")
    manifest, _plan, _video = validate_release_bundle(request, release_dir, repository)
    _run_id, release_tag, request_id = _validate_request(request)

    receipt_path = release_dir / "publisher-receipt.json"
    if receipt_path.exists():
        receipt = _read_json(receipt_path, "existing publisher receipt")
        if receipt.get("release_tag") != release_tag:
            raise RouterError("Existing publisher receipt belongs to a different release.")
        return {"skip": True, "reason": "A durable publisher receipt already exists.", "receipt": receipt}

    attempt_path = release_dir / "publisher-attempt.json"
    if attempt_path.exists():
        previous = _read_json(attempt_path, "existing publisher attempt marker")
        if previous.get("attempt_id") != attempt_id:
            raise RouterError(
                "An earlier fallback attempt has no final receipt. Refusing to retry because the upload outcome may be unknown."
            )
        return {"skip": False, "reason": "Resuming the same workflow attempt only.", "attempt": previous}

    attempt = {
        "schema_version": 1,
        "status": "attempting",
        "attempt_id": attempt_id,
        "request_id": request_id,
        "production_run_id": str(manifest["run_id"]),
        "release_tag": release_tag,
        "provider": "youtube_data_api",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "note": "This marker is stored before the upload request to prevent duplicate publication after an uncertain retry.",
    }
    _write_json(attempt_path, attempt)
    return {"skip": False, "reason": "Durable attempt marker created.", "attempt": attempt}


def route_to_youtube(
    request_path: Path,
    release_dir: Path,
    repository: str,
    attempt_id: str,
) -> dict[str, Any]:
    """Publish the verified MP4 directly with the existing OAuth uploader."""
    request = _read_json(request_path, "publisher fallback request")
    manifest, plan, video_path = validate_release_bundle(request, release_dir, repository)
    _run_id, release_tag, request_id = _validate_request(request)

    attempt = _read_json(release_dir / "publisher-attempt.json", "publisher attempt marker")
    if attempt.get("attempt_id") != attempt_id or attempt.get("status") != "attempting":
        raise RouterError("No matching durable attempt marker exists; refusing to upload.")

    try:
        result = youtube_upload(video_path, plan)
        video_id = str(result.get("id") or "").strip()
        video_url = str(result.get("url") or "").strip()
        if result.get("ok") is False or not video_id or not video_url:
            raise RouterError("YouTube upload did not return a confirmed video ID and URL.")
        receipt = {
            "schema_version": 1,
            "status": "uploaded",
            "provider": "youtube_data_api",
            "request_id": request_id,
            "production_run_id": str(manifest["run_id"]),
            "release_tag": release_tag,
            "youtube_video_id": video_id,
            "youtube_video_url": video_url,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "privacy_status": "public",
            "made_for_kids": False,
            "contains_synthetic_media": manifest.get("contains_synthetic_media"),
        }
        _write_json(release_dir / "publisher-receipt.json", receipt)
        return receipt
    except Exception as exc:
        # The upload adapter may have reached YouTube before a network exception.
        # Persist an unknown outcome and never auto-retry this release.
        receipt = {
            "schema_version": 1,
            "status": "outcome_unknown",
            "provider": "youtube_data_api",
            "request_id": request_id,
            "production_run_id": str(manifest["run_id"]),
            "release_tag": release_tag,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "error": re.sub(r"\s+", " ", str(exc))[:500],
            "retry_allowed": False,
        }
        _write_json(release_dir / "publisher-receipt.json", receipt)
        raise RouterError(
            "The YouTube upload outcome is uncertain. A durable receipt was written and automatic retry is blocked. "
            "Check the channel's uploads before taking any further action."
        ) from exc


def _write_output(values: dict[str, Any]) -> None:
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as stream:
            for key, value in values.items():
                stream.write(f"{key}={str(value).lower() if isinstance(value, bool) else value}\n")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("guard", "route"))
    parser.add_argument("--request", type=Path, default=Path(".autopilot/publisher-fallback-request.json"))
    parser.add_argument("--release-dir", type=Path, default=Path("work/release"))
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--attempt-id", default=os.environ.get("PUBLISHER_ATTEMPT_ID", ""))
    args = parser.parse_args()

    try:
        if not args.repository or "/" not in args.repository:
            raise RouterError("GITHUB_REPOSITORY is missing or malformed.")
        if not args.attempt_id or not re.fullmatch(r"[A-Za-z0-9_.:-]{6,100}", args.attempt_id):
            raise RouterError("A valid workflow attempt ID is required.")

        if args.command == "guard":
            result = prepare_attempt(args.request, args.release_dir, args.repository, args.attempt_id)
            _write_output({"skip": result["skip"]})
        else:
            result = route_to_youtube(args.request, args.release_dir, args.repository, args.attempt_id)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except RouterError as exc:
        print(f"::error::{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
