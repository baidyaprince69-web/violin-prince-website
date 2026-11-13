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



def _extract_final_review_frames(video_path: Path, output_dir: Path,
                                 sample_times: tuple[float, ...] = (1.5, 2.5, 7.5, 13.5, 19.5)) -> list[dict]:
    """Decode review frames from the final audio-muxed MP4, not only the pre-encode canvas."""
    output_dir.mkdir(parents=True, exist_ok=True)
    frames = []
    for value in sample_times:
        stamp = str(value).replace(".", "p")
        target = output_dir / f"final-frame-{stamp}s.png"
        _run([
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", str(value), "-i", str(video_path), "-frames:v", "1",
            "-q:v", "2", str(target),
        ])
        if not target.is_file() or target.stat().st_size < 1000:
            raise RuntimeError(f"Final encoded frame could not be verified at {value:.1f}s.")
        frames.append({"time_seconds": value, "file": target.name, "size_bytes": target.stat().st_size})
    return frames


def _music_energy_samples(path: Path, step_ms: int = 50) -> list[float]:
    """Create a compact RMS envelope so Canvas motion follows the actual music bed."""
    import numpy as np
    import soundfile as sf

    audio, sample_rate = sf.read(str(path), dtype="float32", always_2d=True)
    if audio.size == 0 or sample_rate <= 0:
        return [0.0] * 20
    mono = np.mean(audio, axis=1)
    block = max(1, int(sample_rate * step_ms / 1000))
    energies = []
    for start in range(0, len(mono), block):
        segment = mono[start:start + block]
        if segment.size:
            energies.append(float(np.sqrt(np.mean(np.square(segment), dtype=np.float64))))
    values = np.asarray(energies, dtype=np.float32)
    if values.size == 0:
        return [0.0] * 20
    floor = float(np.percentile(values, 12))
    ceiling = float(np.percentile(values, 94))
    if ceiling <= floor + 1e-6:
        normalised = np.zeros_like(values)
    else:
        normalised = np.clip((values - floor) / (ceiling - floor), 0.0, 1.0)
    if normalised.size >= 3:
        normalised = np.convolve(normalised, np.asarray([0.2, 0.6, 0.2]), mode="same")
    return [round(float(value), 4) for value in normalised]


def _story_font(size: int, bold: bool = False):
    from PIL import ImageFont
    candidates = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Bold.ttf" if bold else
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
    ]
    for candidate in candidates:
        try:
            return ImageFont.truetype(candidate, size=size)
        except OSError:
            continue
    return ImageFont.load_default()


def _draw_second_story_art(destination: Path, scene_index: int) -> None:
    """Draw original warm-toned science-story plates for the second renderer test."""
    from PIL import Image, ImageDraw, ImageFilter

    width, height = 720, 1280
    image = Image.new("RGB", (width, height))
    draw = ImageDraw.Draw(image)
    for y in range(height):
        t = y / max(1, height - 1)
        colour = (
            int(17 + 29 * t),
            int(10 + 9 * t),
            int(10 + 5 * t),
        )
        draw.line((0, y, width, y), fill=colour)

    glow_layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    glow_draw = ImageDraw.Draw(glow_layer)
    glow_draw.ellipse((115, 260, 690, 930), fill=(198, 91, 48, 58))
    glow_draw.ellipse((250, 430, 590, 770), fill=(244, 185, 111, 34))
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(92))
    image = Image.alpha_composite(image.convert("RGBA"), glow_layer)
    draw = ImageDraw.Draw(image)

    # Fine editorial texture and warm orbital lines.
    for index in range(38):
        x = (index * 97 + 31) % width
        y = (index * 181 + 63) % height
        radius = 1 + (index % 3)
        draw.ellipse((x-radius, y-radius, x+radius, y+radius),
                     fill=(236, 190, 137, 78))
    for ring in range(4):
        draw.ellipse((95-ring*22, 300-ring*34, 650+ring*22, 990+ring*34),
                     outline=(224, 155, 101, 35), width=2)

    gold = (239, 193, 137, 230)
    ivory = (255, 239, 218, 225)
    copper = (194, 103, 70, 225)

    if scene_index == 0:
        # Macro view: long strings, bow hair, and the point of contact.
        for string in range(4):
            x = 230 + string * 72
            draw.line((x, 180, x+10, 1030), fill=(219, 190, 151, 170), width=4)
            draw.line((x+3, 180, x+13, 1030), fill=(255, 239, 218, 70), width=1)
        draw.rounded_rectangle((142, 180, 574, 1045), radius=120,
                               outline=(191, 111, 77, 135), width=5)
        draw.line((70, 640, 650, 690), fill=ivory, width=10)
        draw.line((72, 654, 648, 704), fill=copper, width=3)
        draw.ellipse((310, 630, 390, 710), outline=gold, width=4)
        draw.ellipse((327, 647, 373, 693), outline=ivory, width=2)
    elif scene_index == 1:
        # Bridge and body: vibration passes into the hollow resonant body.
        draw.ellipse((78, 315, 666, 1120), outline=(207, 132, 88, 205), width=10)
        draw.ellipse((130, 370, 615, 1060), outline=(240, 190, 132, 90), width=3)
        draw.polygon([(315, 485), (405, 485), (440, 815), (280, 815)],
                     fill=(166, 93, 59, 205), outline=ivory)
        for wave in range(5):
            x = 360 + wave * 24
            draw.arc((x-90, 580-wave*25, x+170, 860+wave*25),
                     start=255, end=105, fill=(239, 193, 137, max(38, 140-wave*18)), width=4)
        draw.line((120, 560, 600, 560), fill=gold, width=4)
        draw.line((120, 750, 600, 750), fill=copper, width=3)
    else:
        # Full instrument silhouette and expanding acoustic rings.
        draw.ellipse((230, 500, 520, 1010), fill=(116, 54, 37, 230),
                     outline=(238, 180, 120, 235), width=8)
        draw.ellipse((252, 550, 498, 955), outline=(255, 229, 190, 120), width=3)
        draw.polygon([(338, 170), (414, 170), (430, 625), (322, 625)],
                     fill=(104, 51, 37, 245), outline=gold)
        draw.ellipse((315, 110, 440, 245), outline=gold, width=7)
        draw.ellipse((345, 140, 410, 210), outline=ivory, width=4)
        draw.line((354, 195, 354, 950), fill=(246, 219, 178, 200), width=3)
        draw.line((378, 195, 378, 950), fill=(246, 219, 178, 170), width=3)
        draw.line((402, 195, 402, 950), fill=(246, 219, 178, 150), width=3)
        for ring in range(5):
            box = (65-ring*20, 525-ring*38, 650+ring*20, 970+ring*38)
            draw.arc(box, start=205, end=155, fill=(242, 188, 127, 155-ring*20), width=4)
            draw.arc(box, start=25, end=335, fill=(205, 111, 75, 125-ring*15), width=3)

    # A clean lower vignette keeps the word-level captions readable.
    vignette = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    vignette_draw = ImageDraw.Draw(vignette)
    vignette_draw.rectangle((0, 900, width, height), fill=(8, 6, 5, 90))
    vignette = vignette.filter(ImageFilter.GaussianBlur(42))
    image = Image.alpha_composite(image, vignette)
    image.convert("RGB").save(destination, "JPEG", quality=91, optimize=True)


def _build_second_story_package(source_package: Path, output_root: Path) -> Path:
    """Prepare a genuinely different 44-word educational story for consistency testing."""
    package = output_root / "second-story-package"
    package.mkdir(parents=True, exist_ok=True)

    script = (
        "Rosin gives the bow hair the grip to catch a violin string. "
        "As the bow travels, the string rapidly alternates between sticking and slipping, "
        "setting it into vibration. The bridge carries that motion into the hollow body, "
        "which moves the air and sends sound outward."
    )
    scenes = [
        {
            "image_prompt": "Macro editorial illustration of violin strings and bow contact, warm burgundy and amber lighting",
            "caption": "Rosin gives the bow its grip",
            "graphic_label": "BOW + ROSIN",
            "graphic_detail": "Friction helps the bow hair catch the string",
        },
        {
            "image_prompt": "Detailed violin bridge and resonant wooden body, glowing vibration waves, warm copper lighting",
            "caption": "The bridge carries the vibration",
            "graphic_label": "VIBRATION TRANSFERS",
            "graphic_detail": "The bridge passes string motion into the body",
        },
        {
            "image_prompt": "Elegant violin silhouette in a dark concert hall with expanding acoustic wave rings",
            "caption": "The body moves the air",
            "graphic_label": "SOUND MOVES OUTWARD",
            "graphic_detail": "The hollow body helps project the sound",
        },
    ]
    plan = {
        "title": "How a Violin Turns Motion into Music",
        "topic": "A different educational story about rosin, bow friction, string vibration, the bridge and resonance",
        "narration_script": script,
        "visual_motif": "bow-performance",
        "scenes": scenes,
    }
    source_metadata = json.loads((source_package / "stage.json").read_text(encoding="utf-8"))
    audio_source = str(source_metadata.get("asset", {}).get("audio_source", "generated_ambient_fallback"))
    metadata = {"asset": {"audio_source": audio_source}, "test_variant": "second-story-consistency"}
    (package / "creative_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    (package / "stage.json").write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8")

    source_soundtrack = source_package / "soundtrack.wav"
    if not source_soundtrack.is_file():
        raise RuntimeError("The second-story test needs the prepared soundtrack.wav file.")
    shutil.copy2(source_soundtrack, package / "soundtrack.wav")
    for index in range(1, 4):
        _draw_second_story_art(package / f"scene-{index}.jpg", index-1)
    return package


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
        "narration_text": script,
        "visual_motif": str(plan.get("visual_motif") or "bow-performance"),
        "width": 720,
        "height": 1280,
        "fps": int(fps),
        "duration_seconds": 24,
        "scenes": scenes,
        "word_cues": word_cues,
        "music_energy": _music_energy_samples(soundtrack_path),
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
    final_review_frames = _extract_final_review_frames(
        final_path, output_dir / "final-encoded-qa-frames"
    )
    prototype_quality = pipeline.validate_final_video(final_path)
    prototype_quality.update({
        "renderer": "HTML Canvas + Playwright + FFmpeg",
        "word_timing_method": narration_info["word_timing_method"],
        "word_timing_count": len(word_cues),
        "caption_animation_presets": [
            "bounce", "serif", "outline", "underline", "tilt", "typewriter", "glow", "editorial", "impact"
        ],
        "typography_families": ["bold sans", "editorial serif", "outlined impact", "typewriter reveal"],
        "background_palette": "warm charcoal, antique gold and copper; no blue information-card background",
        "camera_motion": "scene-specific camera arcs: hook push-in, performance-detail macro push, and gentle payoff pull-back; animated atmosphere and directional light sweeps",
        "caption_logic": "phrase-aware semantic styles with key-term overrides rather than cycling by word index",
        "infographic_reveal": "staged label, headline, detail, connector, nodes and chart reveals",
        "bow_visualization": "localized alternating bow-path highlight in the performance-detail scene; stylized overlay, not anatomically tracked hand animation",
        "music_reactive_bow_visualisation": True,
        "animated_infographics": True,
        "comparison_component": "conditional_on_explicit_scene_comparison_data",
        "publishing_enabled": False,
        "creative_quality_version": 7,
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
            "text_renderer": "SVG text overlay over the animated Canvas scene",
            "final_encoded_review_frames": final_review_frames,
        },
        "notes": [
            "The existing V2 FFmpeg renderer remains the production renderer.",
            "Both videos use the same prepared story, three scene images, narration take and soundtrack.",
            "The HTML prototype is an evaluation path only; no publishing action is called.",
            "Comparison graphics appear only when the scene plan supplies both sides explicitly.",
            "The HTML renderer now uses a warm charcoal, gold and copper palette with no large blue card.",
            "Nine caption treatments are selected by phrase meaning and key-word emphasis, not a simple word-index cycle.",
            "Infographic text, connectors, nodes and chart details reveal in separate staged beats.",
            "The bow-path highlight is localized to the performance-detail scene and remains a stylized overlay, not tracked hand animation.",
            "Image prompts use warm walnut, charcoal, oxblood, copper and antique-gold art direction, with performance-specific bow and hand anatomy constraints.",
            "Atmosphere, animated infographic details, scene light sweeps and bow/string motion are rendered continuously.",
            "The bow/string visual motif responds to a sampled RMS envelope from the soundtrack.",
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
    primary_report = build_prototype(args.package, args.output, args.fps)
    second_package = _build_second_story_package(args.package.resolve(), args.output.resolve())
    second_output = args.output / "second-story"
    second_report = build_prototype(second_package, second_output, args.fps)
    summary = {
        "status": "two_story_prototypes_rendered",
        "production_renderer_changed": False,
        "publishing_enabled": False,
        "primary_story": primary_report,
        "second_story_consistency_test": second_report,
        "second_story_title": "How a Violin Turns Motion into Music",
        "second_story_package": str(second_package),
        "notes": [
            "Both stories use the same isolated V3 HTML renderer and native Kokoro word timing.",
            "The second story uses its own narration script and original warm-toned illustration plates.",
            "V2 remains the production renderer; this workflow only creates review artifacts.",
        ],
    }
    summary_path = args.output / "two-story-test-report.json"
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"V3 prototype failed safely: {exc}", file=sys.stderr)
        raise SystemExit(1)
