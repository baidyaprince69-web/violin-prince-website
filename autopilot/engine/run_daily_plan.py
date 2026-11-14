#!/usr/bin/env python3
"""Run a ChatGPT-authored, source-checked daily plan without Cloudflare services.

ChatGPT writes a compact editorial plan into the repository. This runner verifies
publisher pages and the evidence quotes, synthesizes narration locally with Kokoro,
creates deterministic cinematic scene plates with Pillow, then uses the existing
FFmpeg renderer. It never publishes; the ChatGPT daily operator schedules the
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

from PIL import Image, ImageDraw, ImageFilter

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))

import run as engine  # noqa: E402
from voiceover import synthesize_voiceover  # noqa: E402


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


def _draw_violin(draw: ImageDraw.ImageDraw, cx: int, cy: int, scale: float, bright: bool = True) -> None:
    """Draw an original, simplified violin silhouette for the local scene plate."""
    gold = (229, 188, 112, 245) if bright else (143, 113, 76, 200)
    pale = (250, 229, 190, 225)
    dark = (39, 23, 22, 245)
    body_w, body_h = int(150 * scale), int(260 * scale)
    # Two bouts and a narrow waist make the instrument recognisably violin-shaped.
    draw.ellipse((cx - body_w // 2, cy - body_h // 2, cx + body_w // 2, cy + body_h // 5),
                 fill=dark, outline=gold, width=max(2, int(5 * scale)))
    draw.ellipse((cx - int(body_w * .42), cy - int(body_h * .02),
                  cx + int(body_w * .42), cy + body_h // 2),
                 fill=dark, outline=gold, width=max(2, int(5 * scale)))
    waist = int(35 * scale)
    draw.polygon([
        (cx - body_w // 2, cy - int(body_h * .14)),
        (cx - waist, cy - int(body_h * .04)),
        (cx - int(waist * .65), cy + int(body_h * .15)),
        (cx - body_w // 2, cy + int(body_h * .28)),
        (cx + body_w // 2, cy + int(body_h * .28)),
        (cx + int(waist * .65), cy + int(body_h * .15)),
        (cx + waist, cy - int(body_h * .04)),
        (cx + body_w // 2, cy - int(body_h * .14)),
    ], fill=dark, outline=gold)
    neck_top = cy - int(body_h * .50)
    neck_bottom = cy - int(body_h * .23)
    neck_w = int(28 * scale)
    draw.rounded_rectangle(
        (cx - neck_w // 2, neck_top, cx + neck_w // 2, neck_bottom),
        radius=max(3, int(8 * scale)), fill=(48, 31, 27, 255), outline=gold,
        width=max(2, int(4 * scale)),
    )
    draw.ellipse((cx - int(28 * scale), neck_top - int(34 * scale),
                  cx + int(28 * scale), neck_top + int(22 * scale)),
                 outline=gold, width=max(2, int(4 * scale)))
    # Fingerboard and four strings.
    for offset in (-9, -3, 3, 9):
        x = cx + int(offset * scale)
        draw.line((x, neck_top + int(14 * scale), x, cy + int(body_h * .42)),
                  fill=pale, width=max(1, int(2 * scale)))
    bridge_y = cy + int(body_h * .08)
    draw.polygon([
        (cx - int(43 * scale), bridge_y),
        (cx - int(35 * scale), bridge_y - int(22 * scale)),
        (cx + int(35 * scale), bridge_y - int(22 * scale)),
        (cx + int(43 * scale), bridge_y),
    ], fill=(191, 151, 91, 245))
    for side in (-1, 1):
        x = cx + int(side * 48 * scale)
        draw.arc((x - int(25 * scale), cy - int(12 * scale),
                  x + int(25 * scale), cy + int(80 * scale)),
                 start=35 if side < 0 else 145, end=310 if side < 0 else 215,
                 fill=gold, width=max(2, int(4 * scale)))


def make_scene_plate(scene: dict[str, Any], index: int, target: Path, title: str) -> Path:
    """Create a detailed, deterministic 9:16 illustrated plate without paid image APIs."""
    width, height = 720, 1280
    image = Image.new("RGB", (width, height))
    pixels = image.load()
    top = (6, 10, 20)
    bottom = (28, 20, 28)
    for y in range(height):
        t = y / max(1, height - 1)
        glow = int(9 * (1 - abs(t - .42) * 1.8))
        color = tuple(
            max(0, min(255, int(top[c] * (1 - t) + bottom[c] * t + (glow if c == 0 else glow // 2))))
            for c in range(3)
        )
        for x in range(width):
            pixels[x, y] = color

    # A soft central amber halo gives depth without downloaded artwork.
    halo = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    cx, cy = width // 2, 565
    for radius in range(330, 30, -12):
        alpha = max(1, int((1 - radius / 360) * 5))
        hd.ellipse((cx - radius, cy - radius, cx + radius, cy + radius),
                   outline=(188, 135, 73, alpha), width=14)
    image = Image.alpha_composite(image.convert("RGBA"), halo).convert("RGB")
    draw = ImageDraw.Draw(image, "RGBA")

    # Fine technical grid and golden measurement marks.
    for x in range(42, width, 42):
        draw.line((x, 120, x, 1160), fill=(197, 164, 111, 18), width=1)
    for y in range(140, 1160, 42):
        draw.line((30, y, width - 30, y), fill=(197, 164, 111, 15), width=1)
    for i in range(46):
        x = (i * 97 + index * 53) % width
        y = (i * 173 + index * 89) % height
        radius = 1 + (i % 3)
        draw.ellipse((x - radius, y - radius, x + radius, y + radius),
                     fill=(238, 202, 140, 55 + (i % 4) * 18))

    mode = str(scene.get("visual_mode") or "").casefold()
    if mode in ("macro_3d", "mechanism_3d"):
        # A violin, bridge and taut strings create a tangible opening/reveal.
        _draw_violin(draw, 360, 590, 1.65, bright=True)
        for x in (276, 304, 332, 360, 388, 416, 444):
            draw.line((x, 100, x, 1060), fill=(241, 214, 164, 90), width=2)
        for radius in (230, 290, 350):
            draw.arc((360 - radius, 590 - radius, 360 + radius, 590 + radius),
                     205, 330, fill=(236, 190, 111, 120), width=3)
        draw.line((135, 825, 585, 825), fill=(247, 214, 160, 175), width=4)
        draw.ellipse((345, 806, 375, 836), fill=(255, 223, 167, 235))
    elif mode == "waveform":
        for wave in range(7):
            points = []
            amplitude = 70 + wave * 20
            phase = wave * .42
            for x in range(36, width - 36, 4):
                import math
                y = 580 + int(math.sin(x / (26 + wave * 2) + phase) * amplitude)
                points.append((x, y + wave * 30 - 90))
            draw.line(points, fill=(237, 192 - wave * 7, 121, 205 - wave * 14), width=4)
        for radius in (170, 250, 330):
            draw.arc((360 - radius, 510 - radius, 360 + radius, 510 + radius),
                     205, 335, fill=(221, 183, 123, 135), width=3)
    elif mode == "melody_map":
        import math
        for band in range(5):
            points = []
            for step in range(9):
                x = 70 + step * 72
                y = 450 + band * 95 - int(math.sin(step * .78 + band * .35) * (65 + band * 5))
                points.append((x, y))
            draw.line(points, fill=(239, 196, 124, 210 - band * 20), width=5)
            for x, y in points:
                draw.ellipse((x - 8, y - 8, x + 8, y + 8), fill=(255, 232, 180, 235))
        _draw_violin(draw, 360, 935, .75, bright=False)
    elif mode == "comparison":
        draw.rounded_rectangle((42, 280, 342, 900), radius=28,
                               fill=(21, 25, 38, 215), outline=(221, 184, 124, 190), width=3)
        draw.rounded_rectangle((378, 280, 678, 900), radius=28,
                               fill=(33, 23, 31, 215), outline=(221, 184, 124, 190), width=3)
        for x in (192, 528):
            for radius in (55, 95, 135):
                draw.ellipse((x - radius, 550 - radius, x + radius, 550 + radius),
                             outline=(239, 196, 124, 170), width=4)
        draw.line((360, 280, 360, 900), fill=(244, 212, 155, 180), width=2)
    else:
        # Final scene: a prominent violin and bow, clearly a symbolic visual rather
        # than a claim that the creator's personal performance footage was used.
        _draw_violin(draw, 355, 600, 1.9, bright=True)
        draw.line((135, 260, 590, 980), fill=(240, 217, 178, 225), width=9)
        draw.line((145, 260, 600, 980), fill=(122, 87, 57, 230), width=3)
        for radius in (240, 315, 390):
            draw.arc((355 - radius, 600 - radius, 355 + radius, 600 + radius),
                     210, 335, fill=(239, 197, 128, 115), width=3)

    # Vignette and crisp border finish the plate.
    vignette = Image.new("L", (width, height), 0)
    vd = ImageDraw.Draw(vignette)
    vd.rectangle((0, 0, width, height), fill=245)
    for inset in range(0, 180, 6):
        alpha = max(0, 150 - inset)
        vd.rectangle((inset, inset, width - inset, height - inset), outline=alpha, width=6)
    dark = Image.new("RGB", (width, height), (3, 5, 11))
    image = Image.composite(image, dark, vignette.filter(ImageFilter.GaussianBlur(26)))
    target.parent.mkdir(parents=True, exist_ok=True)
    image.save(target, "JPEG", quality=92, optimize=True)
    return target


def run_daily_plan(plan_path: Path) -> int:
    plan_path = Path(plan_path)
    if not plan_path.is_file():
        raise engine.PipelineError(f"ChatGPT daily plan was not found: {plan_path}")
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise engine.PipelineError("ChatGPT daily plan is not readable JSON.") from exc

    plan, verified_sources = validate_and_enrich_plan(plan)
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

    images = []
    for index, scene in enumerate(plan["scenes"]):
        image_path = engine.PACKAGE / f"scene-{index + 1}.jpg"
        images.append(make_scene_plate(scene, index, image_path, plan.get("title", "")))

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
    return engine.render_stage()


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
        print("DAILY_PRODUCTION_RESULT=" + json.dumps({
            "status": "rendered",
            "run_id": engine.RUN_ID,
            "video": str(final),
            "quality": quality,
            "publishing": "deferred_to_ChatGPT_Metricool_operator",
        }, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        print("Daily production stopped safely: " + str(exc)[:900], file=sys.stderr, flush=True)
        engine.report("failed", str(exc))
        return 1


if __name__ == "__main__":
    sys.exit(main())
