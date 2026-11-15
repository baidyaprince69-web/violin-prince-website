"""Create deterministic cinematic image layers for the daily Frame By Plane scene.

These are authored background plates, not generated or downloaded photographs.
Blender's real 3D subject remains in front; Frame By Plane adds depth-separated
image planes with camera-space parallax behind that subject.
"""
from __future__ import annotations

import hashlib
import json
import random
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFilter


def _seed_for(scene: dict[str, Any], scene_index: int) -> int:
    raw = "|".join((
        str(scene.get("caption") or ""),
        str(scene.get("graphic_label") or ""),
        str(scene.get("image_prompt") or ""),
        str(scene_index),
    )).encode("utf-8")
    return int(hashlib.sha256(raw).hexdigest()[:8], 16)


def _gradient(size: tuple[int, int]) -> Image.Image:
    width, height = size
    image = Image.new("RGBA", size)
    draw = ImageDraw.Draw(image)
    top = (5, 12, 25)
    bottom = (15, 31, 48)
    for y in range(height):
        t = y / max(1, height - 1)
        eased = t * t * (3.0 - 2.0 * t)
        colour = tuple(round(top[i] * (1.0 - eased) + bottom[i] * eased) for i in range(3))
        draw.line((0, y, width, y), fill=(*colour, 255))
    return image


def _make_atmosphere(size: tuple[int, int], seed: int) -> Image.Image:
    width, height = size
    rng = random.Random(seed)
    image = _gradient(size)
    glows = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(glows)
    draw.ellipse(
        (int(width * 0.42), int(height * 0.08), int(width * 1.12), int(height * 0.58)),
        fill=(174, 104, 46, 52),
    )
    draw.ellipse(
        (-int(width * 0.30), int(height * 0.35), int(width * 0.56), int(height * 1.03)),
        fill=(22, 127, 144, 48),
    )
    draw.ellipse(
        (int(width * 0.55), int(height * 0.55), int(width * 1.22), int(height * 1.18)),
        fill=(101, 54, 31, 32),
    )
    image = Image.alpha_composite(image, glows.filter(ImageFilter.GaussianBlur(max(24, width // 8))))

    grain = Image.effect_noise(size, 9).convert("RGBA")
    grain.putalpha(16)
    image = Image.alpha_composite(image, grain)

    lights = Image.new("RGBA", size, (0, 0, 0, 0))
    light_draw = ImageDraw.Draw(lights)
    for _ in range(22):
        x = rng.randint(-20, width + 20)
        y = rng.randint(int(height * 0.10), int(height * 0.90))
        radius = rng.randint(max(4, width // 180), max(8, width // 65))
        colour = (231, 176, 100, rng.randint(14, 36)) if rng.random() > 0.5 else (80, 187, 190, rng.randint(12, 32))
        light_draw.ellipse((x - radius, y - radius, x + radius, y + radius), fill=colour)
    lights = lights.filter(ImageFilter.GaussianBlur(max(3, width // 100)))
    return Image.alpha_composite(image, lights)


def _draw_acoustic_environment(size: tuple[int, int], seed: int, scene: dict[str, Any]) -> Image.Image:
    width, height = size
    rng = random.Random(seed ^ 0xA71D10)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # Receding acoustic wall treatment, kept to the outer frame so the 3D hero
    # and the caption-safe central area remain unobstructed.
    panel_y0 = int(height * 0.20)
    panel_y1 = int(height * 0.58)
    panel_width = int(width * 0.13)
    for side in (0, 1):
        x0 = int(width * (0.025 if side == 0 else 0.845))
        x1 = x0 + panel_width
        draw.rounded_rectangle(
            (x0, panel_y0, x1, panel_y1),
            radius=max(8, width // 90),
            fill=(7, 15, 25, 188),
            outline=(117, 91, 62, 105),
            width=max(2, width // 360),
        )
        inner = max(8, width // 55)
        for slat in range(10):
            x = x0 + inner + slat * max(4, (panel_width - 2 * inner) // 10)
            draw.rounded_rectangle(
                (x, panel_y0 + inner, x + max(2, width // 180), panel_y1 - inner),
                radius=2,
                fill=(35, 53 + slat % 3 * 5, 66, 150),
            )

    # Studio monitors at the two edges provide a recognisable audio-room cue.
    speaker_y = int(height * 0.56)
    speaker_w = int(width * 0.16)
    speaker_h = int(height * 0.24)
    for side in (0, 1):
        x0 = int(width * (0.015 if side == 0 else 0.825))
        x1 = x0 + speaker_w
        y0, y1 = speaker_y, speaker_y + speaker_h
        draw.rounded_rectangle(
            (x0 + 4, y0 + 5, x1 + 4, y1 + 5),
            radius=max(10, width // 65),
            fill=(0, 0, 0, 90),
        )
        draw.rounded_rectangle(
            (x0, y0, x1, y1),
            radius=max(10, width // 65),
            fill=(8, 12, 19, 228),
            outline=(141, 103, 61, 180),
            width=max(2, width // 320),
        )
        cx = (x0 + x1) // 2
        cy = y0 + int(speaker_h * 0.43)
        r = int(speaker_w * 0.31)
        draw.ellipse((cx-r, cy-r, cx+r, cy+r), fill=(22, 29, 38, 255), outline=(153, 112, 66, 210), width=max(2, width // 250))
        r2 = int(r * 0.72)
        draw.ellipse((cx-r2, cy-r2, cx+r2, cy+r2), fill=(44, 58, 66, 255), outline=(66, 154, 159, 190), width=max(2, width // 260))
        r3 = int(r * 0.20)
        draw.ellipse((cx-r3, cy-r3, cx+r3, cy+r3), fill=(9, 17, 26, 255))
        small = int(speaker_w * 0.12)
        sy = y0 + int(speaker_h * 0.83)
        draw.ellipse((cx-small, sy-small, cx+small, sy+small), fill=(34, 44, 52, 255), outline=(190, 133, 69, 175), width=2)

    # Low, soft studio horizon and a few dim status lights.
    horizon = int(height * 0.83)
    draw.line((0, horizon, width, horizon), fill=(146, 99, 56, 76), width=max(2, width // 400))
    for index in range(12):
        x = rng.randint(int(width * 0.18), int(width * 0.82))
        y = rng.randint(int(height * 0.16), int(height * 0.40))
        radius = rng.randint(2, max(3, width // 240))
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=(211, 160, 91, rng.randint(45, 105)))
    return canvas.filter(ImageFilter.GaussianBlur(max(1, width // 1200)))


def _draw_foreground_depth(size: tuple[int, int], seed: int) -> Image.Image:
    width, height = size
    rng = random.Random(seed ^ 0xF09E6A)
    canvas = Image.new("RGBA", size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    for _ in range(74):
        x = rng.randint(-12, width + 12)
        y = rng.randint(-12, height + 12)
        radius = rng.randint(2, max(5, width // 110))
        alpha = rng.randint(16, 56)
        colour = (229, 176, 104, alpha) if rng.random() > 0.42 else (70, 174, 183, alpha)
        draw.ellipse((x-radius, y-radius, x+radius, y+radius), fill=colour)
    haze = Image.new("RGBA", size, (0, 0, 0, 0))
    haze_draw = ImageDraw.Draw(haze)
    haze_draw.ellipse(
        (int(width * 0.22), int(height * 0.74), int(width * 0.92), int(height * 1.15)),
        fill=(204, 132, 70, 20),
    )
    haze = haze.filter(ImageFilter.GaussianBlur(max(12, width // 28)))
    return Image.alpha_composite(canvas.filter(ImageFilter.GaussianBlur(max(1, width // 500))), haze)


def create_frame_by_plane_backgrounds(
    plan: dict[str, Any],
    output_root: str | Path,
    *,
    size: tuple[int, int] = (1080, 1920),
) -> list[dict[str, Any]]:
    """Create three deterministic camera-parallax image planes for each scene."""
    scenes = plan.get("scenes") if isinstance(plan, dict) else None
    if not isinstance(scenes, list) or len(scenes) != 3:
        raise ValueError("Frame By Plane daily production requires exactly three authored scenes.")
    root = Path(output_root).expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    width, height = int(size[0]), int(size[1])
    if width < 540 or height < 960:
        raise ValueError("Frame By Plane background plates must be at least 540×960 pixels.")

    manifests = []
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            raise ValueError(f"Scene {index + 1} is invalid.")
        seed = _seed_for(scene, index)
        folder = root / f"scene-{index + 1}"
        folder.mkdir(parents=True, exist_ok=True)

        atmosphere = _make_atmosphere(size, seed)
        environment = _draw_acoustic_environment(size, seed, scene)
        foreground = _draw_foreground_depth(size, seed)

        files = (
            ("01-far-atmosphere.png", atmosphere),
            ("02-studio-environment.png", environment),
            ("03-foreground-depth.png", foreground),
        )
        for filename, image in files:
            target = folder / filename
            image.save(target, format="PNG", optimize=True)
            with Image.open(target) as verify:
                if verify.size != size or verify.mode not in ("RGBA", "RGB"):
                    raise RuntimeError(f"Invalid Frame By Plane layer image: {target}")

        manifest = {
            "schema_version": 1,
            "style": "violin_prince_midnight_resonance_25d",
            "resolution": [width, height],
            "layers": [
                {
                    "name": "FarAtmosphere",
                    "role": "background",
                    "file": files[0][0],
                    "distance": 13.0,
                    "cover_scale": 2.15,
                    "parallax_x": 0.025,
                    "parallax_z": 0.018,
                },
                {
                    "name": "StudioEnvironment",
                    "role": "midground",
                    "file": files[1][0],
                    "distance": 8.0,
                    "cover_scale": 1.80,
                    "parallax_x": 0.16,
                    "parallax_z": 0.10,
                },
                {
                    "name": "ForegroundDepth",
                    "role": "foreground",
                    "file": files[2][0],
                    "distance": 3.0,
                    "cover_scale": 1.55,
                    "parallax_x": 0.32,
                    "parallax_z": 0.20,
                },
            ],
        }
        manifest_path = folder / "background-manifest.json"
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifests.append({
            "scene_index": index,
            "manifest_path": str(manifest_path),
            "layers": [str(folder / filename) for filename, _image in files],
        })
    return manifests
