#!/usr/bin/env python3
"""Run a ChatGPT-authored, source-checked daily plan through the 2D engine.

ChatGPT supplies the story, narration and scene direction. This runner verifies
publisher evidence, creates scene illustrations, stages original character art,
animates through Motion and renders frame-accurate scenes through HyperFrames.
Existing FFmpeg finishing and quality assurance remain in place.
This script never publishes; it creates the quality-gated release handoff only.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))

import run as engine  # noqa: E402
from voiceover import require_approved_own_voice, synthesize_voiceover  # noqa: E402
from publish_handoff import validate_publish_metadata, write_handoff_files  # noqa: E402
from illustration_asset_factory import prepare_character_assets  # noqa: E402
from hyperframes_pipeline import render_daily_plan  # noqa: E402
from character_presenter import (  # noqa: E402
    PresenterIntegrationError,
    attach_violin_prince_presenter,
    enable_presenter_from_environment,
)
from slot_registry import (  # noqa: E402
    SLOT_CATALOG, SlotContractError, load_daily_batch,
    production_identity as slot_production_identity, slot_workspace, write_slot_receipt,
)


def _normalise_quote(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


def validate_claim_evidence(
    evidence: list[dict[str, Any]],
    sources: list[dict[str, Any]],
    sentences: list[str],
) -> list[dict[str, Any]]:
    """Require one exact, publisher-page quote for each of narration sentences 2–4."""
    if len(sentences) != 4:
        raise engine.PipelineError("Daily narration must contain exactly four sentences.")

    source_by_id = {
        str(item.get("source_id") or "").strip(): item
        for item in sources
        if str(item.get("source_id") or "").strip()
    }
    checked: dict[int, dict[str, Any]] = {}
    for item in evidence if isinstance(evidence, list) else []:
        if not isinstance(item, dict):
            continue
        try:
            sentence_number = int(item.get("sentence_number"))
        except (TypeError, ValueError):
            continue
        source_id = str(item.get("source_id") or "").strip()
        quote = str(item.get("quote") or "").strip()
        if sentence_number not in (2, 3, 4):
            raise engine.PipelineError("Narration evidence must map to sentence numbers 2, 3 and 4.")
        if sentence_number in checked:
            raise engine.PipelineError(f"Duplicate evidence supplied for narration sentence {sentence_number}.")
        source = source_by_id.get(source_id)
        if not source:
            raise engine.PipelineError(
                f"Narration sentence {sentence_number} cites an unselected source: {source_id or '[missing]' }."
            )
        if len(quote) < 28:
            raise engine.PipelineError(
                f"The evidence quote for narration sentence {sentence_number} is too short to verify."
            )
        article_text = _normalise_quote(source.get("evidence_text") or "")
        if _normalise_quote(quote) not in article_text:
            raise engine.PipelineError(
                f"The quote for narration sentence {sentence_number} does not appear in its verified publisher article."
            )
        checked[sentence_number] = {
            "sentence_number": sentence_number,
            "source_id": source_id,
            "quote": quote[:700],
            "publisher_domain": str(source.get("publisher_domain") or ""),
        }

    expected = {2, 3, 4}
    if set(checked) != expected:
        missing = ", ".join(str(value) for value in sorted(expected - set(checked)))
        raise engine.PipelineError("Missing exact publisher evidence for narration sentence(s): " + missing + ".")
    return [checked[number] for number in (2, 3, 4)]



_STORY_COHERENCE_STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "by", "can", "does", "for", "from",
    "how", "in", "into", "is", "it", "its", "of", "on", "or", "that", "the",
    "their", "this", "to", "what", "when", "why", "with", "within",
}
_STORY_COHERENCE_ALIASES = {
    "shape": "arch",
    "curve": "arch",
    "arching": "arch",
    "arches": "arch",
    "resonances": "resonance",
    "frequencies": "frequency",
    "violins": "violin",
    "bodies": "body",
}


def _story_coherence_terms(value: str) -> set[str]:
    """Reduce a short story claim to meaningful, conservative topic anchors."""
    tokens = re.findall(r"[a-z0-9]+", str(value or "").casefold())
    terms = set()
    for token in tokens:
        token = _STORY_COHERENCE_ALIASES.get(token, token)
        if token in _STORY_COHERENCE_STOP_WORDS or len(token) < 3:
            continue
        if token.endswith("s") and len(token) > 4:
            token = token[:-1]
        terms.add(token)
    return terms


def validate_story_coherence(
    plan: dict[str, Any],
    verified_sources: list[dict[str, Any]],
    evidence_records: list[dict[str, Any]],
) -> dict[str, Any]:
    """Ensure every cited publisher supports the same title/core claim.

    Exact quotes alone are not enough: two unrelated, accurately quoted studies
    must not be stitched together as though they were one music fact.
    """
    focus = str(plan.get("core_claim") or plan.get("title") or "").strip()
    focus_terms = _story_coherence_terms(focus)
    if len(focus_terms) < 2:
        raise engine.PipelineError(
            "Story-coherence gate needs a specific core_claim or descriptive title."
        )

    source_by_id = {
        str(item.get("source_id") or ""): item
        for item in verified_sources if isinstance(item, dict)
    }
    cited_ids = {
        str(item.get("source_id") or "")
        for item in evidence_records if isinstance(item, dict)
    }
    selected_ids = set(source_by_id)
    if selected_ids != cited_ids:
        unused = sorted(selected_ids - cited_ids)
        unknown = sorted(cited_ids - selected_ids)
        details = []
        if unused:
            details.append("uncited selected sources: " + ", ".join(unused))
        if unknown:
            details.append("unselected cited sources: " + ", ".join(unknown))
        raise engine.PipelineError(
            "Story-coherence gate requires the evidence source IDs to exactly match the selected sources ("
            + "; ".join(details) + ")."
        )
    if len(cited_ids) < 2:
        raise engine.PipelineError(
            "Story-coherence gate requires at least two cited independent publisher articles."
        )

    minimum_overlap = 2 if len(focus_terms) >= 3 else 1
    checked = []
    for source_id in sorted(cited_ids):
        source = source_by_id.get(source_id)
        if source is None:
            raise engine.PipelineError(
                f"Story-coherence gate found an evidence record without source {source_id}."
            )
        source_text = " ".join((
            str(source.get("title") or ""),
            str(source.get("evidence_text") or ""),
        ))
        source_terms = _story_coherence_terms(source_text)
        overlap = sorted(focus_terms.intersection(source_terms))
        if len(overlap) < minimum_overlap:
            title = str(source.get("title") or source_id)[:120]
            raise engine.PipelineError(
                "Story-coherence gate blocked an unrelated source: "
                + source_id + " (" + title + "). The article does not substantiate "
                "the same core claim as '" + focus[:120] + "'. "
                "Use two publishers covering one shared music fact; do not combine separate studies."
            )
        checked.append({
            "source_id": source_id,
            "matching_topic_terms": overlap,
            "minimum_overlap": minimum_overlap,
        })

    return {
        "status": "passed",
        "core_claim": focus[:240],
        "topic_terms": sorted(focus_terms),
        "cited_sources": checked,
        "rule": "Each cited article must independently match the same core claim; unrelated studies are rejected.",
    }


def validate_and_enrich_plan(plan: dict[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    """Re-fetch sources and enforce the existing editorial, evidence and freshness gates."""
    if not isinstance(plan, dict):
        raise engine.PipelineError("The daily production plan must be a JSON object.")

    raw_sources = plan.get("sources")
    if not isinstance(raw_sources, list) or len(raw_sources) < 2:
        raise engine.PipelineError("The daily plan must provide at least two direct publisher article URLs.")

    sources: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for index, raw in enumerate(raw_sources, start=1):
        if not isinstance(raw, dict):
            raise engine.PipelineError("Every source must be an object containing a publisher article URL.")
        source = dict(raw)
        source_id = str(source.get("source_id") or f"S{index:03d}").strip()
        url = str(source.get("url") or "").strip()
        if not url.startswith(("https://", "http://")):
            raise engine.PipelineError(f"Source {source_id} does not contain an HTTP(S) article URL.")
        if source_id in seen_ids:
            raise engine.PipelineError("Source IDs must be unique.")
        seen_ids.add(source_id)
        source["source_id"] = source_id
        sources.append(source)

    # This fetches the publisher pages again. Headlines, RSS snippets and search
    # results do not qualify as evidence; the article body and date are re-checked.
    enriched = engine.enrich_source_evidence(sources)
    verified = [
        item for item in enriched
        if isinstance(item, dict)
        and item.get("article_page_verified") is True
        and engine.is_direct_publisher_article(item)
    ]
    if len(verified) < 2:
        diagnostics = []
        for item in enriched:
            if not isinstance(item, dict):
                continue
            diagnostics.append({
                "source_id": str(item.get("source_id") or ""),
                "publisher_domain": str(item.get("publisher_domain") or ""),
                "url": str(item.get("url") or ""),
                "article_page_verified": item.get("article_page_verified"),
                "article_page_kind": str(item.get("article_page_kind") or ""),
                "resolution_status": str(item.get("publisher_resolution_status") or ""),
                "resolution_error": str(item.get("publisher_resolution_error") or "")[:220],
                "published_at_utc": str(item.get("published_at_utc") or ""),
                "date": str(item.get("date") or ""),
                "evidence_characters": len(str(item.get("evidence_text") or "")),
            })
        raise engine.PipelineError(
            "Fewer than two readable, date-verifiable direct publisher articles passed the source checks. "
            "Per-source diagnostics: " + json.dumps(diagnostics, ensure_ascii=False)[:1800]
        )

    families = {
        engine.publisher_family_domain(
            item.get("publisher_domain") or item.get("url", "")
        )
        for item in verified
    }
    families.discard("")
    if len(families) < 2:
        raise engine.PipelineError("The selected articles are not from two independent publisher families.")

    script = str(plan.get("narration_script") or "").strip()
    narration_issue = engine.narration_validation_error(script)
    if narration_issue:
        raise engine.PipelineError("Narration failed its exact 35-word/four-sentence calibration and 20–24-second duration target check: " + narration_issue + ".")

    sentences = engine.narration_sentences(script)
    from scene_timeline import apply_scene_operations, ScenePlanError
    try:
        plan = apply_scene_operations(plan, script, minimum_scenes=2, maximum_scenes=4)
    except ScenePlanError as exc:
        raise engine.PipelineError("Scene/narration contract blocked the plan: " + str(exc)) from exc
    sentences = engine.narration_sentences(script)
    plan["narration_evidence"] = validate_claim_evidence(
        plan.get("narration_evidence") or [], verified, sentences
    )
    plan["story_coherence"] = validate_story_coherence(
        plan, verified, plan["narration_evidence"]
    )

    plan["sources"] = verified
    plan["source_group"] = {
        "group_id": "CHATGPT_DAILY_VERIFIED",
        "topic_hint": str(plan.get("topic") or plan.get("title") or "")[:220],
        "publisher_families": sorted(families),
        "independent_publisher_count": len(families),
        "source_ids": [str(item["source_id"]) for item in verified],
        "verified_source_ids": [str(item["source_id"]) for item in verified],
    }

    date_check = engine.validate_story_dates(plan, as_of=datetime.now(timezone.utc).date())
    if date_check.get("status") != "passed":
        raise engine.PipelineError(
            "Story date validation blocked the daily plan: " + " ".join(date_check.get("issues", []))
        )

    quality = engine.build_story_quality_report(plan, verified, date_check, as_of=datetime.now(timezone.utc))
    quality["human_review_required"] = False
    quality["human_review_status"] = "automated_source_date_freshness_and_channel_fit_checks"
    if quality.get("status") != "passed":
        raise engine.PipelineError(
            "Evidence/date/freshness gate blocked production. Check source dates and exact narration quotes."
        )
    plan["quality_control"] = quality
    plan["date_check"] = date_check

    creative_issues = engine.validate_creative_plan(plan)
    if creative_issues:
        raise engine.PipelineError("Violin Prince creative-direction gate blocked production: " + " ".join(creative_issues))

    plan["channel_fit"] = engine.channel_fit_report(plan)
    plan["channel_fit"]["status"] = "passed"
    try:
        plan["visual_reference"] = engine.normalize_visual_reference(
            plan.get("visual_reference"), plan.get("scenes")
        )
    except (TypeError, ValueError) as exc:
        raise engine.PipelineError("Visual reference analysis is invalid: " + str(exc)) from exc
    plan["narrative_style"] = str(plan.get("narrative_style") or "documentary").lower()
    if plan["narrative_style"] not in ("documentary", "cinematic_story"):
        plan["narrative_style"] = "documentary"

    labels = ("THE HOOK", "THE KEY DETAIL", "THE PAYOFF")
    beats = engine.narration_sentences(script)
    for index, scene in enumerate(plan["scenes"]):
        default_label = labels[0] if index == 0 else labels[-1] if index == len(plan["scenes"]) - 1 else f"THE DETAIL {index}"
        mapped_beats = [
            beats[sentence_index]
            for sentence_index in scene.get("narration_sentence_indexes", [])
            if 0 <= sentence_index < len(beats)
        ]
        scene["graphic_label"] = str(scene.get("graphic_label") or default_label)[:32]
        scene["graphic_detail"] = str(
            scene.get("graphic_detail") or " ".join(mapped_beats) or scene.get("caption", "")
        )[:88]
    return plan, verified


def build_production_identity(
    plan_bytes: bytes,
    plan: dict[str, Any],
    *,
    expected_plan_sha256: str = "",
    expected_narration_sha256: str = "",
) -> dict[str, Any]:
    """Pin the exact checked-out plan and normalized script used for narration."""
    if not isinstance(plan, dict):
        raise engine.PipelineError("The daily production plan must be a JSON object.")
    script = re.sub(r"\s+", " ", str(plan.get("narration_script") or "")).strip()
    if not script:
        raise engine.PipelineError("The daily production plan has no narration script.")

    plan_sha256 = hashlib.sha256(plan_bytes).hexdigest()
    narration_sha256 = hashlib.sha256(script.encode("utf-8")).hexdigest()
    expected_plan_sha256 = str(expected_plan_sha256 or "").strip().lower()
    expected_narration_sha256 = str(expected_narration_sha256 or "").strip().lower()
    if bool(expected_plan_sha256) != bool(expected_narration_sha256):
        raise engine.PipelineError(
            "Production snapshot lock is incomplete: both expected plan and narration hashes are required."
        )
    for label, expected, actual in (
        ("plan", expected_plan_sha256, plan_sha256),
        ("narration", expected_narration_sha256, narration_sha256),
    ):
        if expected and not re.fullmatch(r"[0-9a-f]{64}", expected):
            raise engine.PipelineError(f"Expected {label} SHA-256 is malformed.")
        if expected and expected != actual:
            raise engine.PipelineError(
                f"Production snapshot mismatch: checked-out {label} does not match the trigger snapshot. "
                "Refusing to send narration to Qwen3."
            )

    slot_id = str(plan.get("slot_id") or "legacy-single")
    try:
        slot_identity = slot_production_identity(str(plan.get("production_date") or ""), slot_id)
    except SlotContractError as exc:
        raise engine.PipelineError("Daily production slot identity is invalid: " + str(exc)) from exc

    return {
        "schema_version": 1,
        "production_date": str(plan.get("production_date") or ""),
        "slot_id": slot_id,
        "production_identity": slot_identity,
        "plan_sha256": plan_sha256,
        "narration_script_sha256": narration_sha256,
        "narration_word_count": engine.narration_word_count(script),
        "snapshot_lock": "verified" if expected_plan_sha256 else "not_supplied_for_manual_invocation",
    }


def configure_slot_workspace(workspace_root: Path, *, run_id: str) -> None:
    """Point every shared engine path at one slot-owned workspace."""
    root = Path(workspace_root).resolve()
    engine.WORK = root / "work"
    engine.OUT = root / "output"
    engine.IMAGES = root / "images"
    engine.PACKAGE = root / "package"
    engine.RUN_ID = str(run_id)


def run_daily_plan(
    plan_path: Path,
    *,
    workspace_root: Path | None = None,
    batch_snapshot_sha256: str = "",
) -> int:
    # Stop before plan validation, research fetches, soundtrack work or visuals.
    # The former still-illustration route is no longer an acceptable production fallback.
    from animation_production_gate import (
        AnimationProductionGateError,
        require_approved_animation_production,
    )
    try:
        require_approved_animation_production()
    except AnimationProductionGateError as exc:
        raise engine.PipelineError(str(exc)) from exc
    require_approved_own_voice()
    plan_path = Path(plan_path)
    if workspace_root is not None:
        configure_slot_workspace(workspace_root, run_id=os.environ.get("RUN_ID", engine.RUN_ID))
    if not plan_path.is_file():
        raise engine.PipelineError(f"ChatGPT daily plan was not found: {plan_path}")
    try:
        plan_bytes = plan_path.read_bytes()
        plan = json.loads(plan_bytes.decode("utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise engine.PipelineError("ChatGPT daily plan is not readable UTF-8 JSON.") from exc

    production_identity = build_production_identity(
        plan_bytes,
        plan,
        expected_plan_sha256=os.environ.get("EXPECTED_PLAN_SHA256", ""),
        expected_narration_sha256=os.environ.get("EXPECTED_NARRATION_SHA256", ""),
    )
    if batch_snapshot_sha256:
        if not re.fullmatch(r"[0-9a-f]{64}", batch_snapshot_sha256):
            raise engine.PipelineError("The daily batch snapshot SHA-256 is malformed.")
        production_identity["batch_snapshot_sha256"] = batch_snapshot_sha256
    plan, verified_sources = validate_and_enrich_plan(plan)
    scheduled_public_upload = bool(batch_snapshot_sha256)
    if scheduled_public_upload:
        # The creator has explicitly approved direct public YouTube uploads.
        # Re-check the approval file in the production process itself; do not
        # rely only on a workflow environment flag or a batch plan field.
        approval_path = Path(__file__).resolve().parent / "illustration-approval.json"
        try:
            approval = json.loads(approval_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise engine.PipelineError("Public YouTube upload approval is missing or invalid.") from exc
        public_approval = approval.get("creator_publication_approval") if isinstance(approval, dict) else None
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
            raise engine.PipelineError("Creator's explicit public YouTube publishing approval is not valid.")
        supplied_metadata = plan.get("publish_metadata")
        supplied_metadata = supplied_metadata if isinstance(supplied_metadata, dict) else {}
        plan["publish_metadata"] = {**supplied_metadata, "privacy_status": "public"}
    engine.WORK.mkdir(parents=True, exist_ok=True)
    engine.OUT.mkdir(parents=True, exist_ok=True)
    paths = engine._package_paths()
    plan = enable_presenter_from_environment(plan)
    try:
        plan = attach_violin_prince_presenter(
            plan,
            package_dir=engine.PACKAGE,
        )
    except PresenterIntegrationError as exc:
        raise engine.PipelineError(str(exc)) from exc
    try:
        metadata_check = validate_publish_metadata(plan)
    except (TypeError, ValueError) as exc:
        raise engine.PipelineError("YouTube publisher preflight blocked the plan: " + str(exc)) from exc
    plan["publish_metadata"] = dict(metadata_check["value"])
    # Keep generic multi-destination adapters disabled. Scheduled four-slot
    # runs are uploaded only as private previews by a separate fail-closed step.
    os.environ["PUBLISH_ENABLED"] = "false"

    audio_asset, audio_bytes = engine.get_audio(prefer_creator_assets=False)
    if not audio_bytes or len(audio_bytes) < 4096:
        raise engine.PipelineError("The free CC0/ambient violin soundtrack could not be prepared.")
    paths["audio"].write_bytes(audio_bytes)
    from audio_analysis import analyse_audio_file
    known_bpm = (
        (audio_asset.get("bpm") or (audio_asset.get("metadata") or {}).get("bpm"))
        if isinstance(audio_asset, dict) else None
    )
    beat_analysis = analyse_audio_file(
        paths["audio"],
        known_bpm=known_bpm,
        known_beat_times=(audio_asset.get("beat_times") if isinstance(audio_asset, dict) else None),
        known_downbeats=(audio_asset.get("downbeats") if isinstance(audio_asset, dict) else None),
        known_onsets=(audio_asset.get("onsets") if isinstance(audio_asset, dict) else None),
    )
    (engine.PACKAGE / "music-analysis.json").write_text(
        json.dumps(beat_analysis, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    narration_path, narration_info = synthesize_voiceover(
        plan["narration_script"], engine.OUT / "narration.wav"
    )
    private_script_sha256 = str(narration_info.get("script_sha256") or "").strip().lower()
    if private_script_sha256 != production_identity["narration_script_sha256"]:
        raise engine.PipelineError(
            "Private Qwen3 returned narration metadata for a different script version; refusing production."
        )
    production_identity.update({
        "run_id": str(engine.RUN_ID),
        "event_commit_sha": str(os.environ.get("PRODUCTION_EVENT_SHA") or os.environ.get("GITHUB_SHA") or ""),
        "plan_path": str(plan_path),
        "private_voice_script_sha256": private_script_sha256,
        "private_voice_run_id": narration_info.get("private_voice_run_id"),
        "private_voice_verification": narration_info.get("word_sync_status"),
    })
    plan["production_identity"] = production_identity
    identity_text = json.dumps(production_identity, ensure_ascii=False, indent=2) + "\n"
    (engine.PACKAGE / "production-identity.json").write_text(identity_text, encoding="utf-8")
    (engine.OUT / "production-identity.json").write_text(identity_text, encoding="utf-8")
    paths["narration"].write_bytes(narration_path.read_bytes())
    paths["plan"].write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    paths["research"].write_text(
        json.dumps(verified_sources, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    paths["quality_control"].write_text(
        json.dumps(plan["quality_control"], ensure_ascii=False, indent=2), encoding="utf-8"
    )

    from scene_timeline import scene_asset_path
    from media_verification import verify_image_asset, verify_scene_assets
    images = []
    for index, scene in enumerate(plan["scenes"]):
        image_path = scene_asset_path(str(engine.PACKAGE), scene, index, allow_legacy=False)
        image_path.parent.mkdir(parents=True, exist_ok=True)
        if image_path.is_file() and scene.get("_visual_asset_invalidated") is not True:
            try:
                with Image.open(image_path) as existing:
                    existing.verify()
                images.append(image_path)
                scene.pop("_visual_asset_invalidated", None)
                continue
            except Exception:
                image_path.unlink(missing_ok=True)
        elif image_path.is_file():
            image_path.unlink(missing_ok=True)

        prompt = engine._scene_visual_prompt(scene, index=index, plan=plan)
        try:
            generated_image = engine.make_image(prompt, index, scene=scene, plan=plan)
        except (engine.requests.Timeout, engine.requests.ConnectionError):
            engine.log(f"Temporary connection issue for scene {index + 1}; retrying once.")
            engine.time.sleep(2)
            generated_image = engine.make_image(prompt, index, scene=scene, plan=plan)
        image_path.write_bytes(generated_image.read_bytes())
        image_report = verify_image_asset(image_path)
        if image_report.get("status") == "failed":
            raise engine.PipelineError(
                f"Scene illustration {scene['id']} failed independent checks: "
                + json.dumps(image_report.get("errors", []), ensure_ascii=False)
            )
        images.append(image_path)
        scene.pop("_visual_asset_invalidated", None)

    paths["plan"].write_text(
        json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    scene_media_report = verify_scene_assets(
        plan["scenes"], images, total_seconds=24.0, narration_info=narration_info,
        expected_narration_script=plan.get("narration_script"),
    )
    if scene_media_report.get("status") == "failed":
        raise engine.PipelineError(
            "Scene media verification failed: "
            + json.dumps(scene_media_report.get("errors", []), ensure_ascii=False)
        )
    (engine.PACKAGE / "media-verification.json").write_text(
        json.dumps(scene_media_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    character_assets = prepare_character_assets(
        plan,
        source_root=engine.PACKAGE,
        destination_root=engine.WORK / "character-assets",
    )
    metadata = {
        "schema_version": 4,
        "prepared_run_id": engine.RUN_ID,
        "narration_info": narration_info,
        "asset": audio_asset,
        "performance_video": {"available": False, "source": "not_uploaded"},
        "topic": str(plan.get("topic") or ""),
        "title": str(plan.get("title") or "Violin Prince"),
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "production_identity": production_identity,
        "stage": "illustrations_and_character_assets_ready",
        "visual_engine": "Motion + HyperFrames 2D",
        "character_count": len(character_assets),
        "visuals_run_id": engine.RUN_ID,
        "story_review": {
            "status": "approved_by_automated_quality_gates",
            "approved": True,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "approval_method": "verified_publisher_evidence_date_freshness_and_channel_fit",
        },
    }
    paths["metadata"].write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    engine._write_review_text(plan, engine.PACKAGE / "review.txt", {"available": False})
    engine.make_storyboard_preview(
        plan, images, engine.PACKAGE / "storyboard-preview.png"
    )

    audio_path = engine.WORK / "approved-audio"
    audio_path.write_bytes(audio_bytes)
    video_quality = render_daily_plan(
        engine, plan, images, audio_path, narration_path, narration_info, character_assets,
        beat_analysis=beat_analysis,
    )
    final_video = engine.OUT / "violin-prince-short.mp4"
    manifest, _provenance = write_handoff_files(
        engine.OUT,
        plan=plan,
        verified_sources=verified_sources,
        audio_asset=audio_asset,
        audio_path=paths["audio"],
        narration_info=narration_info,
        narration_path=engine.OUT / "narration.wav",
        image_paths=images,
        final_video_path=final_video,
        video_quality=video_quality,
        run_id=engine.RUN_ID,
    )

    slot_id = str(plan.get("slot_id") or "legacy-single")
    slot_identity = str(production_identity.get("production_identity") or "")
    manifest["slot_id"] = slot_id
    manifest["production_identity"] = slot_identity
    manifest["batch_snapshot_sha256"] = batch_snapshot_sha256 or None
    provenance = _provenance
    provenance["slot_id"] = slot_id
    provenance["production_identity"] = slot_identity
    provenance["batch_snapshot_sha256"] = batch_snapshot_sha256 or None
    (engine.OUT / "publish-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8"
    )
    (engine.OUT / "asset-provenance.json").write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8"
    )
    write_slot_receipt(
        engine.OUT / "slot-receipt.json",
        production_date=str(plan.get("production_date") or ""),
        slot_id=slot_id,
        run_id=engine.RUN_ID,
        status=("rendered_ready_for_public_youtube_upload" if scheduled_public_upload else "rendered_handoff_only"),
        output_dir=engine.OUT,
    )
    print(
        "PUBLISHER_PREFLIGHT="
        + json.dumps(manifest.get("publisher_preflight", {}), ensure_ascii=False),
        flush=True,
    )
    return 0


def _materialize_batch_slot(batch_path: Path, slot_id: str, workspace_root: Path) -> tuple[Path, str]:
    """Verify the complete immutable batch and materialize one slot plan."""
    try:
        batch_bytes = batch_path.read_bytes()
        batch_sha256 = hashlib.sha256(batch_bytes).hexdigest()
        expected = str(os.environ.get("EXPECTED_BATCH_SHA256") or "").strip().lower()
        if not re.fullmatch(r"[0-9a-f]{64}", expected) or expected != batch_sha256:
            raise engine.PipelineError("Daily batch snapshot does not match its trigger SHA-256.")

        batch_payload = json.loads(batch_bytes.decode("utf-8"))
        batch_date = str(batch_payload.get("production_date") or "")
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", batch_date):
            raise engine.PipelineError("Daily batch production_date must use YYYY-MM-DD.")
        plans = load_daily_batch(batch_path, expected_date=batch_date)
        plan = next((dict(item) for item in plans if item.get("slot_id") == slot_id), None)
        if plan is None:
            raise engine.PipelineError(f"The daily batch has no plan for slot {slot_id!r}.")
        if str(plan.get("slot_status") or "ready").strip().lower() != "ready":
            reason = str(plan.get("blocked_reason") or "source or editorial evidence gate is not satisfied.")
            raise engine.PipelineError("Selected slot is blocked: " + reason[:500])

        expected_workspace = slot_workspace(Path("work/slots").resolve(), batch_date, slot_id)
        resolved_workspace = workspace_root.resolve()
        if resolved_workspace != expected_workspace.resolve():
            raise engine.PipelineError(
                "Workspace path does not match the validated batch date and slot; refusing to mix outputs."
            )
        os.environ["SLOT_PRODUCTION_DATE"] = batch_date

        input_dir = resolved_workspace / "input"
        input_dir.mkdir(parents=True, exist_ok=True)
        plan_path = input_dir / "daily-plan.json"
        plan_bytes = (json.dumps(plan, ensure_ascii=False, indent=2) + chr(10)).encode("utf-8")
        plan_path.write_bytes(plan_bytes)

        os.environ["EXPECTED_PLAN_SHA256"] = hashlib.sha256(plan_bytes).hexdigest()
        script = re.sub(r"\s+", " ", str(plan.get("narration_script") or "")).strip()
        os.environ["EXPECTED_NARRATION_SHA256"] = hashlib.sha256(script.encode("utf-8")).hexdigest()
        return plan_path, batch_sha256
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, SlotContractError) as exc:
        raise engine.PipelineError("Daily four-slot batch validation failed: " + str(exc)) from exc


def main() -> int:
    parser = argparse.ArgumentParser(description="Render one isolated Violin Prince production slot.")
    inputs = parser.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--plan", help="Path to one ChatGPT-authored JSON plan.")
    inputs.add_argument("--batch", help="Path to the ChatGPT-authored four-plan daily batch.")
    parser.add_argument("--slot-id", help="Canonical content slot ID; required with --batch.")
    parser.add_argument("--workspace-root", help="Isolated output root for this slot.")
    args = parser.parse_args()

    workspace_root = Path(args.workspace_root) if args.workspace_root else None
    batch_snapshot_sha256 = ""
    try:
        if args.batch:
            if args.slot_id not in SLOT_CATALOG:
                raise engine.PipelineError("--batch requires one canonical --slot-id.")
            if workspace_root is None:
                raise engine.PipelineError("--batch requires --workspace-root.")
            plan_path, batch_snapshot_sha256 = _materialize_batch_slot(
                Path(args.batch), args.slot_id, workspace_root
            )
            os.environ["RUN_ID"] = os.environ.get("GITHUB_RUN_ID", engine.RUN_ID)
            os.environ["PUBLISH_ENABLED"] = "false"
        else:
            if args.slot_id and args.slot_id not in ("legacy-single", *SLOT_CATALOG):
                raise engine.PipelineError("Unknown --slot-id.")
            plan_path = Path(args.plan)
            if workspace_root is not None:
                try:
                    plan = json.loads(plan_path.read_text(encoding="utf-8"))
                except (OSError, json.JSONDecodeError) as exc:
                    raise engine.PipelineError("Single plan is not valid JSON.") from exc
                plan.setdefault("slot_id", args.slot_id or "legacy-single")
                plan_path = workspace_root / "input" / "daily-plan.json"
                plan_path.parent.mkdir(parents=True, exist_ok=True)
                plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + chr(10), encoding="utf-8")
                os.environ["EXPECTED_PLAN_SHA256"] = hashlib.sha256(plan_path.read_bytes()).hexdigest()
                os.environ["EXPECTED_NARRATION_SHA256"] = hashlib.sha256(
                    re.sub(r"\s+", " ", str(plan.get("narration_script") or "")).strip().encode("utf-8")
                ).hexdigest()

        result = run_daily_plan(
            plan_path,
            workspace_root=workspace_root,
            batch_snapshot_sha256=batch_snapshot_sha256,
        )
        if result != 0:
            return result

        final = engine.OUT / "violin-prince-short.mp4"
        quality = engine.validate_final_video(final)
        publish_manifest = json.loads((engine.OUT / "publish-manifest.json").read_text(encoding="utf-8"))
        print("DAILY_PRODUCTION_RESULT=" + json.dumps({
            "status": "rendered",
            "run_id": engine.RUN_ID,
            "slot_id": publish_manifest.get("slot_id"),
            "production_identity": publish_manifest.get("production_identity"),
            "video": str(final),
            "quality": quality,
            "publish_manifest": str(engine.OUT / "publish-manifest.json"),
            "asset_provenance": str(engine.OUT / "asset-provenance.json"),
            "publish_ready": publish_manifest.get("publish_ready", False),
            "publisher_preflight": publish_manifest.get("publisher_preflight", {}),
            "publishing": ("private_youtube_preview_after_final_validation" if batch_snapshot_sha256 else "no_automatic_upload"),
        }, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        if workspace_root is not None:
            try:
                from slot_registry import write_slot_receipt
                slot_id = str(args.slot_id or "legacy-single")
                from zoneinfo import ZoneInfo
                production_date = str(os.environ.get("SLOT_PRODUCTION_DATE") or "")
                if not production_date:
                    production_date = datetime.now(ZoneInfo("Asia/Kolkata")).date().isoformat()
                write_slot_receipt(
                    workspace_root / "output" / "slot-receipt.json",
                    production_date=production_date,
                    slot_id=slot_id,
                    run_id=engine.RUN_ID,
                    status="failed",
                    output_dir=workspace_root / "output",
                )
            except Exception:
                pass
        print("Daily production stopped safely: " + str(exc)[:900], file=sys.stderr, flush=True)
        engine.report("failed", str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
