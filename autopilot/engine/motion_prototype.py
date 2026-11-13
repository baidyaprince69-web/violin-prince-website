#!/usr/bin/env python3
"""Build an isolated HTML-renderer V3 preview beside the unchanged V2 renderer."""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

ENGINE = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE))

from voiceover import synthesize_voiceover
from quality_control import QualityGateError, run_quality_gate
import run as pipeline


def _run(command: list[str]) -> None:
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        tail = (result.stderr or result.stdout or "")[-4000:]
        raise RuntimeError(f"Command failed ({result.returncode}): {' '.join(command[:4])}\n{tail}")


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _fingerprint(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _read_json(path: Path) -> dict | None:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
        return value if isinstance(value, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _write_json_atomic(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _record_checkpoint(manifest_path: Path, manifest: dict, stage: str, status: str, **details) -> None:
    manifest.setdefault("stages", {})[stage] = {
        "status": status,
        "updated_at": datetime.now(timezone.utc).isoformat(),
        **details,
    }
    manifest["updated_at"] = datetime.now(timezone.utc).isoformat()
    _write_json_atomic(manifest_path, manifest)


def _validate_approved_visual_package(plan: dict, metadata: dict, image_paths: list[Path]) -> None:
    """Reject missing, altered or unreviewed scene art before any video rendering."""
    from PIL import Image

    required_status = "all_scenes_and_storyboard_passed_ai_review_human_review_still_required"
    if metadata.get("stage") != "visuals_ready" or metadata.get("visual_review_status") != required_status:
        raise RuntimeError("Visual package has not passed the required scene and storyboard AI reviews.")
    assets = metadata.get("visual_assets")
    if not isinstance(assets, list) or len(assets) != 3:
        raise RuntimeError("Visual package must contain three scene-by-scene review records.")
    storyboard = metadata.get("storyboard_review")
    if (
        not isinstance(storyboard, dict)
        or storyboard.get("passed") is not True
        or int(storyboard.get("score", 0)) < pipeline.MIN_IMAGE_QA_SCORE
    ):
        raise RuntimeError("Storyboard continuity review did not meet the minimum passing score.")

    expected_plan_hash = _fingerprint(plan)
    for index, (record, image_path) in enumerate(zip(assets, image_paths), start=1):
        if not isinstance(record, dict):
            raise RuntimeError(f"Scene {index} has no visual-review record.")
        review = record.get("visual_review")
        if (
            not isinstance(review, dict)
            or review.get("passed") is not True
            or int(review.get("score", 0)) < pipeline.MIN_IMAGE_QA_SCORE
        ):
            raise RuntimeError(f"Scene {index} did not pass AI visual review.")
        if record.get("mode") != "cloudflare_flux_portrait_extended":
            raise RuntimeError(f"Scene {index} uses an unapproved visual-generation mode.")
        expected_hash = str(record.get("sha256") or "")
        if not expected_hash or _sha256_file(image_path) != expected_hash:
            raise RuntimeError(f"Scene {index} changed after visual approval; regenerate that scene only.")
        recorded_plan_hash = str(record.get("plan_sha256") or "")
        if recorded_plan_hash and recorded_plan_hash != expected_plan_hash:
            raise RuntimeError(f"Scene {index} was approved against a different creative plan.")
        try:
            with Image.open(image_path) as image:
                image.verify()
            with Image.open(image_path) as image:
                if image.size != (720, 1280):
                    raise RuntimeError(
                        f"Scene {index} is {image.size[0]}x{image.size[1]}, not 720x1280."
                    )
        except RuntimeError:
            raise
        except Exception as exc:
            raise RuntimeError(f"Scene {index} is not a valid readable image: {exc}") from exc


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
        "volume=1.15,asplit=2[voice_sc_raw][voice_mix];"
        "[voice_sc_raw]apad=whole_dur=24[voice_sc];"
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
    _validate_approved_visual_package(plan, metadata, image_paths)

    script = str(plan.get("narration_script") or "").strip()
    if not script:
        raise RuntimeError("The prepared story has no narration script.")

    # The checkpoint fingerprint binds every expensive stage to these exact
    # source files. A changed plan, soundtrack or scene image invalidates only
    # the downstream stages that depend on it.
    package_fingerprint = _fingerprint({
        str(path.name): _sha256_file(path)
        for path in (plan_path, metadata_path, soundtrack_path, *image_paths)
    })
    manifest_path = output_dir / "recovery-manifest.json"
    recovery = _read_json(manifest_path)
    if not isinstance(recovery, dict) or recovery.get("package_fingerprint") != package_fingerprint:
        recovery = {
            "schema_version": 1,
            "package_fingerprint": package_fingerprint,
            "publishing_enabled": False,
            "stages": {},
        }
    _write_json_atomic(manifest_path, recovery)

    # Stage 1 — narration. Reuse the exact audio and native word timings when
    # the script hash and audio hash match; only retry Kokoro if this stage failed.
    narration_path = output_dir / "narration-v3.wav"
    narration_cache_path = output_dir / "narration-v3-cache.json"
    script_hash = hashlib.sha256(script.encode("utf-8")).hexdigest()
    narration_cache = _read_json(narration_cache_path)
    narration_info = None
    narration_reused = False
    if (
        narration_path.is_file()
        and isinstance(narration_cache, dict)
        and narration_cache.get("script_sha256") == script_hash
        and narration_cache.get("audio_sha256") == _sha256_file(narration_path)
        and isinstance(narration_cache.get("narration_info"), dict)
    ):
        narration_info = narration_cache["narration_info"]
        narration_reused = True
        print("Recovery: reusing narration WAV and word timings; Kokoro will not run again.", flush=True)
    else:
        last_error = None
        for narration_attempt in range(1, 3):
            try:
                narration_path, narration_info = synthesize_voiceover(script, narration_path)
                if not pipeline._valid_wav_checkpoint(narration_path):
                    raise RuntimeError("Kokoro returned an invalid or empty narration WAV.")
                _write_json_atomic(narration_cache_path, {
                    "script_sha256": script_hash,
                    "audio_sha256": _sha256_file(narration_path),
                    "narration_info": narration_info,
                    "attempts": narration_attempt,
                })
                break
            except Exception as exc:
                last_error = exc
                if narration_attempt >= 2:
                    raise
                print(f"Recovery: narration stage failed once; retrying only narration: {exc}", flush=True)
        if narration_info is None:
            raise RuntimeError(f"Narration stage failed: {last_error}")
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
    _record_checkpoint(
        manifest_path, recovery, "narration", "reused" if narration_reused else "complete",
        file=narration_path.name,
        audio_sha256=_sha256_file(narration_path),
        word_timing_count=len(word_cues),
    )

    timeline = pipeline.scene_durations_from_narration(narration_info)
    scenes = []
    start = 0.0
    for scene, image_path, scene_duration in zip(plan["scenes"], image_paths, timeline):
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

    # Stage 2 — baseline. A valid cached baseline is re-probed before reuse.
    baseline_path = output_dir / "ffmpeg-baseline.mp4"
    baseline_cache_path = output_dir / "ffmpeg-baseline-cache.json"
    baseline_quality_report = output_dir / "baseline-quality-control-report.json"
    baseline_fingerprint = _fingerprint({
        "package": package_fingerprint,
        "narration": _sha256_file(narration_path),
        "fps": fps,
    })
    baseline_cache = _read_json(baseline_cache_path)
    baseline_quality = None
    baseline_reused = False
    if (
        baseline_path.is_file()
        and isinstance(baseline_cache, dict)
        and baseline_cache.get("input_fingerprint") == baseline_fingerprint
        and baseline_cache.get("output_sha256") == _sha256_file(baseline_path)
    ):
        try:
            baseline_quality = pipeline.validate_final_video(
                baseline_path, narration_info, report_path=baseline_quality_report
            )
            baseline_reused = True
        except pipeline.PipelineError:
            baseline_quality = None
    if baseline_quality is None:
        baseline_video, _baseline_quality = pipeline.render(
            plan,
            soundtrack_path.read_bytes(),
            narration_path,
            narration_info,
            image_paths=image_paths,
            audio_source=str(metadata.get("asset", {}).get("audio_source", "generated_ambient_fallback")),
        )
        shutil.copy2(baseline_video, baseline_path)
        baseline_quality = pipeline.validate_final_video(
            baseline_path, narration_info, report_path=baseline_quality_report
        )
        _write_json_atomic(baseline_cache_path, {
            "input_fingerprint": baseline_fingerprint,
            "output_sha256": _sha256_file(baseline_path),
        })
    _record_checkpoint(
        manifest_path, recovery, "ffmpeg_baseline", "reused" if baseline_reused else "complete",
        file=baseline_path.name,
        output_sha256=_sha256_file(baseline_path),
        quality_gate="passed",
    )

    silent_path = output_dir / "html-render-silent.mp4"
    final_path = output_dir / "html-motion-prototype.mp4"
    text_audit_path = output_dir / "final-text-frame-audit.json"
    silent_cache_path = output_dir / "html-render-cache.json"
    renderer_script = ENGINE.parent / "motion-prototype" / "render.mjs"
    if not renderer_script.is_file():
        raise RuntimeError("The isolated HTML renderer script is missing.")
    if not shutil.which("node"):
        raise RuntimeError("Node.js is required for the isolated HTML renderer.")

    renderer_fingerprint = _fingerprint({
        "renderer_input": _sha256_file(input_path),
        "renderer_script": _sha256_file(renderer_script),
    })
    silent_cache = _read_json(silent_cache_path)
    silent_reused = False

    def validate_silent() -> dict:
        return run_quality_gate(
            silent_path,
            report_path=output_dir / "silent-quality-control-report.json",
            audio_required=False,
            expected_fps=float(fps),
            frame_rate_tolerance=0.5,
            narration_cues=word_cues,
            word_count=int(narration_info.get("word_count", 0)),
            require_word_timing=True,
            text_audit_path=text_audit_path,
        )

    if (
        silent_path.is_file()
        and isinstance(silent_cache, dict)
        and silent_cache.get("input_fingerprint") == renderer_fingerprint
        and silent_cache.get("output_sha256") == _sha256_file(silent_path)
        and text_audit_path.is_file()
    ):
        try:
            validate_silent()
            silent_reused = True
        except QualityGateError:
            silent_reused = False

    renderer_attempts = 0

    def render_silent_stage() -> None:
        nonlocal renderer_attempts, silent_cache
        last_error = None
        while renderer_attempts < 2:
            renderer_attempts += 1
            try:
                _run(["node", str(renderer_script), str(input_path), str(silent_path)])
                validate_silent()
                silent_cache = {
                    "input_fingerprint": renderer_fingerprint,
                    "output_sha256": _sha256_file(silent_path),
                    "attempts": renderer_attempts,
                    "text_audit": text_audit_path.name,
                }
                _write_json_atomic(silent_cache_path, silent_cache)
                _record_checkpoint(
                    manifest_path, recovery, "html_render", "complete",
                    file=silent_path.name,
                    output_sha256=_sha256_file(silent_path),
                    attempts=renderer_attempts,
                    text_audit="passed",
                )
                return
            except QualityGateError as exc:
                last_error = exc
                _record_checkpoint(
                    manifest_path, recovery, "html_render", "rejected",
                    failed_checks=exc.report.get("failed_checks", []),
                    retry_stage=exc.retry_stage,
                    attempts=renderer_attempts,
                )
                if exc.retry_stage != "video_render" or renderer_attempts >= 2:
                    raise
                print("Recovery: V3 video/text quality gate rejected the silent render; rerendering only the HTML video stage.", flush=True)
            except Exception as exc:
                last_error = exc
                if renderer_attempts >= 2:
                    raise
                print(f"Recovery: HTML render stage failed; retrying only HTML rendering: {exc}", flush=True)
        raise RuntimeError(f"HTML render stage failed after targeted retries: {last_error}")

    if not silent_reused:
        render_silent_stage()
    else:
        _record_checkpoint(
            manifest_path, recovery, "html_render", "reused",
            file=silent_path.name,
            output_sha256=_sha256_file(silent_path),
            text_audit="passed",
        )
        print("Recovery: reusing the verified silent V3 render and its encoded-frame text audit.", flush=True)

    audio_source = str(metadata.get("asset", {}).get("audio_source", "generated_ambient_fallback"))
    mix_fingerprint = _fingerprint({
        "silent_video": _sha256_file(silent_path),
        "soundtrack": _sha256_file(soundtrack_path),
        "narration": _sha256_file(narration_path),
        "audio_source": audio_source,
    })
    mix_cache_path = output_dir / "final-mix-cache.json"
    mix_cache = _read_json(mix_cache_path)
    prototype_quality = None
    mix_reused = False
    if (
        final_path.is_file()
        and isinstance(mix_cache, dict)
        and mix_cache.get("input_fingerprint") == mix_fingerprint
        and mix_cache.get("output_sha256") == _sha256_file(final_path)
    ):
        try:
            prototype_quality = pipeline.validate_final_video(
                final_path,
                narration_info,
                text_audit_path=text_audit_path,
                report_path=output_dir / "quality-control-report.json",
            )
            mix_reused = True
        except pipeline.PipelineError as exc:
            if getattr(exc, "retry_stage", "none") == "video_render":
                render_silent_stage()
                mix_fingerprint = _fingerprint({
                    "silent_video": _sha256_file(silent_path),
                    "soundtrack": _sha256_file(soundtrack_path),
                    "narration": _sha256_file(narration_path),
                    "audio_source": audio_source,
                })
            elif getattr(exc, "retry_stage", "none") != "audio_mix":
                raise
            prototype_quality = None

    mix_attempts = 0
    while prototype_quality is None:
        if mix_attempts >= 2:
            raise RuntimeError("Final audio mix did not pass the quality gate after one targeted retry.")
        mix_attempts += 1
        _mix_audio(
            silent_path,
            soundtrack_path,
            narration_path,
            final_path,
            audio_source,
        )
        try:
            prototype_quality = pipeline.validate_final_video(
                final_path,
                narration_info,
                text_audit_path=text_audit_path,
                report_path=output_dir / "quality-control-report.json",
            )
        except pipeline.PipelineError as exc:
            retry_stage = getattr(exc, "retry_stage", "none")
            _record_checkpoint(
                manifest_path, recovery, "quality_control", "rejected",
                failed_checks=getattr(exc, "quality_report", {}).get("failed_checks", []),
                retry_stage=retry_stage,
                audio_mix_attempt=mix_attempts,
            )
            if retry_stage == "audio_mix" and mix_attempts < 2:
                print("Recovery: audio-only QC failure; remixing the existing silent video without rerendering visuals or narration.", flush=True)
                continue
            if retry_stage == "video_render" and renderer_attempts < 2:
                print("Recovery: video/text QC failure; rerendering only the HTML stage, then rebuilding its final audio mux.", flush=True)
                render_silent_stage()
                mix_fingerprint = _fingerprint({
                    "silent_video": _sha256_file(silent_path),
                    "soundtrack": _sha256_file(soundtrack_path),
                    "narration": _sha256_file(narration_path),
                    "audio_source": audio_source,
                })
                continue
            raise
        _write_json_atomic(mix_cache_path, {
            "input_fingerprint": mix_fingerprint,
            "output_sha256": _sha256_file(final_path),
            "attempts": mix_attempts,
        })

    _record_checkpoint(
        manifest_path, recovery, "audio_mix", "reused" if mix_reused else "complete",
        file=final_path.name,
        output_sha256=_sha256_file(final_path),
        attempts=mix_attempts,
    )
    _record_checkpoint(
        manifest_path, recovery, "quality_control", "passed",
        report="quality-control-report.json",
        checks_passed=prototype_quality.get("quality_gate_checks_passed"),
        checks_total=prototype_quality.get("quality_gate_checks_total"),
    )

    final_review_frames = _extract_final_review_frames(
        final_path, output_dir / "final-encoded-qa-frames"
    )
    prototype_quality.update({
        "renderer": "HTML Canvas + Playwright + FFmpeg",
        "visual_review_status": metadata.get("visual_review_status", "not_reviewed"),
        "visual_review_model": metadata.get("visual_review_model", ""),
        "visual_asset_reviews": [
            item.get("visual_review", {}) for item in metadata.get("visual_assets", [])
            if isinstance(item, dict)
        ],
        "storyboard_review": metadata.get("storyboard_review", {}),
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
        "visual_review_status": metadata.get("visual_review_status", "not_reviewed"),
        "visual_asset_reviews": [
            item.get("visual_review", {}) for item in metadata.get("visual_assets", [])
            if isinstance(item, dict)
        ],
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
            "quality_gate_status": baseline_quality.get("quality_gate_status"),
        },
        "html_motion_prototype": {
            "file": final_path.name,
            "quality": prototype_quality,
            "text_renderer": "SVG text overlay over the animated Canvas scene",
            "final_encoded_review_frames": final_review_frames,
        },
        "recovery": {
            "manifest": manifest_path.name,
            "narration_reused": narration_reused,
            "baseline_reused": baseline_reused,
            "silent_render_reused": silent_reused,
            "final_mix_reused": mix_reused,
            "renderer_attempts": renderer_attempts,
            "audio_mix_attempts": mix_attempts,
            "stage_status": recovery.get("stages", {}),
        },
        "notes": [
            "The existing V2 FFmpeg renderer remains the production renderer.",
            "Both videos use the same prepared story, three scene images, narration take and soundtrack.",
            "The HTML prototype is an evaluation path only; no publishing action is called.",
            "Comparison graphics appear only when the scene plan supplies both sides explicitly.",
            "The HTML renderer uses a warm charcoal, gold and copper palette.",
            "Nine caption treatments are selected by phrase meaning and key-word emphasis.",
            "Infographic text, connectors, nodes and chart details reveal in separate staged beats.",
            "The bow-path highlight remains a stylized overlay, not tracked hand animation.",
            "The V3 media gate verifies encoded streams, durations, decode integrity, black-frame intervals, loudness, true peak and the final music tail.",
            "The renderer text audit checks sampled final-frame text presence, bounds and word order.",
            "Targeted recovery retries narration, HTML rendering or audio mixing without regenerating already accepted scene images.",
        ],
    }
    (output_dir / "v3-comparison-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    input_path.unlink(missing_ok=True)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Render one isolated Violin Prince V3 HTML motion prototype.")
    parser.add_argument("--package", type=Path, default=Path("work/package"))
    parser.add_argument("--output", type=Path, default=Path("work/output/motion-prototype"))
    parser.add_argument("--fps", type=int, default=25)
    args = parser.parse_args()
    if not 12 <= args.fps <= 30:
        raise ValueError("Prototype FPS must be between 12 and 30.")
    story_report = build_prototype(args.package, args.output, args.fps)
    summary = {
        "status": "single_story_prototype_rendered",
        "production_renderer_changed": False,
        "publishing_enabled": False,
        "story": story_report,
        "notes": [
            "Only the primary prepared story is rendered in this review cycle.",
            "The second story consistency render is intentionally disabled to reduce review time.",
            "The original AI-generated scene images are preserved; no procedural violin macro replacement is applied.",
            "The HTML prototype remains an evaluation path; production V2 is unchanged.",
            "Word captions use native Kokoro duration cues from this exact narration take.",
        ],
    }
    summary_path = args.output / "single-story-test-report.json"
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
