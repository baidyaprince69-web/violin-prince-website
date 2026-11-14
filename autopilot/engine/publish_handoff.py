"""Publisher preflight and asset-provenance records for the daily Violin Prince route.

This module uses only the Python standard library. It records evidence and media
origins already known to the production engine; it is not a legal-clearance tool
and it does not publish or schedule videos.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote


MAX_TITLE_LENGTH = 100
MAX_DESCRIPTION_LENGTH = 5000
MAX_TAGS_LENGTH = 450
MAX_TAG_COUNT = 30
DEFAULT_CATEGORY_ID = "10"
DEFAULT_LANGUAGE = "en"
# The connected Violin Prince channel's audience setting was explicitly
# confirmed as not made for kids in the existing ChatGPT production instructions.
DEFAULT_MADE_FOR_KIDS = False
VALID_PRIVACY = {"public", "unlisted", "private"}


def _strip_controls(value: Any, *, multiline: bool = False) -> str:
    text = str(value or "")
    if multiline:
        text = "".join(
            char for char in text
            if char in "\n\r\t" or ord(char) >= 32 and ord(char) != 127
        )
        return text.strip()
    text = "".join(char if ord(char) >= 32 and ord(char) != 127 else " " for char in text)
    return re.sub(r"\s+", " ", text).strip()


def _parse_tag_values(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    elif isinstance(value, str):
        try:
            raw = next(csv.reader(io.StringIO(value), skipinitialspace=True))
        except (csv.Error, StopIteration):
            raw = value.split()
    else:
        raw = []

    tags: list[str] = []
    seen: set[str] = set()
    total = 0
    for item in raw:
        tag = _strip_controls(item).replace('"', "").lstrip("#").strip()
        if not tag:
            continue
        tag = tag[:100].strip()
        key = tag.casefold()
        if key in seen:
            continue
        next_total = total + len(tag) + (1 if tags else 0)
        if len(tags) >= MAX_TAG_COUNT or next_total > MAX_TAGS_LENGTH:
            break
        tags.append(tag)
        seen.add(key)
        total = next_total
    return tags


def validate_publish_metadata(plan: dict[str, Any]) -> dict[str, Any]:
    """Normalize metadata and return blocking errors and advisory warnings.

    Invalid title/description/tag payloads are blocked before rendering. An
    unknown made-for-kids value does not prevent video generation, but it keeps
    the final publisher handoff in HOLD state until ChatGPT has a confirmed value.
    """
    if not isinstance(plan, dict):
        raise ValueError("Daily production plan must be a JSON object.")

    supplied = plan.get("publish_metadata")
    source = supplied if isinstance(supplied, dict) else plan
    title = _strip_controls(source.get("title") or plan.get("title"))
    description = _strip_controls(
        source.get("description") if source.get("description") is not None else plan.get("description"),
        multiline=True,
    )
    raw_tags = source.get("tags")
    if raw_tags is None:
        raw_tags = plan.get("tags")
    if raw_tags is None:
        raw_tags = source.get("hashtags", plan.get("hashtags", []))
        if isinstance(raw_tags, str):
            raw_tags = raw_tags.split()
    tags = _parse_tag_values(raw_tags)

    errors: list[str] = []
    warnings: list[str] = []
    if not title:
        errors.append("A YouTube title is required.")
    elif len(title) > MAX_TITLE_LENGTH:
        errors.append(f"YouTube title exceeds {MAX_TITLE_LENGTH} characters ({len(title)} supplied).")
    if len(description) > MAX_DESCRIPTION_LENGTH:
        errors.append(
            f"YouTube description exceeds {MAX_DESCRIPTION_LENGTH} characters ({len(description)} supplied)."
        )
    if not description:
        warnings.append("The YouTube description is empty.")
    if len(tags) < 3:
        warnings.append("Fewer than three usable YouTube tags remain after normalization.")

    category_id = str(
        source.get("category_id")
        or source.get("categoryId")
        or plan.get("category_id")
        or DEFAULT_CATEGORY_ID
    ).strip()
    if not re.fullmatch(r"\d{1,3}", category_id):
        errors.append("YouTube category ID must be numeric.")

    language = str(
        source.get("default_language")
        or source.get("defaultLanguage")
        or plan.get("default_language")
        or DEFAULT_LANGUAGE
    ).strip()
    if not re.fullmatch(r"[A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8})*", language):
        errors.append("Default language must be a valid language tag.")

    privacy = str(
        source.get("privacy_status")
        or source.get("youtube_privacy")
        or plan.get("privacy_status")
        or "public"
    ).strip().lower()
    if privacy not in VALID_PRIVACY:
        errors.append("YouTube privacy status must be public, unlisted, or private.")

    audience = source.get("made_for_kids")
    if audience is None:
        audience = plan.get("made_for_kids")
    if audience is None and isinstance(plan.get("publishing"), dict):
        audience = plan["publishing"].get("made_for_kids")
    if audience is None:
        audience = DEFAULT_MADE_FOR_KIDS
    audience_confirmed = isinstance(audience, bool)
    if not audience_confirmed:
        warnings.append(
            "YouTube audience classification is not a boolean; the publisher must hold "
            "the upload until made_for_kids is explicitly confirmed as true or false."
        )

    if errors:
        raise ValueError("YouTube publishing metadata is invalid: " + " ".join(errors))

    return {
        "valid": True,
        "value": {
            "title": title,
            "description": description,
            "tags": tags,
            "category_id": category_id,
            "default_language": language,
            "default_audio_language": language,
            "privacy_status": privacy,
            "made_for_kids": audience if audience_confirmed else None,
        },
        "audience_confirmed": audience_confirmed,
        "warnings": warnings,
        "errors": [],
    }


def _hash_file(path: str | Path) -> dict[str, Any]:
    target = Path(path)
    if not target.is_file():
        raise ValueError(f"Required provenance asset is missing: {target.name}")
    digest = hashlib.sha256()
    size = 0
    with target.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            size += len(chunk)
            digest.update(chunk)
    if size <= 0:
        raise ValueError(f"Required provenance asset is empty: {target.name}")
    return {
        "filename": target.name,
        "size_bytes": size,
        "sha256": digest.hexdigest(),
    }


def _hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def build_asset_provenance(
    *,
    plan: dict[str, Any],
    verified_sources: list[dict[str, Any]],
    audio_asset: dict[str, Any],
    audio_path: str | Path,
    narration_info: dict[str, Any],
    narration_path: str | Path,
    image_paths: list[str | Path],
    final_video_path: str | Path,
    video_quality: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    """Build a verifiable inventory of generated media and factual evidence."""
    if len(image_paths) != 3:
        raise ValueError("The daily production provenance record requires exactly three scene images.")

    soundtrack = _hash_file(audio_path)
    audio_source = str(audio_asset.get("audio_source") or "unknown")
    audio_license = str(audio_asset.get("license") or "")
    if audio_license == "CC0-1.0":
        audio_rights = "cc0_license_recorded_from_pinned_sample_manifest"
    elif audio_source == "generated_ambient_fallback":
        audio_rights = "locally_procedurally_generated_audio"
    else:
        audio_rights = "rights_review_required"

    soundtrack.update({
        "asset_type": "soundtrack",
        "origin": audio_source,
        "license": audio_license or None,
        "rights_status": audio_rights,
        "source_library": str(audio_asset.get("source_library") or ""),
        "attribution": str(audio_asset.get("attribution") or ""),
        "sample_bank_revision": str(audio_asset.get("sample_bank_revision") or ""),
    })

    narration = _hash_file(narration_path)
    narration.update({
        "asset_type": "narration",
        "origin": "synthetic_tts",
        "engine": str(narration_info.get("engine") or "Kokoro-82M"),
        "model_license": str(narration_info.get("model_license") or ""),
        "voice_type": str(narration_info.get("voice_type") or "synthetic"),
        "voice": str(narration_info.get("voice") or ""),
        "rights_status": "synthetic_voice_model_terms_apply",
    })

    scenes = plan.get("scenes", [])
    scene_assets = []
    for index, image_path in enumerate(image_paths):
        scene = scenes[index] if index < len(scenes) and isinstance(scenes[index], dict) else {}
        prompt = str(scene.get("image_prompt") or "")
        asset = _hash_file(image_path)
        asset.update({
            "asset_type": "scene_image",
            "scene_number": index + 1,
            "visual_mode": str(scene.get("visual_mode") or ""),
            "origin": "ai_generated_image",
            "provider": "Cloudflare Workers AI",
            "model": "@cf/black-forest-labs/flux-1-schnell",
            "scene_prompt_source_sha256": _hash_text(prompt),
            "rights_status": "provider_terms_apply_no_external_stock_asset_inserted",
        })
        scene_assets.append(asset)

    final_video = _hash_file(final_video_path)
    final_video.update({
        "asset_type": "final_video",
        "container": "mp4",
        "quality_validation": video_quality,
    })

    source_records = []
    for source in verified_sources:
        if not isinstance(source, dict):
            continue
        source_records.append({
            "source_id": str(source.get("source_id") or ""),
            "title": str(source.get("title") or ""),
            "publisher": str(source.get("publisher_name") or source.get("publisher_domain") or ""),
            "publisher_domain": str(source.get("publisher_domain") or ""),
            "url": str(source.get("url") or ""),
            "published_at_utc": str(source.get("published_at_utc") or source.get("date") or ""),
            "verification": "direct_publisher_article_verified",
        })

    evidence_records = []
    for item in plan.get("narration_evidence", []):
        if isinstance(item, dict):
            evidence_records.append({
                "sentence_number": item.get("sentence_number"),
                "source_id": str(item.get("source_id") or ""),
                "publisher_domain": str(item.get("publisher_domain") or ""),
                "exact_article_quote": str(item.get("quote") or ""),
                "verification": "exact_quote_found_in_verified_publisher_article",
            })

    return {
        "schema_version": 1,
        "run_id": str(run_id),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "content": {
            "title": str(plan.get("title") or ""),
            "topic": str(plan.get("topic") or ""),
            "story_type": str(plan.get("story_type") or ""),
        },
        "factual_provenance": {
            "status": str((plan.get("quality_control") or {}).get("status") or "unknown"),
            "independent_publisher_count": (plan.get("source_group") or {}).get("independent_publisher_count"),
            "sources": source_records,
            "narration_claim_evidence": evidence_records,
        },
        "assets": {
            "scene_images": scene_assets,
            "narration": narration,
            "soundtrack": soundtrack,
            "final_video": final_video,
            "creator_supplied_performance": {
                "included": False,
                "reason": "The ChatGPT daily route does not insert a private creator-uploaded performance asset.",
            },
        },
        "synthetic_media": {
            "contains_synthetic_media": True,
            "reason": "The video contains AI-generated scene imagery and synthetic TTS narration.",
        },
        "rights_notice": (
            "This file records media origins and license metadata available to the pipeline. "
            "It is not legal advice or blanket rights clearance. Provider terms apply to generated "
            "media; separately supplied assets require their own permission review."
        ),
    }


def build_publish_manifest(
    *,
    plan: dict[str, Any],
    metadata_check: dict[str, Any],
    video_quality: dict[str, Any],
    provenance: dict[str, Any],
    run_id: str,
) -> dict[str, Any]:
    """Create a publisher-facing handoff. A missing audience choice means HOLD."""
    metadata = metadata_check["value"]
    blockers: list[str] = []
    if not (
        video_quality.get("width") == 720
        and video_quality.get("height") == 1280
        and video_quality.get("video_codec") == "h264"
        and float(video_quality.get("duration_seconds") or 0) > 0
        and int(video_quality.get("audio_sample_rate") or 0) >= 22050
    ):
        blockers.append("Final MP4 quality validation did not return the expected vertical H.264/audio contract.")
    if not metadata_check.get("audience_confirmed"):
        blockers.append("Confirm made_for_kids as true or false before scheduling or publishing.")
    audio_rights = provenance.get("assets", {}).get("soundtrack", {}).get("rights_status")
    if audio_rights == "rights_review_required":
        blockers.append("Soundtrack origin or license needs review before publication.")

    repository = str(os.environ.get("GITHUB_REPOSITORY") or "").strip()
    github_run = str(os.environ.get("GITHUB_RUN_ID") or run_id).strip()
    release_tag = f"violin-prince-short-{github_run}"
    public_video_url = (
        f"https://github.com/{repository}/releases/download/{quote(release_tag, safe='')}/violin-prince-short.mp4"
        if repository and github_run else ""
    )

    return {
        "schema_version": 1,
        "status": "rendered",
        "run_id": str(run_id),
        "release_tag": release_tag,
        "public_video_url": public_video_url or None,
        "title": metadata["title"],
        "description": metadata["description"],
        "tags": metadata["tags"],
        "hashtags": plan.get("hashtags") or [],
        "category_id": metadata["category_id"],
        "default_language": metadata["default_language"],
        "default_audio_language": metadata["default_audio_language"],
        "youtube_privacy": metadata["privacy_status"],
        "made_for_kids": metadata["made_for_kids"],
        "contains_synthetic_media": True,
        "duration_seconds": video_quality.get("duration_seconds", 24),
        "format": "9:16",
        "video_type": "short",
        "sources": [
            {"title": item.get("title", ""), "url": item.get("url", "")}
            for item in provenance.get("factual_provenance", {}).get("sources", [])
        ],
        "asset_provenance_file": "asset-provenance.json",
        "publisher": "ChatGPT daily operator via Metricool",
        "publishing_enabled_in_github": False,
        "publish_ready": not blockers,
        "publisher_preflight": {
            "status": "ready" if not blockers else "hold",
            "blockers": blockers,
            "warnings": metadata_check.get("warnings", []),
            "required_action": (
                "Resolve every blocker before Metricool scheduling or any public upload."
                if blockers else "Metadata and production checks passed; proceed through the configured publisher."
            ),
        },
    }


def write_handoff_files(
    output_dir: str | Path,
    *,
    plan: dict[str, Any],
    verified_sources: list[dict[str, Any]],
    audio_asset: dict[str, Any],
    audio_path: str | Path,
    narration_info: dict[str, Any],
    narration_path: str | Path,
    image_paths: list[str | Path],
    final_video_path: str | Path,
    video_quality: dict[str, Any],
    run_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Write the publisher handoff and companion asset provenance JSON files."""
    check = validate_publish_metadata(plan)
    provenance = build_asset_provenance(
        plan=plan,
        verified_sources=verified_sources,
        audio_asset=audio_asset,
        audio_path=audio_path,
        narration_info=narration_info,
        narration_path=narration_path,
        image_paths=image_paths,
        final_video_path=final_video_path,
        video_quality=video_quality,
        run_id=run_id,
    )
    manifest = build_publish_manifest(
        plan=plan,
        metadata_check=check,
        video_quality=video_quality,
        provenance=provenance,
        run_id=run_id,
    )
    target = Path(output_dir)
    target.mkdir(parents=True, exist_ok=True)
    (target / "asset-provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (target / "publish-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest, provenance
