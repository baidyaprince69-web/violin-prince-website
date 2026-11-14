"""Deterministic animated visual-explainer panels for Violin Prince.

The panel is rendered frame-by-frame with Pillow and composited by FFmpeg.
It adds original motion graphics without a paid video API, Blender install,
or locally running software on the creator's computer.
"""
from __future__ import annotations

import math
import re
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFilter


def _clean(value: object, limit: int = 100) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _curve_points(mode: str, phase: float, width: int, baseline: int) -> list[tuple[int, int]]:
    points = []
    for x in range(44, width - 30, 4):
        u = (x - 44) / max(1, width - 74)
        if mode in {"mechanism_3d", "macro_3d"}:
            amplitude = 11 if mode == "mechanism_3d" else 7
            y = baseline + math.sin((u * 4.0 * math.pi) - phase) * amplitude
        elif mode == "melody_map":
            y = baseline + math.sin(u * 2.0 * math.pi - phase) * 12 + math.sin(u * 5.0 * math.pi) * 3
        elif mode == "comparison":
            y = baseline + math.sin(u * 3.0 * math.pi - phase) * 9
        else:
            envelope = 0.25 + 0.75 * abs(math.sin(u * math.pi))
            y = baseline + math.sin((u * 8.0 * math.pi) - phase) * (16 * envelope)
        points.append((x, int(y)))
    return points


def make_motion_graphic_frames(
    scene: dict,
    index: int,
    plan: dict,
    target_dir: str | Path,
    frame_count: int,
    fps: int,
    font: Callable[[int], object],
) -> Path:
    """Write a transparent animated panel sequence and return its frame pattern."""
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    width, height = 620, 300
    count = max(1, int(frame_count))
    frame_rate = max(1, int(fps))
    mode = _clean(scene.get("visual_mode") or "waveform", 40).casefold()
    if mode not in {
        "macro_3d", "mechanism_3d", "waveform",
        "melody_map", "comparison", "cover_performance",
    }:
        mode = "waveform"

    label = _clean(scene.get("graphic_label") or f"STORY BEAT {index + 1}", 28).upper()
    caption = _clean(scene.get("caption") or plan.get("title") or "Music, explained", 88)
    detail = _clean(scene.get("graphic_detail") or "", 110)
    headline_lines = []
    words = caption.split()
    line = ""
    for word in words:
        candidate = (line + " " + word).strip()
        if len(candidate) > 29 and line:
            headline_lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        headline_lines.append(line)
    headline_lines = headline_lines[:2]
    detail_lines = []
    words = detail.split()
    line = ""
    for word in words:
        candidate = (line + " " + word).strip()
        if len(candidate) > 50 and line:
            detail_lines.append(line)
            line = word
        else:
            line = candidate
    if line:
        detail_lines.append(line)
    detail_lines = detail_lines[:2]

    for frame_index in range(count):
        progress = frame_index / max(1, count - 1)
        phase = progress * math.tau * 2.2
        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (4, 4, width - 4, height - 4),
            radius=25,
            fill=(5, 11, 23, 226),
            outline=(235, 202, 139, 225),
            width=2,
        )
        draw.rounded_rectangle((24, 18, 32, 83), radius=4, fill=(235, 202, 139, 255))

        # A compact luminous signal moves with time. Its motion is deterministic,
        # so the same approved package always renders identically.
        points = _curve_points(mode, phase, width, 52)
        glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        glow_draw.line(points, fill=(45, 190, 183, 145), width=13, joint="curve")
        glow = glow.filter(ImageFilter.GaussianBlur(8))
        image = Image.alpha_composite(image, glow)
        draw = ImageDraw.Draw(image)
        draw.line(points, fill=(235, 202, 139, 238), width=3, joint="curve")

        if mode == "comparison":
            second = [
                (x, int(y + 18 + math.sin((x / width * math.tau) + phase * 0.7) * 5))
                for x, y in points
            ]
            draw.line(second, fill=(74, 190, 185, 210), width=2, joint="curve")
        elif mode == "cover_performance":
            for bar in range(15):
                x = 70 + bar * 34
                envelope = abs(math.sin((bar / 14) * math.pi))
                bar_height = 7 + int((10 + 24 * envelope) * (0.35 + 0.65 * abs(math.sin(phase + bar * 0.72))))
                draw.rounded_rectangle(
                    (x, 78 - bar_height, x + 9, 78),
                    radius=4,
                    fill=(74, 190, 185, 220),
                )
        else:
            marker_x = 44 + int(progress * (width - 88))
            marker_y = int(52 + math.sin(progress * math.tau * 2.2 - phase) * 5)
            draw.ellipse(
                (marker_x - 8, marker_y - 8, marker_x + 8, marker_y + 8),
                fill=(255, 246, 224, 250),
                outline=(74, 190, 185, 255),
                width=3,
            )

        draw.text((54, 96), f"{index + 1:02d}  /  03     {label}", font=font(15), fill=(235, 202, 139, 255))
        y = 126
        for headline in headline_lines:
            draw.text((54, y), headline, font=font(27), fill=(255, 250, 241, 255))
            y += 34
        detail_y = 205 if len(headline_lines) > 1 else 190
        for detail_line in detail_lines:
            draw.text((54, detail_y), detail_line, font=font(16), fill=(191, 202, 214, 255))
            detail_y += 22

        # Three-step progress is decorative navigation, not a data claim.
        line_y = 276
        draw.line((width - 112, line_y, width - 26, line_y), fill=(235, 202, 139, 110), width=2)
        for step in range(3):
            x = width - 112 + step * 43
            colour = (235, 202, 139, 255) if step <= index else (120, 133, 151, 180)
            draw.ellipse((x - 5, line_y - 5, x + 5, line_y + 5), fill=colour)

        image.save(target / f"frame-{frame_index + 1:05d}.png", "PNG", optimize=True)

    return target / "frame-%05d.png"
