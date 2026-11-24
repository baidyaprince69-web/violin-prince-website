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
          "Welcome to Violin Prince. This preview combines the full-body performance with narration, additional animation, music and sound effects."])

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
             "x": 0, "y": 0, "width": width, "height": height, "fit": "contain"},
            {"id": "independent_motion_graphic", "kind": "video", "role": "animated_graphic",
             "path": overlay.name, "start_seconds": 0, "end_seconds": 8,
             "x": 0, "y": 0, "width": width, "height": height, "fit": "contain",
             "opacity": 0.96}
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
