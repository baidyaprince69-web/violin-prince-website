"""Validate and upload only a Phase 3 READY YouTube release.

The workflow always validates the handoff report, original V3 artifact, MP4 hash,
recovery manifest and QC report before any upload attempt. Upload is a separate,
explicitly confirmed private-beta operation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .engine import YouTubeNativeClient, build_metadata


class ReleaseValidationError(RuntimeError):
    """The V3 artifact does not match a verified Phase 3 YouTube READY release."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ReleaseValidationError(f"Required release JSON is missing or invalid: {path.name}") from exc
    if not isinstance(value, dict):
        raise ReleaseValidationError(f"Required release JSON is not an object: {path.name}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _decision(value: str) -> bool | None:
    clean = str(value or "unconfirmed").strip().lower()
    if clean == "true":
        return True
    if clean == "false":
        return False
    if clean == "unconfirmed":
        return None
    raise ReleaseValidationError("Audience and synthetic-media decisions must be true, false, or unconfirmed.")


def validate_phase3_release(
    report_path: str | Path,
    artifact_root: str | Path,
    expected_run_id: str,
) -> dict[str, Any]:
    """Return the exact MP4 and release ID only after all provenance checks pass."""
    run_id = str(expected_run_id).strip()
    if not run_id.isdigit():
        raise ReleaseValidationError("The Phase 3 source run ID must be numeric.")

    root = Path(artifact_root)
    report = _read_json(Path(report_path))
    if report.get("schema_version") != 1 or report.get("phase") != "phase3_release_handoff":
        raise ReleaseValidationError("Unsupported Phase 3 release-handoff schema.")
    if report.get("status") != "prepared":
        raise ReleaseValidationError("Phase 3 handoff is not in prepared state.")
    if report.get("publishing_enabled") is not False or report.get("provider_requests_made") != 0:
        raise ReleaseValidationError("The source handoff is not a valid non-publishing Phase 3 record.")

    source = report.get("source") or {}
    if str(source.get("phase2_run_id") or "") != run_id:
        raise ReleaseValidationError("The Phase 3 report does not belong to the requested V3 run.")
    if str(source.get("artifact_name") or "") != f"v3-motion-prototype-{run_id}":
        raise ReleaseValidationError("The Phase 3 report references a different V3 artifact.")

    phase2 = report.get("phase2") or {}
    if phase2.get("video_file") != "html-motion-prototype.mp4":
        raise ReleaseValidationError("The Phase 3 report does not identify the expected final MP4.")

    output_root = root / "output" / "motion-prototype"
    video_path = output_root / "html-motion-prototype.mp4"
    manifest_path = output_root / "recovery-manifest.json"
    qc_path = output_root / "quality-control-report.json"
    plan_path = root / "package" / "creative_plan.json"
    for path in (video_path, manifest_path, qc_path, plan_path):
        if not path.is_file() or path.stat().st_size == 0:
            raise ReleaseValidationError(f"Required V3 release artifact is missing: {path.relative_to(root)}")

    video_hash = _sha256(video_path)
    if video_hash != str(phase2.get("video_sha256") or ""):
        raise ReleaseValidationError("The MP4 SHA-256 does not match the Phase 3 handoff report.")
    if _sha256(manifest_path) != str(phase2.get("manifest_sha256") or ""):
        raise ReleaseValidationError("The recovery manifest hash does not match the Phase 3 handoff report.")
    if _sha256(qc_path) != str(phase2.get("qc_report_sha256") or ""):
        raise ReleaseValidationError("The QC report hash does not match the Phase 3 handoff report.")

    manifest = _read_json(manifest_path)
    qc = _read_json(qc_path)
    plan = _read_json(plan_path)
    if manifest.get("publishing_enabled") is not False:
        raise ReleaseValidationError("The V3 recovery manifest does not confirm publishing-disabled mode.")
    if manifest.get("package_fingerprint") != phase2.get("package_fingerprint"):
        raise ReleaseValidationError("The creative package fingerprint differs from the Phase 3 handoff.")
    audio_mix = (manifest.get("stages") or {}).get("audio_mix") or {}
    qc_stage = (manifest.get("stages") or {}).get("quality_control") or {}
    if audio_mix.get("output_sha256") != video_hash or qc_stage.get("status") != "passed":
        raise ReleaseValidationError("The V3 recovery manifest does not confirm the exact final MP4 and passed QC.")
    if qc.get("passed") is not True or qc.get("status") != "passed":
        raise ReleaseValidationError("The V3 quality-control report did not pass.")
    checks = qc.get("checks") or []
    if not checks or any(item.get("passed") is not True for item in checks):
        raise ReleaseValidationError("The V3 QC report contains missing or failed checks.")
    if len(checks) != int(phase2.get("qc_checks_total") or -1):
        raise ReleaseValidationError("The number of QC checks does not match the Phase 3 report.")
    if sum(1 for item in checks if item.get("passed") is True) != int(phase2.get("qc_checks_passed") or -1):
        raise ReleaseValidationError("The passed QC check count does not match the Phase 3 report.")

    youtube_rows = [
        item for item in report.get("releases", [])
        if item.get("destination") == "youtube"
    ]
    if len(youtube_rows) != 1 or youtube_rows[0].get("state") != "READY":
        raise ReleaseValidationError("A unique YouTube release in READY state is required.")
    release_id = str(youtube_rows[0].get("release_id") or "").strip()
    if not release_id:
        raise ReleaseValidationError("Phase 3 did not return a YouTube release ID.")

    return {
        "release_id": release_id,
        "phase3_run_id": run_id,
        "video_path": str(video_path),
        "video_sha256": video_hash,
        "video_size_bytes": video_path.stat().st_size,
        "metadata_sha256": str(report.get("metadata_sha256") or ""),
        "creative_plan_path": str(plan_path),
        "title": str(plan.get("title") or ""),
        "topic": str(plan.get("topic") or ""),
        "qc_checks_passed": int(phase2.get("qc_checks_passed") or 0),
        "qc_checks_total": int(phase2.get("qc_checks_total") or 0),
        "qc_status": qc.get("status"),
        "privacy_status": "private",
    }


def prepare_review(
    release: dict[str, Any],
    *,
    metadata_overrides_json: str = "",
    made_for_kids: str = "unconfirmed",
    contains_synthetic_media: str = "unconfirmed",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Prepare metadata for review; never self-approve it."""
    plan = _read_json(Path(release["creative_plan_path"]))
    overrides_text = str(metadata_overrides_json or "").strip()
    if overrides_text:
        try:
            overrides = json.loads(overrides_text)
        except json.JSONDecodeError as exc:
            raise ReleaseValidationError("metadata_overrides_json must be a valid JSON object.") from exc
        if not isinstance(overrides, dict):
            raise ReleaseValidationError("metadata_overrides_json must be a JSON object.")
        allowed = {"seo_title", "seo_description", "seo_tags", "seo_hashtags", "primary_keyword"}
        unknown = set(overrides) - allowed
        if unknown:
            raise ReleaseValidationError("Unsupported metadata override field(s): " + ", ".join(sorted(unknown)))
        plan.update(overrides)

    kids_decision = _decision(made_for_kids)
    synthetic_decision = _decision(contains_synthetic_media)
    if kids_decision is not None:
        plan["made_for_kids"] = kids_decision
    if synthetic_decision is not None:
        plan["contains_synthetic_media"] = synthetic_decision
    plan["seo_metadata_approved"] = False

    review: dict[str, Any] = {
        "status": "awaiting_owner_review",
        "release_id": release["release_id"],
        "phase3_run_id": release["phase3_run_id"],
        "video_sha256": release["video_sha256"],
        "privacy_status": "private",
        "title_candidate": plan.get("seo_title") or plan.get("title") or "",
        "description_candidate": plan.get("seo_description") or plan.get("description") or "",
        "ordinary_tags_candidate": plan.get("seo_tags") or plan.get("tags") or [],
        "hashtags_candidate": plan.get("seo_hashtags") or plan.get("hashtags") or [],
        "made_for_kids": kids_decision,
        "contains_synthetic_media": synthetic_decision,
        "qc": f"{release['qc_checks_passed']}/{release['qc_checks_total']}",
        "metadata_audit": None,
        "metadata_error": None,
        "approval_required": True,
    }
    try:
        metadata = build_metadata(plan, privacy_status="private", allow_public=False)
        review["metadata_audit"] = metadata["audit"]
        review["title_candidate"] = metadata["body"]["snippet"]["title"]
        review["description_candidate"] = metadata["body"]["snippet"]["description"]
        review["ordinary_tags_candidate"] = metadata["body"]["snippet"].get("tags", [])
        review["metadata_valid"] = True
    except Exception as exc:
        review["metadata_valid"] = False
        review["metadata_error"] = str(exc)
    return plan, review


def run_private_upload(
    release: dict[str, Any],
    plan: dict[str, Any],
    *,
    confirm_private_upload: bool,
    confirm_asset_rights: bool,
    confirm_metadata_approved: bool,
) -> dict[str, Any]:
    """Upload only after every owner confirmation and the private-only environment gate."""
    if not confirm_private_upload or not confirm_asset_rights or not confirm_metadata_approved:
        raise ReleaseValidationError(
            "Private upload requires explicit upload, content-rights and metadata confirmations."
        )
    if plan.get("made_for_kids") not in (True, False):
        raise ReleaseValidationError("Select an explicit made-for-kids decision before upload.")
    if plan.get("contains_synthetic_media") not in (True, False):
        raise ReleaseValidationError("Select an explicit synthetic-media disclosure decision before upload.")
    if plan.get("seo_metadata_approved") is not False:
        raise ReleaseValidationError("The review plan must not arrive pre-approved.")
    plan = dict(plan)
    plan["seo_metadata_approved"] = True
    client = YouTubeNativeClient()
    result = client.upload_video(
        release["video_path"],
        plan,
        release_id=release["release_id"],
    )
    processing = client.wait_for_processing(result["video_id"])
    return {
        "status": "uploaded_private_and_processed",
        "release_id": release["release_id"],
        "video_id": result["video_id"],
        "url": result["url"],
        "already_uploaded": result["already_uploaded"],
        "privacy_status": processing.get("privacy_status"),
        "upload_status": processing.get("upload_status"),
        "processing_status": processing.get("processing_status"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", required=True)
    parser.add_argument("--artifact-root", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--output", default="work/youtube-release-review.json")
    parser.add_argument("--metadata-overrides-json", default="")
    parser.add_argument("--made-for-kids", choices=("true", "false", "unconfirmed"), default="unconfirmed")
    parser.add_argument("--contains-synthetic-media", choices=("true", "false", "unconfirmed"), default="unconfirmed")
    parser.add_argument("--upload", action="store_true")
    parser.add_argument("--confirm-private-upload", action="store_true")
    parser.add_argument("--confirm-asset-rights", action="store_true")
    parser.add_argument("--confirm-metadata-approved", action="store_true")
    args = parser.parse_args()

    release = validate_phase3_release(args.report, args.artifact_root, args.run_id)
    plan, review = prepare_review(
        release,
        metadata_overrides_json=args.metadata_overrides_json,
        made_for_kids=args.made_for_kids,
        contains_synthetic_media=args.contains_synthetic_media,
    )
    if not review["metadata_valid"] and args.upload:
        raise ReleaseValidationError("Reviewed metadata is invalid: " + str(review.get("metadata_error")))
    result: dict[str, Any] = {"release": release, "review": review}
    if args.upload:
        result["upload"] = run_private_upload(
            release,
            plan,
            confirm_private_upload=args.confirm_private_upload,
            confirm_asset_rights=args.confirm_asset_rights,
            confirm_metadata_approved=args.confirm_metadata_approved,
        )
    destination = Path(args.output)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
