#!/usr/bin/env python3
"""Build an isolated HTML-renderer V3 preview beside the unchanged V2 renderer."""
from __future__ import annotations

import argparse
import base64
import json
import shutil
import subprocess
import sys
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE))

from voiceover import synthesize_voiceover
import run as pipeline


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        tail = (result.stderr or result.stdout or "")[-4000:]
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command[:4])}\n{tail}")


def _mix_audio(video_only: Path, soundtrack: Path, narration: Path,
               target: Path, audio_source: str) -> None:
    if audio_source == "generated_ambient_fallback":
        bed_volume = "0.18"
    elif audio_source == "sampled_violin_cc0":
        bed_volume = "0.24"
    else:
        bed_volume = "0.26"
    audio_filter = (
        f"[1:a]volume={bed_volume}[bed];"
        "[2:a]highpass=f=75,acompressor=threshold=-20dB:ratio=3:attack=12:release=180,"
        "volume=1.15,asplit=2[voice_sc][voice_mix];"
        "[bed][voice_sc]sidechaincompress=threshold=0.035:ratio=10:attack=18:release=620:knee=4:makeup=1[duckedbed];"
        "[duckedbed][voice_mix]amix=inputs=2:duration=longest:dropout_transition=1,"
        "loudnorm=I=-16:TP=-1.5:LRA=11,"
        "afade=t=in:st=0:d=0.5,afade=t=out:st=22:d=2[aout]"
    )
    _run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(video_only),
        "-stream_loop", "-1", "-i", str(soundtrack),
        "-i", str(narration),
        "-map", "0:v:0",
        "-filter_complex", audio_filter, "-map", "[aout]",
        "-t", "24", "-vf", "format=yuv420p",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart", str(target),
    ])


def build_prototype(package_dir: Path, output_dir: Path, fps: int = 25) -> dict:
    package_dir = package_dir.resolve()
    output_dir = output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)

    plan_path = package_dir / "creative_plan.json"
    metadata_path = package_dir / "stage.json"
    soundtrack_path = package_dir / "soundtrack.wav"
    for required in (plan_path, metadata_path, soundtrack_path):
        if not required.is_file():
            raise RuntimeError(f"Prepared package is missing {required.name}.")

    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    if len(plan.get("scenes", [])) != 3:
        raise RuntimeError("The V3 prototype needs exactly three prepared scene images.")
    image_paths = [package_dir / f"scene-{i}.jpg" for i in (1, 2, 3)]
    for image in image_paths:
        if not image.is_file():
            raise RuntimeError(f"Prepared scene image is missing: {image.name}")

    script = str(plan.get("narration_script") or "").strip()
    if not script:
        raise RuntimeError("The prepared story has no narration script.")

    # Regenerate the same approved script once so Kokoro can return its native
    # per-word timing objects together with this exact audio file.
    narration_path, narration_info = synthesize_voiceover(
        script, output_dir / "narration-v3.wav"
    )
    word_cues = sorted(
        narration_info.get("word_cues", []),
        key=lambda cue: (float(cue.get("start", 0)), float(cue.get("end", 0))),
    )
    minimum_words = max(10, int(narration_info.get("word_count", 0) * 0.60))
    if len(word_cues) < minimum_words:
        raise RuntimeError(
            "Kokoro did not return enough native word timings for a reliable word-synced preview "
            f"({len(word_cues)} timings; expected at least {minimum_words}). "
            "The renderer will not invent timing estimates."
        )
    if narration_info.get("word_timing_method") != "kokoro_predicted_phoneme_durations":
        raise RuntimeError("Word timing method was not the native Kokoro duration output.")

    timeline = pipeline.scene_durations_from_narration(narration_info)
    scenes = []
    start = 0.0
    for index, (scene, image_path, scene_duration) in enumerate(
        zip(plan["scenes"], image_paths, timeline)
    ):
        scenes.append({
            "start": round(start, 3),
            "duration": round(float(scene_duration), 3),
            "caption": str(scene.get("caption") or ""),
            "graphic_label": str(scene.get("graphic_label") or ""),
            "graphic_detail": str(scene.get("graphic_detail") or ""),
            "comparison": scene.get("comparison"),
            "image_b64": base64.b64encode(image_path.read_bytes()).decode("ascii"),
        })
        start += float(scene_duration)

    input_path = output_dir / "renderer-input.json"
    input_path.write_text(json.dumps({
        "title": str(plan.get("title") or "Violin Prince Short"),
        "topic": str(plan.get("topic") or ""),
        "width": 720,
        "height": 1280,
        "fps": int(fps),
        "duration_seconds": 24,
        "scenes": scenes,
        "word_cues": word_cues,
    }, ensure_ascii=False), encoding="utf-8")

    # Produce a V2 FFmpeg baseline using the same new narration/audio/images.
    # This is for side-by-side evaluation only; it does not replace production.
    baseline_video, baseline_quality = pipeline.render(
        plan,
        soundtrack_path.read_bytes(),
        narration_path,
        narration_info,
        image_paths=image_paths,
        audio_source=str(metadata.get("asset", {}).get("audio_source", "generated_ambient_fallback")),
    )
    baseline_path = output_dir / "ffmpeg-baseline.mp4"
    shutil.copy2(baseline_video, baseline_path)

    silent_path = output_dir / "html-render-silent.mp4"
    final_path = output_dir / "html-motion-prototype.mp4"
    renderer_script = ENGINE.parent / "motion-prototype" / "render.mjs"
    if not renderer_script.is_file():
        raise RuntimeError("The isolated HTML renderer script is missing.")
    if not shutil.which("node"):
        raise RuntimeError("Node.js is required for the isolated HTML renderer.")
    _run(["node", str(renderer_script), str(input_path), str(silent_path)])

    _mix_audio(
        silent_path,
        soundtrack_path,
        narration_path,
        final_path,
        str(metadata.get("asset", {}).get("audio_source", "generated_ambient_fallback")),
    )
    prototype_quality = pipeline.validate_final_video(final_path)
    prototype_quality.update({
        "renderer": "HTML Canvas + Playwright + FFmpeg",
        "word_timing_method": narration_info["word_timing_method"],
        "word_timing_count": len(word_cues),
        "caption_animation_presets": ["slide", "rise", "snap", "pop", "impact"],
        "animated_infographics": True,
        "comparison_component": "conditional_on_explicit_scene_comparison_data",
        "publishing_enabled": False,
        "creative_quality_version": 5,
    })
    report = {
        "status": "prototype_rendered",
        "production_renderer_changed": False,
        "publishing_enabled": False,
        "narration": {
            "engine": narration_info.get("engine"),
            "voice": narration_info.get("voice"),
            "word_count": narration_info.get("word_count"),
            "word_timing_count": len(word_cues),
            "word_timing_method": narration_info.get("word_timing_method"),
        },
        "ffmpeg_baseline": {
            "file": baseline_path.name,
            "width": baseline_quality.get("width"),
            "height": baseline_quality.get("height"),
            "duration_seconds": baseline_quality.get("duration_seconds"),
            "file_size_bytes": baseline_quality.get("file_size_bytes"),
        },
        "html_motion_prototype": {
            "file": final_path.name,
            "quality": prototype_quality,
        },
        "notes": [
            "The existing V2 FFmpeg renderer remains the production renderer.",
            "Both videos use the same prepared story, three scene images, narration take and soundtrack.",
            "The HTML prototype is an evaluation path only; no publishing action is called.",
            "Comparison graphics appear only when the scene plan supplies both sides explicitly.",
        ],
    }
    (output_dir / "v3-comparison-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    input_path.unlink(missing_ok=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Render the isolated Violin Prince V3 HTML motion prototype.")
    parser.add_argument("--package", type=Path, default=Path("work/package"))
    parser.add_argument("--output", type=Path, default=Path("work/output/motion-prototype"))
    parser.add_argument("--fps", type=int, default=25)
    args = parser.parse_args()
    if not 12 <= args.fps <= 30:
        raise ValueError("Prototype FPS must be between 12 and 30.")
    report = build_prototype(args.package, args.output, args.fps)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"V3 prototype failed safely: {exc}", file=sys.stderr)
        raise SystemExit(1)
