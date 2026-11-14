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


def _draw_macro_string(draw: ImageDraw.ImageDraw, progress: float, phase: float, width: int) -> None:
    """Show layered string vibration with a travelling focus pulse."""
    palette = ((74, 190, 185, 150), (235, 202, 139, 235), (255, 246, 224, 190))
    for strand, colour in enumerate(palette):
        points = []
        baseline = 43 + strand * 10
        amplitude = 4 + strand * 1.8
        for x in range(48, width - 30, 4):
            u = (x - 48) / max(1, width - 78)
            y = baseline + math.sin(u * math.tau * 2.1 - phase + strand * 0.32) * amplitude
            points.append((x, int(y)))
        draw.line(points, fill=colour, width=3 if strand == 1 else 2, joint="curve")
    marker_x = 48 + int(progress * (width - 82))
    marker_y = 53 + int(math.sin(phase) * 5)
    pulse = 12 + int((0.5 + 0.5 * math.sin(phase * 1.3)) * 9)
    for radius, alpha in ((pulse + 12, 85), (pulse, 170)):
        draw.ellipse(
            (marker_x - radius, marker_y - radius, marker_x + radius, marker_y + radius),
            outline=(74, 190, 185, alpha),
            width=2,
        )
    draw.ellipse(
        (marker_x - 5, marker_y - 5, marker_x + 5, marker_y + 5),
        fill=(255, 246, 224, 250),
    )


def _draw_mechanism_diagram(draw: ImageDraw.ImageDraw, progress: float, phase: float, width: int) -> None:
    """Animate a simplified bow/string/bridge interaction diagram."""
    string_points = _curve_points("mechanism_3d", phase, width, 54)
    draw.line(string_points, fill=(74, 190, 185, 235), width=4, joint="curve")
    # The bridge is a symbolic cross-section, not a measured instrument blueprint.
    draw.polygon(
        [(414, 39), (444, 39), (455, 82), (403, 82)],
        fill=(125, 82, 43, 225),
        outline=(235, 202, 139, 255),
    )
    draw.line((419, 40, 438, 40), fill=(255, 246, 224, 235), width=2)
    bow_x = 140 + int(math.sin(phase * 0.7) * 34)
    draw.line((bow_x, 24, bow_x + 118, 82), fill=(74, 190, 185, 115), width=11)
    draw.line((bow_x, 24, bow_x + 118, 82), fill=(255, 246, 224, 245), width=2)
    contact_x = bow_x + 61
    contact_y = 54
    radius = 10 + int((0.5 + 0.5 * math.sin(phase * 1.4)) * 7)
    draw.ellipse(
        (contact_x - radius, contact_y - radius, contact_x + radius, contact_y + radius),
        outline=(235, 202, 139, 245),
        width=3,
    )
    draw.ellipse(
        (contact_x - 4, contact_y - 4, contact_x + 4, contact_y + 4),
        fill=(255, 246, 224, 255),
    )
    arrow_x = 275 + int(progress * 24)
    draw.line((arrow_x, 24, arrow_x + 42, 24), fill=(74, 190, 185, 230), width=2)
    draw.line((arrow_x + 33, 18, arrow_x + 42, 24, arrow_x + 33, 30),
              fill=(74, 190, 185, 230), width=2)


def _draw_melody_map(draw: ImageDraw.ImageDraw, progress: float, phase: float, width: int) -> None:
    """Animate an abstract pitch contour without reproducing a copyrighted melody."""
    staff_y = (31, 43, 55, 67, 79)
    for y in staff_y:
        draw.line((52, y, width - 30, y), fill=(120, 133, 151, 135), width=1)
    note_x = [82, 151, 220, 289, 358, 427, 496, 555]
    pitch_y = [68, 55, 61, 37, 48, 29, 43, 56]
    contour = list(zip(note_x, pitch_y))
    draw.line(contour, fill=(74, 190, 185, 170), width=3, joint="curve")
    active_index = min(len(note_x) - 1, int(progress * len(note_x)))
    for index, (x, y) in enumerate(contour):
        draw.ellipse((x - 6, y - 4, x + 6, y + 4),
                     fill=(235, 202, 139, 245) if index <= active_index else (191, 202, 214, 175))
        draw.line((x + 5, y, x + 5, y - 18), fill=(235, 202, 139, 210), width=2)
    scan_x = 82 + int(progress * (width - 164))
    draw.line((scan_x, 22, scan_x, 88), fill=(255, 246, 224, 185), width=2)
    active_x, active_y = contour[active_index]
    glow = 10 + int((0.5 + 0.5 * math.sin(phase)) * 5)
    draw.ellipse((active_x - glow, active_y - glow, active_x + glow, active_y + glow),
                 outline=(74, 190, 185, 235), width=2)


def _draw_waveform(draw: ImageDraw.ImageDraw, mode: str, progress: float, phase: float, width: int) -> None:
    points = _curve_points(mode, phase, width, 52)
    draw.line(points, fill=(235, 202, 139, 238), width=3, joint="curve")
    if mode == "comparison":
        second = [
            (x, int(y + 18 + math.sin((x / width * math.tau) + phase * 0.7) * 5))
            for x, y in points
        ]
        draw.line(second, fill=(74, 190, 185, 210), width=2, joint="curve")
        draw.text((48, 23), "A", fill=(235, 202, 139, 230))
        draw.text((48, 67), "B", fill=(74, 190, 185, 230))
    else:
        marker_x = 44 + int(progress * (width - 88))
        marker_y = int(52 + math.sin(phase + progress * math.tau * 0.45) * 5)
        draw.ellipse(
            (marker_x - 8, marker_y - 8, marker_x + 8, marker_y + 8),
            fill=(255, 246, 224, 250),
            outline=(74, 190, 185, 255),
            width=3,
        )


def _draw_performance_bars(draw: ImageDraw.ImageDraw, phase: float) -> None:
    """Render a moving spectrum-like energy display for a performance beat."""
    for bar in range(15):
        x = 70 + bar * 34
        envelope = abs(math.sin((bar / 14) * math.pi))
        bar_height = 7 + int((10 + 24 * envelope) * (0.35 + 0.65 * abs(math.sin(phase + bar * 0.72))))
        draw.rounded_rectangle(
            (x, 78 - bar_height, x + 9, 78),
            radius=4,
            fill=(74, 190, 185, 220),
        )
    marker_x = 70 + int((phase % math.tau) / math.tau * 476)
    draw.ellipse((marker_x - 5, 39, marker_x + 5, 49), fill=(255, 246, 224, 245))


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

        # Give each scene a distinct animated explanatory visual, not one repeated waveform.
        glow = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        glow_draw = ImageDraw.Draw(glow)
        points = _curve_points(mode, phase, width, 52)
        glow_draw.line(points, fill=(45, 190, 183, 145), width=13, joint="curve")
        glow = glow.filter(ImageFilter.GaussianBlur(8))
        image = Image.alpha_composite(image, glow)
        draw = ImageDraw.Draw(image)

        if mode == "macro_3d":
            _draw_macro_string(draw, progress, phase, width)
        elif mode == "mechanism_3d":
            _draw_mechanism_diagram(draw, progress, phase, width)
        elif mode == "melody_map":
            _draw_melody_map(draw, progress, phase, width)
        elif mode == "cover_performance":
            _draw_performance_bars(draw, phase)
        else:
            _draw_waveform(draw, mode, progress, phase, width)

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
