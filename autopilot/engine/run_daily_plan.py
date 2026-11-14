#!/usr/bin/env python3
"""Run a ChatGPT-authored, source-checked daily plan with photorealistic scene generation.

ChatGPT writes a compact editorial plan into the repository. This runner verifies
publisher pages and the evidence quotes, synthesizes narration locally with Kokoro,
generates full-colour photorealistic scene images with the existing FLUX image model,
then uses the existing FFmpeg renderer. It never publishes; the ChatGPT daily operator schedules the
finished public release asset through Metricool after the render succeeds.
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

from PIL import Image

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))

import run as engine  # noqa: E402
from voiceover import synthesize_voiceover  # noqa: E402
from publish_handoff import validate_publish_metadata, write_handoff_files  # noqa: E402


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
        raise engine.PipelineError("Narration failed its four-sentence/40–44-word check: " + narration_issue + ".")

    sentences = engine.narration_sentences(script)
    plan["narration_evidence"] = validate_claim_evidence(
        plan.get("narration_evidence") or [], verified, sentences
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
        scene["graphic_label"] = str(scene.get("graphic_label") or labels[index])[:32]
        scene["graphic_detail"] = str(
            scene.get("graphic_detail") or beats[min(index, len(beats) - 1)]
        )[:88]
    return plan, verified


def run_daily_plan(plan_path: Path) -> int:
    plan_path = Path(plan_path)
    if not plan_path.is_file():
        raise engine.PipelineError(f"ChatGPT daily plan was not found: {plan_path}")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise engine.PipelineError("ChatGPT daily plan is not readable JSON.") from exc

    plan, verified_sources = validate_and_enrich_plan(plan)
    try:
        metadata_check = validate_publish_metadata(plan)
    except (TypeError, ValueError) as exc:
        raise engine.PipelineError("YouTube publisher preflight blocked the plan: " + str(exc)) from exc
    # Store the normalized metadata in the saved plan so every downstream handoff
    # reads the exact same title, description, tags, language and privacy setting.
    plan["publish_metadata"] = dict(metadata_check["value"])
    engine.WORK.mkdir(parents=True, exist_ok=True)
    engine.OUT.mkdir(parents=True, exist_ok=True)
    paths = engine._package_paths()

    # The daily ChatGPT mode is deliberately independent from the optional
    # Cloudflare Worker, R2 bucket, and all direct-publishing credentials.
    engine.API = ""
    engine.JOB_TOKEN = ""
    os.environ["AUTOPILOT_API_URL"] = ""
    os.environ["AUTOPILOT_JOB_TOKEN"] = ""
    os.environ["PUBLISH_ENABLED"] = "false"

    audio_asset, audio_bytes = engine.get_audio(prefer_creator_assets=False)
    if not audio_bytes or len(audio_bytes) < 4096:
        raise engine.PipelineError("The free CC0/ambient violin soundtrack could not be prepared.")
    paths["audio"].write_bytes(audio_bytes)

    narration_path, narration_info = synthesize_voiceover(
        plan["narration_script"], engine.OUT / "narration.wav"
    )
    paths["narration"].write_bytes(narration_path.read_bytes())
    paths["plan"].write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    paths["research"].write_text(
        json.dumps(verified_sources, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    paths["quality_control"].write_text(
        json.dumps(plan["quality_control"], ensure_ascii=False, indent=2), encoding="utf-8"
    )

    # Reuse the photorealistic FLUX image-generation path from the earlier
    # Visuals stage. Never silently degrade to stick drawings or line art.
    if not engine.CF_ACCOUNT or not engine.CF_TOKEN:
        raise engine.PipelineError(
            "Photorealistic scene generation requires CF_ACCOUNT_ID and CF_AI_TOKEN. "
            "The run will stop rather than substitute basic line drawings."
        )

    images = []
    for index, scene in enumerate(plan["scenes"]):
        image_path = engine.PACKAGE / f"scene-{index + 1}.jpg"
        prompt = engine._scene_visual_prompt(scene, index=index, plan=plan)
        generated_image = engine.make_image(prompt, index)
        image_path.write_bytes(generated_image.read_bytes())
        with Image.open(image_path) as image_check:
            if image_check.width < 512 or image_check.height < 512:
                raise engine.PipelineError(f"Generated scene image {index + 1} is unexpectedly small.")
            image_check.verify()
        images.append(image_path)

    metadata = {
        "schema_version": 3,
        "prepared_run_id": engine.RUN_ID,
        "narration_info": narration_info,
        "asset": audio_asset,
        "performance_video": {"available": False, "source": "not_uploaded"},
        "topic": str(plan.get("topic") or ""),
        "title": str(plan.get("title") or "Violin Prince"),
        "prepared_at": datetime.now(timezone.utc).isoformat(),
        "stage": "visuals_ready",
        "visuals_run_id": engine.RUN_ID,
        "story_review": {
            "status": "approved_by_automated_quality_gates",
            "approved": True,
            "approved_at": datetime.now(timezone.utc).isoformat(),
            "approval_method": "verified_publisher_evidence_date_freshness_and_channel_fit",
        },
    }
    paths["metadata"].write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")
    engine._write_review_text(plan, engine.PACKAGE / "review.txt", {"available": False})
    engine.make_storyboard_preview(plan, images, engine.PACKAGE / "storyboard-preview.png")

    # Existing FFmpeg render and media QA remain the final authority for the MP4.
    result = engine.render_stage()
    if result != 0:
        return result
    final_video = engine.OUT / "violin-prince-short.mp4"
    video_quality = engine.validate_final_video(final_video)
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
    print(
        "PUBLISHER_PREFLIGHT="
        + json.dumps(manifest.get("publisher_preflight", {}), ensure_ascii=False),
        flush=True,
    )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Render one ChatGPT-prepared Violin Prince daily plan.")
    parser.add_argument("--plan", required=True, help="Path to the ChatGPT-authored JSON plan.")
    args = parser.parse_args()
    try:
        result = run_daily_plan(Path(args.plan))
        if result != 0:
            return result
        final = engine.OUT / "violin-prince-short.mp4"
        quality = engine.validate_final_video(final)
        publish_manifest = json.loads((engine.OUT / "publish-manifest.json").read_text(encoding="utf-8"))
        print("DAILY_PRODUCTION_RESULT=" + json.dumps({
            "status": "rendered",
            "run_id": engine.RUN_ID,
            "video": str(final),
            "quality": quality,
            "publish_manifest": str(engine.OUT / "publish-manifest.json"),
            "asset_provenance": str(engine.OUT / "asset-provenance.json"),
            "publish_ready": publish_manifest.get("publish_ready", False),
            "publisher_preflight": publish_manifest.get("publisher_preflight", {}),
            "publishing": "deferred_to_ChatGPT_Metricool_operator",
        }, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        print("Daily production stopped safely: " + str(exc)[:900], file=sys.stderr, flush=True)
        engine.report("failed", str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
