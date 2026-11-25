"""Build preview assets from private creator audio or explicitly synthetic test narration.

Creator audio is referenced in place and marked private in the timeline; it is never
copied into a public artifact by this builder.
"""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter


def _run(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise RuntimeError("Unable to prepare the synthetic composition preview: " + str(detail)[-1800:]) from exc


def _probe_audio(path: Path, label: str, ffprobe: str) -> dict:
    """Reject missing or undecodable creator/test audio before composing a timeline."""
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries",
             "format=duration:stream=codec_type,sample_rate,channels",
             "-of", "json", str(path)],
            check=True, capture_output=True, text=True, timeout=60,
        )
        metadata = json.loads(result.stdout)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} audio could not be decoded: {path.name}") from exc
    stream = next(
        (item for item in metadata.get("streams", []) if item.get("codec_type") == "audio"),
        None,
    )
    if not stream:
        raise RuntimeError(f"{label} input has no audio stream: {path.name}")
    duration = float((metadata.get("format") or {}).get("duration") or 0)
    if duration <= 0:
        raise RuntimeError(f"{label} input has no measurable duration: {path.name}")
    return {
        "duration_seconds": duration,
        "sample_rate": int(stream.get("sample_rate") or 0),
        "channels": int(stream.get("channels") or 0),
    }


def _audio_track_manifest(
    voice_path: Path,
    music_path: Path,
    sfx_path: Path,
    *,
    creator_voice: bool,
    music_source: str,
    voice_source_in_seconds: float = 0.0,
) -> list[dict]:
    """Build audio timeline records while retaining source provenance and privacy."""
    if music_source not in {"cc0_sample", "creator_recording"}:
        raise ValueError("music_source must be cc0_sample or creator_recording")
    voice_type = "creator_recorded_voice" if creator_voice else "synthetic_test_fixture"
    music_type = (
        "creator_recorded_violin" if music_source == "creator_recording" else "cc0_sample"
    )
    return [
        {
            "id": "creator_voice_recording" if creator_voice else "synthetic_voice_preview",
            "role": "voice",
            "path": str(voice_path),
            "start_seconds": 0,
            "end_seconds": 8,
            "source_in_seconds": float(voice_source_in_seconds),
            "gain_db": -2,
            "fade_in_seconds": 0.08,
            "fade_out_seconds": 0.35,
            "private_source": creator_voice,
            "source_type": voice_type,
        },
        {
            "id": "creator_violin_recording" if music_source == "creator_recording" else "sampled_violin_music",
            "role": "music",
            "path": str(music_path),
            "start_seconds": 0,
            "end_seconds": 8,
            "gain_db": -15,
            "loop": music_source == "cc0_sample",
            "fade_in_seconds": 0.25,
            "fade_out_seconds": 0.5,
            "private_source": music_source == "creator_recording",
            "source_type": music_type,
        },
        {
            "id": "transition_whoosh",
            "role": "sfx",
            "path": str(sfx_path),
            "start_seconds": 2.7,
            "end_seconds": 3.4,
            "gain_db": -16,
            "fade_in_seconds": 0.04,
            "fade_out_seconds": 0.2,
            "private_source": False,
            "source_type": "generated_preview_sfx",
        },
    ]


def create_fixture(
    character_video: Path,
    music_wav: Path,
    output_dir: Path,
    *,
    voice_wav: Path | None = None,
    synthetic_voice_for_tests: bool = False,
    music_source: str = "cc0_sample",
    voice_source_in_seconds: float = 0.0,
) -> Path:
    character_video = character_video.resolve(strict=True)
    music_wav = music_wav.resolve(strict=True)
    if (voice_wav is None) == (not synthetic_voice_for_tests):
        raise RuntimeError(
            "Supply --voice-wav for creator audio, or explicitly select "
            "--synthetic-voice-for-tests for automated fixtures."
        )
    if music_source not in {"cc0_sample", "creator_recording"}:
        raise RuntimeError("Music source must be cc0_sample or creator_recording.")
    if not math.isfinite(float(voice_source_in_seconds)) or not 0 <= float(voice_source_in_seconds) <= 600:
        raise RuntimeError("Voice source offset must be between 0 and 600 seconds.")
    output_dir.mkdir(parents=True, exist_ok=True)
    ffprobe = shutil.which("ffprobe")
    ffmpeg = shutil.which("ffmpeg")
    if not ffprobe or not ffmpeg:
        raise RuntimeError("FFprobe and FFmpeg are required to validate and render the preview.")
    music_info = _probe_audio(music_wav, "Music", ffprobe)
    if music_info["duration_seconds"] + 0.02 < 8.0:
        raise RuntimeError("Music audio must cover the full eight-second cinematic preview.")
    creator_voice = voice_wav is not None
    if creator_voice:
        voice = voice_wav.expanduser().resolve(strict=True)
        voice_info = _probe_audio(voice, "Creator voice", ffprobe)
        if voice_info["duration_seconds"] <= float(voice_source_in_seconds):
            raise RuntimeError("Voice source offset is beyond the end of the recording.")
    else:
        voice = output_dir / "synthetic-narration-preview.wav"
        espeak = shutil.which("espeak-ng")
        if not espeak:
            raise RuntimeError("The explicit synthetic test fixture requires espeak-ng.")
        _run([espeak, "-v", "en-us", "-s", "154", "-w", str(voice),
              "Violin Prince. One performance. Five camera shots. A full-body introduction, close details of the violin and bow, the performer, then the final wide shot."])
    if music_source == "creator_recording" and music_info["duration_seconds"] + 0.02 < 8.0:
        raise RuntimeError("Creator violin recording must cover the full performance preview.")
    overlay_dir = output_dir / "overlay-frames"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    overlay = output_dir / "independent-motion-graphic-overlay.mov"
    lighting_dir = output_dir / "lighting-frames"
    particles_dir = output_dir / "particle-frames"
    lighting_dir.mkdir(parents=True, exist_ok=True)
    particles_dir.mkdir(parents=True, exist_ok=True)
    lighting = output_dir / "volumetric-stage-lighting.mov"
    particles = output_dir / "foreground-dust-particles.mov"
    sfx = output_dir / "preview-whoosh.wav"

    # Transparent motion-graphic video: an independent animated layer, not a
    # replacement for or edit of the current character performance.
    width, height, fps, frames = 720, 1280, 25, 200
    for frame in range(frames):
        progress = frame / max(1, frames - 1)
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        phase = 2 * math.pi * progress
        cx, cy = 610, 205
        radius = int(42 + 13 * math.sin(phase * 2))
        alpha = int(110 + 45 * (0.5 + 0.5 * math.sin(phase)))
        draw.ellipse((cx-radius, cy-radius, cx+radius, cy+radius),
                     outline=(236, 202, 140, alpha), width=4)
        sweep_x = int(500 + 150 * progress)
        draw.line((sweep_x, 310, min(width-28, sweep_x+70), 310),
                  fill=(238, 220, 187, int(80 + 80 * progress)), width=3)
        bar_y = int(1160 + 9 * math.sin(phase * 3))
        draw.rounded_rectangle((46, bar_y, 674, bar_y+5), radius=2,
                               fill=(226, 188, 126, 130))
        image.save(overlay_dir / f"frame-{frame:04d}.png")

    _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
          "-framerate", str(fps), "-i", str(overlay_dir / "frame-%04d.png"),
          "-c:v", "qtrle", "-pix_fmt", "argb", str(overlay)])
    # Independent volumetric beams and drifting foreground dust create
    # atmosphere around the existing stage plate without hiding the performer.
    for frame in range(frames):
        progress = frame / max(1, frames - 1)
        phase = 2 * math.pi * progress

        beams = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        beam_draw = ImageDraw.Draw(beams)
        left_top = int(130 + 55 * math.sin(phase))
        right_top = int(590 + 42 * math.sin(phase + 1.2))
        left_base = int(280 + 90 * math.sin(phase + 0.55))
        right_base = int(475 + 75 * math.sin(phase + 1.75))
        beam_draw.polygon(
            [(left_top - 18, -40), (left_top + 18, -40),
             (left_base + 205, 980), (left_base - 175, 980)],
            fill=(232, 203, 151, 33),
        )
        beam_draw.polygon(
            [(right_top - 12, -30), (right_top + 12, -30),
             (right_base + 145, 910), (right_base - 145, 910)],
            fill=(153, 195, 193, 26),
        )
        beam_glow = beams.filter(ImageFilter.GaussianBlur(30))
        beams = Image.alpha_composite(beam_glow, beams)
        beams.save(lighting_dir / f"frame-{frame:04d}.png")

        particles_image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        particle_draw = ImageDraw.Draw(particles_image)
        for index in range(34):
            seed_x = (index * 157 + 47) % width
            seed_y = (index * 239 + 91) % height
            drift_x = 16 * math.sin(phase + index * 0.61)
            drift_y = (progress * (88 + (index % 7) * 13) + 11 * math.sin(phase * 1.6 + index)) % height
            x = int((seed_x + drift_x) % width)
            y = int((seed_y - drift_y) % height)
            radius = 1 + (index % 4)
            alpha = 30 + (index * 17) % 48
            if index % 9 == 0:
                radius += 3
                alpha = 24
            particle_draw.ellipse(
                (x - radius, y - radius, x + radius, y + radius),
                fill=(242, 222, 182, alpha),
            )
        particle_glow = particles_image.filter(ImageFilter.GaussianBlur(5))
        particles_image = Image.alpha_composite(particle_glow, particles_image)
        particles_image.save(particles_dir / f"frame-{frame:04d}.png")

    _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
          "-framerate", str(fps), "-i", str(lighting_dir / "frame-%04d.png"),
          "-c:v", "qtrle", "-pix_fmt", "argb", str(lighting)])
    _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
          "-framerate", str(fps), "-i", str(particles_dir / "frame-%04d.png"),
          "-c:v", "qtrle", "-pix_fmt", "argb", str(particles)])

    _run([ffmpeg, "-y", "-hide_banner", "-loglevel", "error",
          "-f", "lavfi", "-i",
          "anoisesrc=color=pink:duration=0.7:sample_rate=48000:amplitude=0.12",
          "-af", "highpass=f=500,lowpass=f=5500,afade=t=in:st=0:d=0.06,afade=t=out:st=0.35:d=0.35",
          "-c:a", "pcm_s16le", str(sfx)])

    manifest = {
        "schema_version": 1,
        "preview_only": True,
        "publish_enabled": False,
        "title": "Violin Prince — Multi-layer cinematic composition preview",
        "width": width,
        "height": height,
        "fps": fps,
        "duration_seconds": 8,
        "video_layers": [
            {"id": "full_body_character", "kind": "video", "role": "character_performance",
             "path": str(character_video), "start_seconds": 0, "end_seconds": 8,
             "x": 0, "y": 0, "width": width, "height": height, "fit": "contain",
             "camera_framing": "full_body_wide", "camera_move": {"type": "push_in", "intensity": 0.55},
             "shot_id": "shot-01-wide",
             "shot_label": "Full-body establishing performance",
             "grade": {"contrast": 1.08, "saturation": 0.92, "brightness": -0.015, "gamma": 0.98}},
            {"id": "medium_performance_shot", "kind": "video", "role": "character_performance",
             "path": str(character_video), "start_seconds": 1.65, "end_seconds": 3.35,
             "source_in_seconds": 1.6, "x": 0, "y": 0, "width": width, "height": height,
             "fit": "cover", "camera_crop": {"x": 0.09, "y": 0.00, "width": 0.82, "height": 0.82},
             "camera_framing": "medium_performance", "camera_move": {"type": "pan_right", "intensity": 0.58},
             "shot_id": "shot-02-medium",
             "shot_label": "Medium performer and instrument shot",
             "fade_in_seconds": 0.24, "fade_out_seconds": 0.24,
             "grade": {"contrast": 1.08, "saturation": 0.92, "brightness": -0.015, "gamma": 0.98}},
            {"id": "instrument_hands_closeup", "kind": "video", "role": "character_performance",
             "path": str(character_video), "start_seconds": 3.15, "end_seconds": 4.95,
             "source_in_seconds": 3.0, "x": 0, "y": 0, "width": width, "height": height,
             "fit": "cover", "camera_crop": {"x": 0.23, "y": 0.14, "width": 0.68, "height": 0.68},
             "camera_framing": "instrument_hands_close_up", "camera_move": {"type": "push_in", "intensity": 0.85},
             "shot_id": "shot-03-instrument",
             "shot_label": "Violin, bow and hand close-up",
             "fade_in_seconds": 0.22, "fade_out_seconds": 0.22,
             "grade": {"contrast": 1.08, "saturation": 0.92, "brightness": -0.015, "gamma": 0.98}},
            {"id": "face_performance_closeup", "kind": "video", "role": "character_performance",
             "path": str(character_video), "start_seconds": 4.75, "end_seconds": 6.45,
             "source_in_seconds": 4.2, "x": 0, "y": 0, "width": width, "height": height,
             "fit": "cover", "camera_crop": {"x": 0.16, "y": 0.00, "width": 0.68, "height": 0.68},
             "camera_framing": "face_close_up", "camera_move": {"type": "push_in", "intensity": 0.52},
             "shot_id": "shot-04-face",
             "shot_label": "Expression and upper-body close-up",
             "fade_in_seconds": 0.22, "fade_out_seconds": 0.22,
             "grade": {"contrast": 1.08, "saturation": 0.92, "brightness": -0.015, "gamma": 0.98}},
            {"id": "hero_full_body_return", "kind": "video", "role": "character_performance",
             "path": str(character_video), "start_seconds": 6.25, "end_seconds": 8,
             "source_in_seconds": 6.0, "x": 0, "y": 0, "width": width, "height": height,
             "fit": "cover", "camera_crop": {"x": 0.02, "y": 0.02, "width": 0.96, "height": 0.96},
             "camera_framing": "full_body_wide", "camera_move": {"type": "pull_out", "intensity": 0.58},
             "shot_id": "shot-05-hero",
             "shot_label": "Return to full-body hero performance",
             "fade_in_seconds": 0.28,
             "grade": {"contrast": 1.08, "saturation": 0.92, "brightness": -0.015, "gamma": 0.98}},
            {"id": "volumetric_stage_lighting", "kind": "video", "role": "atmospheric_lighting",
             "path": lighting.name, "start_seconds": 0, "end_seconds": 8,
             "x": 0, "y": 0, "width": width, "height": height, "fit": "contain",
             "opacity": 0.38, "fade_in_seconds": 0.4, "fade_out_seconds": 0.6},
            {"id": "foreground_dust_particles", "kind": "video", "role": "foreground_particles",
             "path": particles.name, "start_seconds": 0, "end_seconds": 8,
             "x": 0, "y": 0, "width": width, "height": height, "fit": "contain",
             "opacity": 0.32, "fade_in_seconds": 0.5, "fade_out_seconds": 0.5},
            {"id": "independent_motion_graphic", "kind": "video", "role": "animated_graphic",
             "path": overlay.name, "start_seconds": 0, "end_seconds": 8,
             "x": 0, "y": 0, "width": width, "height": height, "fit": "contain",
             "opacity": 0.20}
        ],
        # The character render already carries its canonical Violin Prince
        # header. Avoid a second title over the same safe-area text; retain one
        # closing brand mark after the final hero shot.
        "text_layers": [
            {"id": "closing_tag", "text": "VIOLIN PRINCE", "start_seconds": 5.3,
             "end_seconds": 7.5, "x": 42, "y": 1165, "font_size": 24,
             "color": "#FFFFFF", "alpha": 0.88}
        ],
        "audio_tracks": _audio_track_manifest(
            voice, music_wav, sfx,
            creator_voice=creator_voice,
            music_source=music_source,
            voice_source_in_seconds=voice_source_in_seconds,
        ),
        "audio_provenance": {
            "voice_source": "creator_recorded_voice" if creator_voice else "synthetic_test_fixture",
            "music_source": "creator_recorded_violin" if music_source == "creator_recording" else "cc0_sample",
            "private_creator_audio": bool(creator_voice or music_source == "creator_recording"),
        },
    }
    manifest_path = output_dir / "cinematic-timeline.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a preview-only cinematic timeline using private creator audio or an explicit test voice."
    )
    parser.add_argument("--character-video", required=True, type=Path)
    parser.add_argument("--music-wav", required=True, type=Path)
    voice_mode = parser.add_mutually_exclusive_group(required=True)
    voice_mode.add_argument("--voice-wav", type=Path, help="Private creator-recorded narration WAV.")
    voice_mode.add_argument(
        "--synthetic-voice-for-tests", action="store_true",
        help="Use the synthetic narration fixture in automated tests only.",
    )
    parser.add_argument(
        "--music-source", choices=("cc0_sample", "creator_recording"), default="cc0_sample",
        help="Declare whether --music-wav is the CC0 test bed or a private creator violin take.",
    )
    parser.add_argument("--voice-source-in-seconds", type=float, default=0.0)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        path = create_fixture(
            args.character_video, args.music_wav, args.output_dir,
            voice_wav=args.voice_wav,
            synthetic_voice_for_tests=args.synthetic_voice_for_tests,
            music_source=args.music_source,
            voice_source_in_seconds=args.voice_source_in_seconds,
        )
        print(f"CINEMATIC_TIMELINE={path}")
        return 0
    except Exception as exc:
        parser.exit(1, "Cinematic fixture stopped safely: " + str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
