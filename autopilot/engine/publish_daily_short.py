#!/usr/bin/env python3
"""Publish one verified Violin Prince Short directly to public YouTube.

The publisher consumes the rendered MP4 in the current runner. It never creates
a private-video copy or a public GitHub Release. A durable attempt marker is
pushed to main before the YouTube upload request; uncertain outcomes are never
retried automatically.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from publisher import youtube_upload
from youtube_channel_audit import (
    ChannelAuditError,
    DuplicateVideoFound,
    assert_title_absent,
)

ROOT = Path(__file__).resolve().parents[2]
TIMEZONE = "Asia/Kolkata"


class PublishBlocked(RuntimeError):
    """A daily Short failed a pre-upload publication gate."""


def _read_json(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PublishBlocked(f"{label} is missing or invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise PublishBlocked(f"{label} must be a JSON object.")
    return value


def _sha256(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    return digest.hexdigest(), size


def _word_count(value: str) -> int:
    return len(re.findall(r"\b[\w’'-]+\b", str(value or "")))


def probe_video(path: Path) -> dict[str, Any]:
    """Independently inspect the actual MP4 using the runner's FFprobe binary."""
    command = [
        "ffprobe", "-v", "error",
        "-show_entries", "format=duration",
        "-show_entries", "stream=codec_type,codec_name,width,height,sample_rate",
        "-of", "json", str(path),
    ]
    try:
        result = subprocess.run(
            command, check=True, capture_output=True, text=True, timeout=45
        )
        payload = json.loads(result.stdout)
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as exc:
        raise PublishBlocked("FFprobe could not independently inspect the finished MP4.") from exc

    streams = payload.get("streams") or []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    duration = float((payload.get("format") or {}).get("duration") or 0)
    if not video or not audio:
        raise PublishBlocked("The finished MP4 must contain both video and audio streams.")
    if (
        video.get("codec_name") != "h264"
        or int(video.get("width") or 0) != 720
        or int(video.get("height") or 0) != 1280
    ):
        raise PublishBlocked("The finished MP4 is not the expected 720x1280 H.264 vertical format.")
    if int(audio.get("sample_rate") or 0) < 22050:
        raise PublishBlocked("The finished MP4 audio sample rate is below the production contract.")
    if not 20 <= duration <= 25:
        raise PublishBlocked("The finished MP4 duration is outside the 20–25 second Shorts contract.")
    return {
        "status": "passed",
        "duration_seconds": round(duration, 3),
        "width": int(video["width"]),
        "height": int(video["height"]),
        "video_codec": video["codec_name"],
        "audio_codec": audio.get("codec_name"),
        "audio_sample_rate": int(audio["sample_rate"]),
    }


def validate_daily_bundle(
    output_dir: str | Path,
    plan_path: str | Path,
    *,
    run_id: str,
    expected_slot_id: str,
    production_date: str | None = None,
    video_probe: dict[str, Any] | None = None,
    expected_privacy_status: str = "private",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], Path, dict[str, Any]]:
    """Validate the exact rendered asset, editorial provenance and requested YouTube visibility."""
    output = Path(output_dir)
    plan = _read_json(Path(plan_path), "Creative plan")
    manifest = _read_json(output / "publish-manifest.json", "Publisher manifest")
    provenance = _read_json(output / "asset-provenance.json", "Asset provenance")
    video = output / "violin-prince-short.mp4"

    today = production_date or datetime.now(ZoneInfo(TIMEZONE)).date().isoformat()
    if plan.get("production_date") != today:
        raise PublishBlocked(f"Production plan must be dated {today} ({TIMEZONE}).")
    if str(plan.get("slot_id") or "legacy-single") != expected_slot_id:
        raise PublishBlocked("The creative plan slot identity does not match the selected scheduled slot.")
    if str(manifest.get("run_id") or "") != str(run_id):
        raise PublishBlocked("Publisher manifest run ID does not match this GitHub Actions run.")
    if manifest.get("status") != "rendered" or manifest.get("publish_ready") is not True:
        raise PublishBlocked("The rendered manifest is not marked publish_ready.")
    preflight = manifest.get("publisher_preflight")
    if not isinstance(preflight, dict) or preflight.get("status") != "ready" or preflight.get("blockers"):
        blockers = (preflight or {}).get("blockers") or []
        raise PublishBlocked("Publisher preflight is not ready: " + json.dumps(blockers, ensure_ascii=False))
    expected_privacy = str(expected_privacy_status or "").strip().lower()
    if expected_privacy != "private":
        raise PublishBlocked("Automatic Violin Prince publication is private-preview-only; public or unlisted visibility is disabled.")
    manifest_privacy = str(manifest.get("youtube_privacy") or "").strip().lower()
    if manifest_privacy != expected_privacy:
        raise PublishBlocked(
            f"The daily publication manifest does not explicitly request {expected_privacy} YouTube visibility."
        )
    plan_metadata = plan.get("publish_metadata")
    plan_metadata = plan_metadata if isinstance(plan_metadata, dict) else {}
    plan_privacy = str(plan_metadata.get("privacy_status") or plan.get("privacy_status") or "").strip().lower()
    if expected_privacy == "private" and plan_privacy != "private":
        raise PublishBlocked("The scheduled creative plan must explicitly request private YouTube visibility.")
    if plan_privacy and plan_privacy != expected_privacy:
        raise PublishBlocked("Creative-plan and publisher-manifest YouTube visibility do not match.")
    if manifest.get("made_for_kids") is not False:
        raise PublishBlocked("The plan does not match the channel's confirmed not-made-for-kids setting.")
    if manifest.get("format") != "9:16" or manifest.get("video_type") != "short":
        raise PublishBlocked("The publisher manifest does not describe a vertical YouTube Short.")
    if not isinstance(manifest.get("contains_synthetic_media"), bool):
        raise PublishBlocked("The manifest is missing a boolean synthetic-media declaration.")
    if not video.is_file() or video.stat().st_size < 4096:
        raise PublishBlocked("The rendered MP4 is missing or unexpectedly small.")

    factual = provenance.get("factual_provenance")
    if not isinstance(factual, dict) or factual.get("status") != "passed":
        raise PublishBlocked("Verified factual provenance is missing or did not pass.")
    sources = factual.get("sources")
    evidence = factual.get("narration_claim_evidence")
    if (
        not isinstance(sources, list) or len(sources) < 2
        or int(factual.get("independent_publisher_count") or 0) < 2
        or not isinstance(evidence, list) or len(evidence) < 3
        or {int(item.get("sentence_number") or 0) for item in evidence if isinstance(item, dict)} != {2, 3, 4}
    ):
        raise PublishBlocked("Publication requires two independent publisher sources and exact evidence for narration sentences 2–4.")
    if len({str(item.get("publisher_domain") or "").casefold() for item in sources if isinstance(item, dict)}) < 2:
        raise PublishBlocked("Factual provenance does not contain two distinct publisher domains.")

    script = str(plan.get("narration_script") or "").strip()
    sentences = re.findall(r"[^.!?]+[.!?]+(?=\s|$)", script)
    if _word_count(script) != 35 or len(sentences) != 4:
        raise PublishBlocked("The publication plan does not meet the 35-word/four-sentence narration contract.")
    if str(plan.get("title") or "").strip() != str(manifest.get("title") or "").strip():
        raise PublishBlocked("Creative-plan title and publisher-manifest title do not match.")

    synthetic = provenance.get("synthetic_media")
    if not isinstance(synthetic, dict) or synthetic.get("contains_synthetic_media") is not True:
        raise PublishBlocked("Asset provenance does not declare the generated media accurately.")
    if manifest.get("contains_synthetic_media") is not synthetic.get("contains_synthetic_media"):
        raise PublishBlocked("Manifest and asset provenance synthetic-media declarations do not match.")
    assets = provenance.get("assets") or {}
    scene_images = assets.get("scene_images")
    if not isinstance(scene_images, list) or len(scene_images) != 3:
        raise PublishBlocked("Provenance must describe the three rendered scene illustrations.")
    for image_record in scene_images:
        if (
            not isinstance(image_record, dict)
            or image_record.get("origin") != "locally_generated_vector_artwork"
            or image_record.get("provider") != "Violin Prince local vector illustrator"
            or image_record.get("model") != "violin-prince-vector-illustrator-v1"
            or image_record.get("rights_status") != "original_locally_generated_vector_artwork"
            or not re.fullmatch(r"[0-9a-f]{64}", str(image_record.get("sha256") or ""))
        ):
            raise PublishBlocked("Scene illustration provenance does not match the creator-approved local vector renderer.")
    soundtrack = assets.get("soundtrack") or {}
    if soundtrack.get("rights_status") not in {
        "cc0_license_recorded_from_pinned_sample_manifest",
        "locally_procedurally_generated_audio",
    }:
        raise PublishBlocked("Soundtrack provenance does not contain an accepted rights record.")

    final_record = assets.get("final_video") or {}
    digest, size = _sha256(video)
    if final_record.get("sha256") != digest:
        raise PublishBlocked("Final MP4 SHA-256 does not match asset provenance.")
    if final_record.get("size_bytes") is not None and int(final_record["size_bytes"]) != size:
        raise PublishBlocked("Final MP4 size does not match asset provenance.")

    quality = video_probe if video_probe is not None else probe_video(video)
    if quality.get("status") != "passed":
        raise PublishBlocked("Independent final-video inspection did not pass.")
    if (
        quality.get("width") != 720 or quality.get("height") != 1280
        or quality.get("video_codec") != "h264"
        or not 20 <= float(quality.get("duration_seconds") or 0) <= 25
    ):
        raise PublishBlocked("Independent final-video inspection does not match the Shorts format contract.")

    metadata = {
        "title": str(manifest.get("title") or "").strip()[:100],
        "description": str(manifest.get("description") or "").strip()[:5000],
        "tags": manifest.get("tags") if isinstance(manifest.get("tags"), list) else [],
        "category_id": str(manifest.get("category_id") or "10"),
        "default_language": str(manifest.get("default_language") or "en"),
        "privacy_status": expected_privacy,
        "made_for_kids": False,
    }
    if not metadata["title"] or not metadata["description"]:
        raise PublishBlocked("A public YouTube title and description are required.")
    if len(metadata["tags"]) < 3:
        raise PublishBlocked("At least three validated YouTube tags are required.")
    plan["publish_metadata"] = metadata
    plan["made_for_kids"] = False
    plan["contains_synthetic_media"] = True
    return manifest, provenance, plan, video, {
        "sha256": digest, "size_bytes": size, "youtube_metadata": metadata,
        "video_quality": quality,
    }


def _git_commit(paths: list[str], message: str) -> None:
    """Persist a publication marker/receipt on main before/after the API call."""
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=ROOT, check=True)
    subprocess.run(
        ["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"],
        cwd=ROOT, check=True,
    )
    subprocess.run(["git", "fetch", "origin", "main"], cwd=ROOT, check=True)
    subprocess.run(["git", "rebase", "origin/main"], cwd=ROOT, check=True)
    subprocess.run(["git", "add", *paths], cwd=ROOT, check=True)
    staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if staged.returncode == 0:
        raise PublishBlocked("No durable publication record was staged; refusing to upload.")
    subprocess.run(["git", "commit", "-m", message], cwd=ROOT, check=True)

    last_error = ""
    for _attempt in range(3):
        pushed = subprocess.run(
            ["git", "push", "origin", "HEAD:main"],
            cwd=ROOT, capture_output=True, text=True,
        )
        if pushed.returncode == 0:
            return
        last_error = (pushed.stderr or pushed.stdout or "git push failed")[-1200:]
        subprocess.run(["git", "fetch", "origin", "main"], cwd=ROOT, check=True)
        subprocess.run(["git", "rebase", "origin/main"], cwd=ROOT, check=True)
    raise PublishBlocked("Could not persist the publication guard/receipt to main: " + last_error)


def _summary(text: str) -> None:
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(text.rstrip() + "\n")


def publish_daily_short(
    output_dir: str | Path,
    plan_path: str | Path,
    *,
    run_id: str,
    expected_slot_id: str,
    production_date: str | None = None,
) -> dict[str, Any]:
    raise PublishBlocked(
        "Direct public YouTube publication is disabled. Use upload_private_preview_uploadpost.py."
    )
    if os.environ.get("GITHUB_REF_NAME") != "main":
        raise PublishBlocked("Scheduled public publication must execute from main.")
    if os.environ.get("YOUTUBE_PRIVACY_STATUS", "").strip().lower() != "public":
        raise PublishBlocked("YOUTUBE_PRIVACY_STATUS must be explicitly set to public.")
    expected_channel = os.environ.get("YOUTUBE_EXPECTED_CHANNEL_ID", "").strip()
    if not expected_channel:
        raise PublishBlocked("YOUTUBE_EXPECTED_CHANNEL_ID is not configured.")

    manifest, provenance, plan, video, audit = validate_daily_bundle(
        output_dir, plan_path,
        run_id=run_id,
        expected_slot_id=expected_slot_id,
        production_date=production_date,
    )
    title = str(plan["publish_metadata"]["title"])
    identity = re.sub(r"[^A-Za-z0-9_-]+", "-", f"{run_id}-{expected_slot_id}").strip("-")
    attempt_dir = ROOT / ".autopilot/publication-attempts"
    receipt_dir = ROOT / ".autopilot/publication-receipts"
    attempt_path = attempt_dir / f"{identity}.json"
    receipt_path = receipt_dir / f"{identity}.json"

    if receipt_path.is_file():
        receipt = _read_json(receipt_path, "Existing publication receipt")
        if receipt.get("status") == "uploaded" and receipt.get("sha256") == audit["sha256"]:
            _summary("## Already published\n\nA durable receipt already exists for this exact production run and video.")
            return receipt
        raise PublishBlocked("An existing publication receipt conflicts with this production asset.")
    if attempt_path.is_file():
        raise PublishBlocked("A durable upload attempt exists without a final receipt. Check YouTube manually; automatic retries are blocked.")

    os.environ["YOUTUBE_EXPECTED_CHANNEL_ID"] = expected_channel
    try:
        duplicate_check = assert_title_absent(title)
    except DuplicateVideoFound as exc:
        matches = json.dumps(exc.matches[:5], ensure_ascii=False)
        raise PublishBlocked("A video with this exact title already exists on the channel; publication blocked: " + matches) from exc
    except ChannelAuditError as exc:
        raise PublishBlocked("YouTube channel/duplicate audit failed; publication blocked: " + str(exc)) from exc

    attempt = {
        "schema_version": 1,
        "status": "attempting",
        "run_id": str(run_id),
        "production_date": str(plan.get("production_date") or ""),
        "slot_id": expected_slot_id,
        "title": title,
        "youtube_channel_id": expected_channel,
        "privacy_status": "public",
        "sha256": audit["sha256"],
        "size_bytes": audit["size_bytes"],
        "duplicate_check": duplicate_check,
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "note": "Committed before the YouTube API request. An uncertain outcome must be checked manually; no automatic retry is allowed.",
    }
    attempt_dir.mkdir(parents=True, exist_ok=True)
    attempt_path.write_text(json.dumps(attempt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _git_commit(
        [str(attempt_path.relative_to(ROOT))],
        f"Record YouTube publication attempt {identity}",
    )

    try:
        upload = youtube_upload(video, plan)
        video_id = str(upload.get("id") or "").strip()
        video_url = str(upload.get("url") or "").strip()
        if upload.get("ok") is False or not video_id or not video_url:
            raise PublishBlocked("YouTube did not confirm the uploaded video ID and URL.")
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
            "privacy_status": "public",
            "sha256": audit["sha256"],
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "error": re.sub(r"\s+", " ", str(exc))[:500],
            "retry_allowed": False,
        }
        receipt_dir.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _git_commit(
            [str(receipt_path.relative_to(ROOT))],
            f"Record uncertain YouTube publication outcome {identity}",
        )
        raise PublishBlocked(
            "The YouTube upload outcome is uncertain. A durable no-retry receipt was saved; check the channel before any further action."
        ) from exc

    actual_privacy = str(upload.get("privacy_status") or "").strip().lower()
    if actual_privacy != "public":
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
            "requested_privacy_status": "public",
            "returned_privacy_status": actual_privacy or "not returned",
            "sha256": audit["sha256"],
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "retry_allowed": False,
            "note": "YouTube returned an upload ID but did not confirm public visibility. Do not retry or publish another copy; inspect this exact video.",
        }
        receipt_dir.mkdir(parents=True, exist_ok=True)
        receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        attempt.update({
            "status": "uploaded_visibility_mismatch",
            "youtube_video_id": video_id,
            "youtube_video_url": video_url,
            "returned_privacy_status": actual_privacy or "not returned",
        })
        attempt_path.write_text(json.dumps(attempt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        _git_commit(
            [str(attempt_path.relative_to(ROOT)), str(receipt_path.relative_to(ROOT))],
            f"Record YouTube visibility mismatch {identity}",
        )
        raise PublishBlocked(
            "YouTube accepted the upload but did not confirm public visibility. A no-retry receipt was saved; inspect this exact video manually."
        )

    receipt = {
        "schema_version": 1,
        "status": "uploaded",
        "provider": "youtube_data_api",
        "run_id": str(run_id),
        "production_date": str(plan.get("production_date") or ""),
        "slot_id": expected_slot_id,
        "youtube_video_id": video_id,
        "youtube_video_url": video_url,
        "youtube_channel_id": expected_channel,
        "title": title,
        "privacy_status": actual_privacy,
        "sha256": audit["sha256"],
        "size_bytes": audit["size_bytes"],
        "duplicate_check": duplicate_check,
        "factual_provenance": {
            "independent_publisher_count": (provenance.get("factual_provenance") or {}).get("independent_publisher_count"),
            "source_count": len((provenance.get("factual_provenance") or {}).get("sources") or []),
        },
        "uploaded_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    attempt["status"] = "uploaded"
    attempt["youtube_video_id"] = video_id
    attempt["youtube_video_url"] = video_url
    attempt["completed_at_utc"] = receipt["uploaded_at_utc"]
    attempt_path.write_text(json.dumps(attempt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _git_commit(
        [str(attempt_path.relative_to(ROOT)), str(receipt_path.relative_to(ROOT))],
        f"Save YouTube publication receipt {identity}",
    )
    _summary(
        "## Violin Prince Short published publicly on YouTube\n\n"
        f"- **Title:** {title}\n"
        f"- **YouTube:** {video_url}\n"
        f"- **Channel:** {expected_channel}\n"
        f"- **Slot:** {expected_slot_id}\n"
        f"- **SHA-256:** {audit['sha256']}\n"
        "- **Private video copy:** not created\n"
    )
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return receipt


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument("--slot-id", required=True)
    parser.add_argument("--production-date", default="")
    args = parser.parse_args()

    try:
        if not re.fullmatch(r"\d{6,20}", str(args.run_id)):
            raise PublishBlocked("A numeric GitHub Actions run ID is required.")
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", str(args.slot_id)):
            raise PublishBlocked("A valid daily slot ID is required.")
        publish_daily_short(
            args.output_dir,
            args.plan,
            run_id=str(args.run_id),
            expected_slot_id=str(args.slot_id),
            production_date=args.production_date or None,
        )
        return 0
    except (PublishBlocked, OSError, ValueError, subprocess.CalledProcessError) as exc:
        message = "PUBLIC YOUTUBE PUBLICATION BLOCKED: " + str(exc)
        print(message, file=sys.stderr)
        _summary("## Public YouTube publication blocked\n\n" + message)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
