#!/usr/bin/env python3
"""Render a complete, non-publishing procedural Master Director short for inspection.

This CI/demo runner adds temporary synthetic narration and an original, locally
synthesised ambient score. Those tracks are preview scaffolding only; the
scheduled production path must use its independently approved narration and
music assets. No external generation API is called.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import subprocess
import sys
import wave
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFont

ENGINE_DIR = Path(__file__).resolve().parent
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

import run as engine  # noqa: E402
from hyperframes_pipeline import render_master_director_video  # noqa: E402
from master_creative_director import require_valid_director_plan  # noqa: E402


class PreviewRenderError(RuntimeError):
    """Raised when the non-publishing procedural preview cannot be rendered."""


def _run(command: list[str], *, cwd: Path) -> None:
    result = subprocess.run(
        command, cwd=str(cwd), capture_output=True, text=True, check=False
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or "No diagnostic")[-3000:]
        raise PreviewRenderError(f"{Path(command[0]).name} failed: {detail}")


def _make_synthetic_narration(text: str, destination: Path, rate: int = 205) -> float:
    """Create temporary preview-only speech. Never used as a production voice."""
    espeak = shutil.which("espeak-ng")
    if not espeak:
        raise PreviewRenderError("espeak-ng is required only for the non-publishing demo voice track.")
    _run([
        espeak, "-v", "en-us", "-s", str(rate), "-a", "135",
        "-w", str(destination), text
    ], cwd=destination.parent)
    with wave.open(str(destination), "rb") as source:
        return source.getnframes() / float(source.getframerate())


def _make_original_ambient_score(destination: Path, duration: float, sample_rate: int = 48000) -> None:
    """Synthesize a quiet original chord pad; no existing recording or melody is used."""
    sample_count = int(math.ceil(duration * sample_rate))
    timeline = np.arange(sample_count, dtype=np.float64) / sample_rate
    audio = np.zeros(sample_count, dtype=np.float64)
    chords = [
        (0.0, 8.0, (146.83, 220.00, 293.66, 369.99)),
        (8.0, 16.0, (130.81, 196.00, 261.63, 329.63)),
        (16.0, 24.0, (174.61, 261.63, 349.23, 440.00)),
        (24.0, duration, (146.83, 220.00, 293.66, 392.00)),
    ]
    for start, end, frequencies in chords:
        first = max(0, int(start * sample_rate))
        last = min(sample_count, int(end * sample_rate))
        if last <= first:
            continue
        local = timeline[first:last] - start
        fade_in = np.clip(local / 1.3, 0.0, 1.0)
        fade_out = np.clip((end - (local + start)) / 1.5, 0.0, 1.0)
        envelope = np.minimum(fade_in, fade_out) * 0.55
        chord = np.zeros(last - first, dtype=np.float64)
        for index, frequency in enumerate(frequencies):
            partial = np.sin(2.0 * np.pi * frequency * local)
            partial += 0.28 * np.sin(2.0 * np.pi * frequency * 2.0 * local)
            chord += partial * (0.42 / (index + 1))
        audio[first:last] += chord * envelope
    # Add a soft, slow pulse so there is gentle rhythmic movement under speech.
    pulse = 0.035 * (0.5 + 0.5 * np.sin(2.0 * np.pi * 0.25 * timeline))
    audio *= 0.16 + pulse
    peak = max(0.001, float(np.max(np.abs(audio))))
    audio = np.clip(audio / peak * 0.36, -0.95, 0.95)
    stereo = np.column_stack((audio, audio * 0.96))
    pcm = np.asarray(stereo * 32767.0, dtype="<i2")
    with wave.open(str(destination), "wb") as target:
        target.setnchannels(2)
        target.setsampwidth(2)
        target.setframerate(sample_rate)
        target.writeframes(pcm.tobytes())


def _make_word_timing(script: str, audio_duration: float) -> tuple[list[str], list[dict[str, Any]]]:
    sentences = [
        re.sub(r"\s+", " ", value).strip()
        for value in re.split(r"(?<=[.!?])\s+", script.strip())
        if value.strip()
    ]
    if not sentences:
        raise PreviewRenderError("The preview narration script is empty.")
    weighted = []
    for sentence in sentences:
        words = re.findall(r"\S+", sentence)
        if not words:
            continue
        weights = [max(1, len(re.sub(r"[^A-Za-z0-9]", "", word))) for word in words]
        weighted.append((sentence, words, weights, sum(weights)))
    total_weight = sum(item[3] for item in weighted)
    if total_weight <= 0:
        raise PreviewRenderError("Unable to construct word timing for the preview narration.")
    available = max(0.1, min(audio_duration, sum(item[3] for item in weighted) * 60 / 205))
    cursor = 0.18
    usable = max(0.1, available - 0.34)
    word_cues: list[dict[str, Any]] = []
    subtitle_cues: list[str] = []
    for sentence_index, (sentence, words, weights, sentence_weight) in enumerate(weighted):
        sentence_duration = usable * sentence_weight / total_weight
        subtitle_cues.append(sentence)
        sentence_cursor = cursor
        for word, weight in zip(words, weights, strict=True):
            word_duration = sentence_duration * weight / sentence_weight
            word_cues.append({
                "text": word,
                "start": round(sentence_cursor, 3),
                "end": round(sentence_cursor + max(0.07, word_duration - 0.012), 3),
                "sentence_index": sentence_index,
            })
            sentence_cursor += word_duration
        cursor += sentence_duration + 0.025
    if not word_cues:
        raise PreviewRenderError("No preview word timings were created.")
    return subtitle_cues, word_cues


def _make_contact_sheet(video: Path, shots: list[dict[str, Any]], destination: Path) -> None:
    """Extract one centre frame per shot for a quick visual continuity review."""
    frame_paths: list[Path] = []
    for index, shot in enumerate(shots):
        timestamp = (float(shot["start_seconds"]) + float(shot["end_seconds"])) / 2.0
        frame_path = destination.parent / f"shot-{index + 1:02d}-frame.png"
        _run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{timestamp:.3f}", "-i", str(video),
            "-frames:v", "1", "-vf", "scale=360:640",
            str(frame_path),
        ], cwd=destination.parent)
        frame_paths.append(frame_path)

    columns, rows = 4, (len(frame_paths) + 3) // 4
    cell_width, image_height, label_height = 360, 640, 54
    sheet = Image.new("RGB", (columns * cell_width, rows * (image_height + label_height)), "#101722")
    draw = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("DejaVuSans.ttf", 18)
    except OSError:
        font = ImageFont.load_default()
    for index, (frame_path, shot) in enumerate(zip(frame_paths, shots, strict=True)):
        frame = Image.open(frame_path).convert("RGB")
        x = (index % columns) * cell_width
        y = (index // columns) * (image_height + label_height)
        sheet.paste(frame, (x, y))
        caption = f"{index + 1:02d}  {shot['id']}  |  {shot['procedural_scene']['environment']}"
        draw.text((x + 10, y + image_height + 13), caption[:52], fill="#F3EADB", font=font)
    sheet.save(destination, quality=92)


def render_preview(
    plan_path: Path,
    output_dir: Path,
    *,
    rig_bundle_dir: Path | None = None,
) -> dict[str, Any]:
    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PreviewRenderError("Master Director plan is not readable JSON.") from exc
    require_valid_director_plan(plan)
    if plan.get("render_mode") != "procedural_2d":
        raise PreviewRenderError("The preview runner accepts procedural_2d plans only.")
    plan_path = plan_path.expanduser().resolve()
    output_dir = output_dir.expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    production_context = plan.get("production_context") or {}
    narration_script = str(production_context.get("narration_script") or "").strip()
    if not narration_script:
        raise PreviewRenderError("The plan is missing production_context.narration_script.")
    duration = float(plan["storyboard"]["duration_seconds"])
    narration_path = output_dir / "preview-synthetic-narration.wav"
    score_path = output_dir / "original-procedural-preview-score.wav"
    narration_duration = _make_synthetic_narration(narration_script, narration_path)
    _make_original_ambient_score(score_path, duration)
    subtitle_cues, word_cues = _make_word_timing(narration_script, narration_duration)

    report = render_master_director_video(
        engine,
        plan,
        [],
        score_path,
        narration_path,
        {
            "subtitle_cues": subtitle_cues,
            "word_cues": word_cues,
            "timing_source": "estimated_preview_timing_not_production_voice_alignment",
        },
        project_dir=output_dir / "composition",
        output_video=output_dir / "master-director-preview.mp4",
        layer_assets=None,
        rig_bundle_dir=rig_bundle_dir,
    )
    motion = report.get("motion_report") or {}
    expected_shots = len(plan["storyboard"]["shots"])
    if int(report.get("shot_count") or 0) != expected_shots:
        raise PreviewRenderError("Rendered scene count does not match the Director storyboard.")
    if int(motion.get("animated_stagecraft_scene_count") or 0) != expected_shots:
        raise PreviewRenderError("Not every storyboard shot rendered an animated procedural environment.")
    if int(motion.get("animated_stagecraft_object_count") or 0) < expected_shots * 2:
        raise PreviewRenderError("Some Director shots are missing their authored moving objects.")
    if int(motion.get("animated_presenter_count") or 0) < 3:
        raise PreviewRenderError("The rendered short contains too few articulated presenter scenes.")
    if int(motion.get("rendered_layer_count") or 0) != 0:
        raise PreviewRenderError("Procedural v3 unexpectedly staged legacy picture layers.")
    preview_video = output_dir / "master-director-preview.mp4"
    contact_sheet = output_dir / "master-director-contact-sheet.jpg"
    _make_contact_sheet(preview_video, plan["storyboard"]["shots"], contact_sheet)

    preview_meta = {
        "status": "passed",
        "preview_only": True,
        "publishable": False,
        "render_mode": "procedural_2d",
        "renderer": report.get("renderer"),
        "shot_count": expected_shots,
        "duration_seconds": report.get("duration_seconds"),
        "motion_report": motion,
        "final_video_qa": report.get("final_video_qa"),
        "contact_sheet": str(contact_sheet),
        "audio_preview": {
            "narration": "espeak-ng synthetic preview voice; replace with approved production narration",
            "score": "original locally synthesised ambient score; preview use only",
            "word_timing": "estimated from speech duration for preview captions",
        },
        "research_sources": production_context.get("verified_sources") or [],
        "source_ids": production_context.get("source_ids") or [],
    }
    (output_dir / "procedural-preview-report.json").write_text(
        json.dumps(preview_meta, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return preview_meta


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Render and inspect a source-verified procedural Master Director preview."
    )
    parser.add_argument("--plan", required=True, help="Procedural Master Director v3 JSON plan.")
    parser.add_argument("--output-dir", required=True, help="Directory for the MP4 and inspection reports.")
    parser.add_argument("--rig-bundle-dir", help="Optional path to a tested Violin Prince character rig bundle.")
    args = parser.parse_args()
    try:
        result = render_preview(
            Path(args.plan).expanduser(),
            Path(args.output_dir).expanduser(),
            rig_bundle_dir=Path(args.rig_bundle_dir).expanduser() if args.rig_bundle_dir else None,
        )
        print("PROCEDURAL_MASTER_DIRECTOR_PREVIEW=" + json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        print("Procedural preview stopped safely: " + str(exc)[:1600], file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
