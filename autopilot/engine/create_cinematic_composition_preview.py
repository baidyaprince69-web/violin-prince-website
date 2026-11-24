"""Create safe synthetic assets for the public cinematic-composition smoke preview."""
from __future__ import annotations

import argparse
import json
import math
import shutil
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw


def _run(command: list[str]) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        detail = getattr(exc, "stderr", "") or str(exc)
        raise RuntimeError("Unable to prepare the synthetic composition preview: " + str(detail)[-1800:]) from exc


def create_fixture(character_video: Path, music_wav: Path, output_dir: Path) -> Path:
    character_video = character_video.resolve(strict=True)
    music_wav = music_wav.resolve(strict=True)
    output_dir.mkdir(parents=True, exist_ok=True)
    voice = output_dir / "synthetic-narration-preview.wav"
    overlay_dir = output_dir / "overlay-frames"
    overlay_dir.mkdir(parents=True, exist_ok=True)
    overlay = output_dir / "independent-motion-graphic-overlay.mov"
    sfx = output_dir / "preview-whoosh.wav"

    espeak = shutil.which("espeak-ng")
    ffmpeg = shutil.which("ffmpeg")
    if not espeak or not ffmpeg:
        raise RuntimeError("The synthetic smoke preview requires espeak-ng and ffmpeg on PATH.")
    _run([espeak, "-v", "en-us", "-s", "154", "-w", str(voice),
          "Violin Prince. One performance. Five camera shots. A full-body introduction, close details of the violin and bow, the performer, then the final wide shot."])

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
             "camera_framing": "full_body_wide", "shot_id": "shot-01-wide",
             "shot_label": "Full-body establishing performance",
             "grade": {"contrast": 1.08, "saturation": 0.92, "brightness": -0.015, "gamma": 0.98}},
            {"id": "medium_performance_shot", "kind": "video", "role": "character_performance",
             "path": str(character_video), "start_seconds": 1.65, "end_seconds": 3.35,
             "source_in_seconds": 1.6, "x": 0, "y": 0, "width": width, "height": height,
             "fit": "cover", "camera_crop": {"x": 0.10, "y": 0.05, "width": 0.80, "height": 0.80},
             "camera_framing": "medium_performance", "shot_id": "shot-02-medium",
             "shot_label": "Medium performer and instrument shot",
             "fade_in_seconds": 0.24, "fade_out_seconds": 0.24,
             "grade": {"contrast": 1.08, "saturation": 0.92, "brightness": -0.015, "gamma": 0.98}},
            {"id": "instrument_hands_closeup", "kind": "video", "role": "character_performance",
             "path": str(character_video), "start_seconds": 3.15, "end_seconds": 4.95,
             "source_in_seconds": 3.0, "x": 0, "y": 0, "width": width, "height": height,
             "fit": "cover", "camera_crop": {"x": 0.26, "y": 0.17, "width": 0.64, "height": 0.64},
             "camera_framing": "instrument_hands_close_up", "shot_id": "shot-03-instrument",
             "shot_label": "Violin, bow and hand close-up",
             "fade_in_seconds": 0.22, "fade_out_seconds": 0.22,
             "grade": {"contrast": 1.08, "saturation": 0.92, "brightness": -0.015, "gamma": 0.98}},
            {"id": "face_performance_closeup", "kind": "video", "role": "character_performance",
             "path": str(character_video), "start_seconds": 4.75, "end_seconds": 6.45,
             "source_in_seconds": 4.2, "x": 0, "y": 0, "width": width, "height": height,
             "fit": "cover", "camera_crop": {"x": 0.19, "y": 0.02, "width": 0.62, "height": 0.62},
             "camera_framing": "face_close_up", "shot_id": "shot-04-face",
             "shot_label": "Expression and upper-body close-up",
             "fade_in_seconds": 0.22, "fade_out_seconds": 0.22,
             "grade": {"contrast": 1.08, "saturation": 0.92, "brightness": -0.015, "gamma": 0.98}},
            {"id": "hero_full_body_return", "kind": "video", "role": "character_performance",
             "path": str(character_video), "start_seconds": 6.25, "end_seconds": 8,
             "source_in_seconds": 6.0, "x": 0, "y": 0, "width": width, "height": height,
             "fit": "cover", "camera_crop": {"x": 0.02, "y": 0.02, "width": 0.96, "height": 0.96},
             "camera_framing": "full_body_wide", "shot_id": "shot-05-hero",
             "shot_label": "Return to full-body hero performance",
             "fade_in_seconds": 0.28,
             "grade": {"contrast": 1.08, "saturation": 0.92, "brightness": -0.015, "gamma": 0.98}},
            {"id": "independent_motion_graphic", "kind": "video", "role": "animated_graphic",
             "path": overlay.name, "start_seconds": 0, "end_seconds": 8,
             "x": 0, "y": 0, "width": width, "height": height, "fit": "contain",
             "opacity": 0.72}
        ],
        "text_layers": [
            {"id": "opening_title", "text": "VIOLIN PRINCE", "start_seconds": 0.6,
             "end_seconds": 2.8, "x": 42, "y": 82, "font_size": 42,
             "color": "#F3D7A4", "alpha": 0.95, "border_width": 1},
            {"id": "closing_tag", "text": "MUSIC IN MOTION", "start_seconds": 5.3,
             "end_seconds": 7.5, "x": 42, "y": 1165, "font_size": 28,
             "color": "#FFFFFF", "alpha": 0.88}
        ],
        "audio_tracks": [
            {"id": "synthetic_voice_preview", "role": "voice", "path": voice.name,
             "start_seconds": 0, "end_seconds": 8, "gain_db": -2,
             "fade_in_seconds": 0.08, "fade_out_seconds": 0.35,
             "private_source": False},
            {"id": "sampled_violin_music", "role": "music", "path": str(music_wav),
             "start_seconds": 0, "end_seconds": 8, "gain_db": -15, "loop": True,
             "fade_in_seconds": 0.25, "fade_out_seconds": 0.5},
            {"id": "transition_whoosh", "role": "sfx", "path": sfx.name,
             "start_seconds": 2.7, "end_seconds": 3.4, "gain_db": -16,
             "fade_in_seconds": 0.04, "fade_out_seconds": 0.2}
        ]
    }
    manifest_path = output_dir / "cinematic-timeline.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a synthetic-voice, preview-only cinematic timeline fixture.")
    parser.add_argument("--character-video", required=True, type=Path)
    parser.add_argument("--music-wav", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    try:
        path = create_fixture(args.character_video, args.music_wav, args.output_dir)
        print(f"CINEMATIC_TIMELINE={path}")
        return 0
    except Exception as exc:
        parser.exit(1, "Cinematic fixture stopped safely: " + str(exc) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
