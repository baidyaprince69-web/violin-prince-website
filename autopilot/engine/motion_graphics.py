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
    draw.line(((arrow_x + 33, 18), (arrow_x + 42, 24), (arrow_x + 33, 30)),
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



def make_ambient_glow_frames(
    target_dir: str | Path,
    frame_count: int,
    fps: int,
    scene_index: int = 0,
) -> Path:
    """Create subtle, moving illuminated dust, star glints and gradient halos."""
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    width, height = 360, 640
    count = max(1, int(frame_count))
    anchors = (
        (0.12, 0.20, 0.22), (0.84, 0.28, 0.17),
        (0.18, 0.70, 0.16), (0.87, 0.78, 0.20),
        (0.52, 0.13, 0.11),
    )
    motes = tuple(
        (
            (index * 67 + scene_index * 23) % width,
            (index * 113 + scene_index * 41) % height,
            0.5 + ((index * 7 + scene_index) % 9) * 0.12,
            (index * 0.73 + scene_index * 0.51) % math.tau,
        )
        for index in range(18)
    )

    for frame_index in range(count):
        progress = frame_index / max(1, count - 1)
        phase = progress * math.tau
        haze = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        haze_draw = ImageDraw.Draw(haze)

        # Soft coloured light pools drift almost imperceptibly along the edges.
        for glow_index, (nx, ny, radius) in enumerate(anchors):
            drift = math.sin(phase + glow_index * 1.23) * 7.0
            cx = int(nx * width + drift)
            cy = int(ny * height + math.cos(phase + glow_index) * 9.0)
            r = int(38 + radius * 35)
            colour = (235, 190, 112, 19) if glow_index % 2 == 0 else (76, 187, 181, 15)
            haze_draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill=colour)
        haze = haze.filter(ImageFilter.GaussianBlur(27 + (scene_index % 2) * 4))

        crisp = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(crisp)
        # Sparse dust motes gently rise and drift sideways.
        for mote_index, (x0, y0, scale, offset) in enumerate(motes):
            travel = progress * 34.0
            x = int((x0 + math.sin(phase + offset) * 5 + travel * (0.35 + scale * 0.14)) % width)
            y = int((y0 - travel * (0.45 + scale * 0.20) + math.cos(phase + offset) * 4) % height)
            pulse = 0.5 + 0.5 * math.sin(phase * (0.8 + scale * 0.16) + offset)
            alpha = int(34 + pulse * 62)
            radius = 1 if mote_index % 4 else 2
            colour = (255, 231, 183, alpha) if mote_index % 3 else (119, 225, 219, int(alpha * 0.8))
            draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=colour)

        # Three tiny four-point glints, never oversized decorative stars.
        for star_index, (nx, ny, radius, speed) in enumerate((
            (0.78, 0.17, 5, 1.0),
            (0.16, 0.44, 4, 0.7),
            (0.88, 0.61, 4, 0.9),
        )):
            twinkle = 0.5 + 0.5 * math.sin(phase * speed + star_index * 2.1)
            alpha = int(75 + twinkle * 105)
            cx = int(nx * width + math.sin(phase + star_index) * 3)
            cy = int(ny * height + math.cos(phase * 0.8 + star_index) * 4)
            length = radius + int(twinkle * 2)
            draw.line((cx-length, cy, cx+length, cy), fill=(255, 238, 202, alpha), width=1)
            draw.line((cx, cy-length, cx, cy+length), fill=(255, 238, 202, alpha), width=1)
            draw.ellipse((cx-1, cy-1, cx+1, cy+1), fill=(255, 250, 232, min(235, alpha+45)))

        Image.alpha_composite(haze, crisp).save(
            target / f"glow-{frame_index + 1:05d}.png", "PNG", optimize=True
        )

    return target / "glow-%05d.png"



def _spring_response(elapsed: float, omega: float = 16.0, damping: float = 0.94) -> float:
    """Closed-form damped spring step response, deterministic at any frame time."""
    if elapsed <= 0:
        return 0.0
    t = float(elapsed)
    w = max(0.1, float(omega))
    z = max(0.0, float(damping))
    if z < 1.0 - 1e-6:
        wd = w * math.sqrt(1.0 - z * z)
        return 1.0 - math.exp(-z * w * t) * (
            math.cos(wd * t) + (z * w / wd) * math.sin(wd * t)
        )
    if z > 1.0 + 1e-6:
        q = w * math.sqrt(z * z - 1.0)
        r1, r2 = -z * w + q, -z * w - q
        return 1.0 - (r2 * math.exp(r1 * t) - r1 * math.exp(r2 * t)) / (r2 - r1)
    return 1.0 - math.exp(-w * t) * (1.0 + w * t)


def _spring_track(
    keyframes: list[tuple[float, float]],
    initial: float = 0.0,
    omega: float = 16.0,
    damping: float = 0.94,
) -> Callable[[float], float]:
    """Build a seekable value track from target changes using summed spring steps."""
    previous = float(initial)
    changes = []
    for at, target in sorted(keyframes, key=lambda item: item[0]):
        target = float(target)
        delta = target - previous
        if abs(delta) > 1e-9:
            changes.append((max(0.0, float(at)), delta))
        previous = target

    def value_at(time_value: float) -> float:
        result = float(initial)
        for at, delta in changes:
            result += delta * _spring_response(float(time_value) - at, omega, damping)
        return max(0.0, min(1.0, result))

    return value_at


def _select_word_beats(word_events: list[dict] | None, duration: float, limit: int = 7) -> list[dict]:
    """Select readable content-word cues for purposeful animation beats."""
    if not isinstance(word_events, list):
        return []
    stop_words = {
        "about", "after", "again", "also", "because", "been", "being", "could",
        "does", "from", "have", "into", "just", "like", "more", "most", "only",
        "over", "same", "some", "than", "that", "their", "there", "these",
        "they", "this", "those", "through", "very", "when", "where", "which",
        "while", "with", "would", "your",
    }
    candidates = []
    for item in word_events:
        if not isinstance(item, dict):
            continue
        try:
            start = float(item.get("start"))
        except (TypeError, ValueError):
            continue
        word = re.sub(r"[^A-Za-z0-9'-]", "", str(item.get("text") or ""))
        if not word or start < 0 or start >= max(0.0, duration - 0.08):
            continue
        candidates.append({"start": start, "text": word})

    if not candidates:
        return []
    content = [
        item for item in candidates
        if len(item["text"]) >= 4 and item["text"].casefold() not in stop_words
    ]
    pool = content if content else candidates
    # Keep beats distinct enough to read. If the script is dense, sample across it.
    spaced = []
    for item in pool:
        if not spaced or item["start"] - spaced[-1]["start"] >= 0.42:
            spaced.append(item)
    if not spaced:
        spaced = [pool[0]]
    if len(spaced) > limit:
        indices = [round(index * (len(spaced) - 1) / (limit - 1)) for index in range(limit)]
        spaced = [spaced[index] for index in dict.fromkeys(indices)]
    return spaced


def _voice_progress(time_value: float, duration: float, beats: list[dict]) -> float:
    """Move a diagram's focus on narration words, not on an arbitrary linear timer."""
    if not beats:
        progress = max(0.0, min(1.0, time_value / max(0.1, duration)))
        return progress * progress * (3.0 - 2.0 * progress)

    keyframes = []
    count = len(beats)
    for index, beat in enumerate(beats):
        target = 0.12 + 0.76 * (index + 1) / count
        keyframes.append((float(beat["start"]), target))
    last_start = float(beats[-1]["start"])
    finish_at = min(max(0.0, duration - 0.12), last_start + 0.55)
    keyframes.append((finish_at, 0.98))
    return _spring_track(keyframes)(time_value)


def _voice_pulse(time_value: float, beats: list[dict]) -> float:
    """A restrained spring-like pulse marks each spoken content beat."""
    pulse = 0.0
    for beat in beats:
        elapsed = time_value - float(beat["start"])
        if 0.0 <= elapsed <= 0.72:
            pulse = max(pulse, math.exp(-5.0 * elapsed))
    return max(0.0, min(1.0, pulse))


def make_motion_graphic_frames(
    scene: dict,
    index: int,
    plan: dict,
    target_dir: str | Path,
    frame_count: int,
    fps: int,
    font: Callable[..., object],
    word_events: list[dict] | None = None,
) -> Path:
    """Render a scene-specific, word-driven graphic with deterministic spring motion."""
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    width, height = 620, 260
    count = max(1, int(frame_count))
    frame_rate = max(1, int(fps))
    duration = count / frame_rate
    mode = _clean(scene.get("visual_mode") or "waveform", 40).casefold()
    valid_modes = {
        "macro_3d", "mechanism_3d", "waveform",
        "melody_map", "comparison", "cover_performance",
    }
    if mode not in valid_modes:
        mode = "waveform"

    beats = _select_word_beats(word_events, duration)
    progress_track = None
    if beats:
        keyframes = []
        for beat_index, beat in enumerate(beats):
            keyframes.append((float(beat["start"]), 0.12 + 0.76 * (beat_index + 1) / len(beats)))
        keyframes.append((min(max(0.0, duration - 0.12), float(beats[-1]["start"]) + 0.55), 0.98))
        progress_track = _spring_track(keyframes)

    label = _clean(scene.get("graphic_label") or f"STORY BEAT {index + 1}", 28).upper()
    caption = _clean(scene.get("caption") or plan.get("title") or "Music, explained", 88)
    detail = _clean(scene.get("graphic_detail") or "", 110)
    label_font = font(12, "medium")
    headline_font = font(27, "regular", "serif")
    detail_font = font(15, "regular")

    def wrap_pixels(draw, value, face, max_width, max_lines):
        lines = []
        current = ""
        for word in str(value or "").split():
            candidate = (current + " " + word).strip()
            bounds = draw.textbbox((0, 0), candidate, font=face)
            if current and bounds[2] - bounds[0] > max_width:
                lines.append(current)
                current = word
            else:
                current = candidate
        if current:
            lines.append(current)
        if len(lines) > max_lines:
            lines = lines[:max_lines]
            lines[-1] = lines[-1].rstrip(" .") + "…"
        return lines

    headline_probe = ImageDraw.Draw(Image.new("RGBA", (width, height)))
    headline_lines = wrap_pixels(headline_probe, caption, headline_font, 282, 2)
    detail_lines = wrap_pixels(headline_probe, detail, detail_font, 282, 3)
    label_at = max(0.0, (float(beats[0]["start"]) - 0.10)) if beats else 0.04
    headline_at = max(0.0, (float(beats[0]["start"]) + 0.10)) if beats else 0.16
    detail_at = (
        max(0.0, float(beats[1]["start"]) + 0.06)
        if len(beats) > 1 else headline_at + 0.58
    )

    for frame_index in range(count):
        local_time = frame_index / frame_rate
        progress = (
            progress_track(local_time) if progress_track
            else _voice_progress(local_time, duration, [])
        )
        pulse = _voice_pulse(local_time, beats)
        phase = local_time * 0.92 + index * 0.17
        label_reveal = _spring_response(local_time - label_at, 19.0, 0.96)
        headline_reveal = _spring_response(local_time - headline_at, 16.0, 0.94)
        detail_reveal = _spring_response(local_time - detail_at, 13.0, 0.98)

        # A compact, restrained light pool adds separation inside the panel only.
        haze = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        haze_draw = ImageDraw.Draw(haze)
        glow_x = int(470 + math.sin(phase * 0.7) * 12)
        glow_alpha = int(18 + pulse * 8)
        haze_draw.ellipse(
            (glow_x - 100, 8, glow_x + 100, 172),
            fill=(70, 184, 181, glow_alpha),
        )
        haze = haze.filter(ImageFilter.GaussianBlur(38))

        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)
        draw.rounded_rectangle(
            (4, 4, width - 4, height - 4),
            radius=22,
            fill=(5, 11, 23, 206),
            outline=(174, 194, 207, 112),
            width=1,
        )
        draw.line((28, 12, width - 28, 12), fill=(235, 202, 139, 100), width=1)
        draw.rounded_rectangle((28, 30, 32, 57), radius=2, fill=(74, 190, 185, 235))
        image = Image.alpha_composite(image, haze)
        draw = ImageDraw.Draw(image)

        # The illustration remains in one fixed visual stage; its focus moves on
        # selected spoken words. Each mode keeps its own source-grounded diagram.
        draw.rounded_rectangle(
            (350, 25, 590, 139),
            radius=16,
            fill=(11, 22, 37, 115),
            outline=(160, 184, 200, 80),
            width=1,
        )
        left, right = 372, 568
        top, bottom = 42, 122
        teal = (74, 190, 185, 235)
        gold = (235, 202, 139, 245)
        ivory = (255, 246, 225, 230)
        muted = (144, 166, 184, 155)

        if mode in {"macro_3d", "mechanism_3d"}:
            for strand in range(3):
                baseline = 62 + strand * 17
                pts = []
                for x in range(left, right + 1, 3):
                    u = (x - left) / (right - left)
                    amp = (4.5 + strand * 1.1) * (1.0 + 0.14 * pulse)
                    y = baseline + math.sin(u * math.tau * 2.0 - phase + strand * 0.22) * amp
                    pts.append((x, int(y)))
                draw.line(pts, fill=teal if strand != 1 else gold, width=2, joint="curve")
            marker_x = left + int(progress * (right - left))
            marker_y = int(79 + math.sin(phase * 1.4) * 3)
            ring = 9 + int(pulse * 7)
            for radius, alpha in ((ring + 9, int(65 + pulse * 45)), (ring, int(125 + pulse * 55))):
                draw.ellipse(
                    (marker_x-radius, marker_y-radius, marker_x+radius, marker_y+radius),
                    outline=(235, 202, 139, alpha),
                    width=2,
                )
            draw.ellipse((marker_x-3, marker_y-3, marker_x+3, marker_y+3), fill=ivory)
            if mode == "mechanism_3d":
                bridge_x = 465
                draw.polygon(
                    [(bridge_x-10, 100), (bridge_x+10, 100),
                     (bridge_x+17, 119), (bridge_x-17, 119)],
                    fill=(121, 79, 45, 215),
                    outline=gold,
                )
                bow_x = int(390 + progress * 90)
                draw.line((bow_x, 38, bow_x+38, 115), fill=(226, 231, 230, 155), width=5)
                draw.line((bow_x, 38, bow_x+38, 115), fill=ivory, width=1)

        elif mode == "melody_map":
            staff_y = (55, 69, 83, 97, 111)
            for y in staff_y:
                draw.line((left, y, right, y), fill=muted, width=1)
            note_x = [384, 410, 437, 462, 489, 516, 544, 565]
            note_y = [101, 85, 92, 64, 78, 55, 72, 88]
            draw.line(list(zip(note_x, note_y)), fill=teal, width=2, joint="curve")
            active = min(len(note_x) - 1, max(0, int(progress * len(note_x))))
            for note_index, (x, y) in enumerate(zip(note_x, note_y)):
                is_active = note_index == active
                is_played = note_index < active
                if is_active:
                    radius = 5 + int(pulse * 3)
                    draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=ivory, outline=gold, width=2)
                else:
                    draw.ellipse(
                        (x-4, y-3, x+4, y+3),
                        fill=gold if is_played else muted,
                    )
            scan_x = note_x[active]
            draw.line((scan_x, 42, scan_x, 119), fill=(235, 202, 139, int(90 + pulse * 70)), width=1)

        elif mode == "comparison":
            for row, baseline, colour, amp in (
                ("A", 67, gold, 10),
                ("B", 103, teal, 7),
            ):
                points = []
                for x in range(left, right + 1, 3):
                    u = (x - left) / (right - left)
                    y = baseline + math.sin(u * math.tau * 1.5 - phase) * amp
                    points.append((x, int(y)))
                draw.text((left - 2, baseline - 22), row, font=label_font, fill=colour)
                draw.line(points, fill=colour, width=2, joint="curve")
            scan_x = left + int(progress * (right - left))
            draw.line((scan_x, top, scan_x, bottom), fill=(255, 246, 225, int(80 + pulse * 75)), width=2)

        elif mode == "cover_performance":
            for bar in range(22):
                x = left + 2 + bar * 9
                envelope = abs(math.sin((bar / 21) * math.pi))
                bar_height = 8 + int((11 + 27 * envelope) * (
                    0.35 + 0.65 * abs(math.sin(phase * 1.15 + bar * 0.62))
                ))
                draw.rounded_rectangle(
                    (x, 111-bar_height, x+4, 111),
                    radius=2,
                    fill=gold if bar % 3 else teal,
                )
            marker_x = left + int(progress * (right - left))
            draw.line((marker_x, 43, marker_x, 118), fill=(255, 246, 225, int(80 + pulse * 90)), width=2)
            draw.line((left, 115, right, 115), fill=muted, width=1)

        else:  # waveform
            for strand, (baseline, amp, colour) in enumerate((
                (66, 14, gold), (101, 9, teal),
            )):
                points = []
                for x in range(left, right + 1, 3):
                    u = (x - left) / (right - left)
                    y = baseline + math.sin(u * math.tau * 2.0 - phase + strand * 0.35) * amp
                    points.append((x, int(y)))
                draw.line(points, fill=colour, width=2, joint="curve")
            scan_x = left + int(progress * (right - left))
            draw.line((scan_x, top, scan_x, bottom), fill=(255, 246, 225, int(80 + pulse * 80)), width=2)
            draw.ellipse((scan_x-4, 78-4, scan_x+4, 78+4), fill=ivory)

        # Label, headline and explanatory detail enter in separate speech-led beats.
        label_alpha = int(230 * label_reveal)
        label_x = 48 - int(5 * (1.0 - label_reveal))
        draw.text((label_x, 31 + int(5 * (1.0 - label_reveal))), label,
                  font=label_font, fill=(235, 202, 139, label_alpha))
        headline_alpha = int(255 * headline_reveal)
        headline_x = 48 - int(9 * (1.0 - headline_reveal))
        headline_y = 76 + int(8 * (1.0 - headline_reveal))
        for line in headline_lines:
            draw.text((headline_x, headline_y), line, font=headline_font,
                      fill=(255, 250, 241, headline_alpha))
            headline_y += 34

        detail_alpha = int(245 * detail_reveal)
        detail_x = 48 - int(7 * (1.0 - detail_reveal))
        detail_y = max(151, headline_y + 3)
        for line in detail_lines:
            if detail_y > 218:
                break
            draw.text((detail_x, detail_y), line, font=detail_font,
                      fill=(191, 202, 214, detail_alpha))
            detail_y += 19

        # The indicator advances at chosen spoken content words and settles smoothly.
        line_y = 237
        draw.line((48, line_y, width - 48, line_y), fill=(132, 151, 169, 100), width=1)
        progress_x = 48 + int(progress * (width - 96))
        draw.line((48, line_y, progress_x, line_y), fill=gold, width=2)
        draw.ellipse((progress_x-4, line_y-4, progress_x+4, line_y+4),
                     fill=ivory if pulse < 0.05 else gold)

        image.save(target / f"frame-{frame_index + 1:05d}.png", "PNG", optimize=True)

    return target / "frame-%05d.png"
