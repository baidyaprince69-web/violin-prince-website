#!/usr/bin/env python3
"""Render and package all local Violin Prince illustration modes and one story profile."""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))

import local_vector_illustrator as illustrator

SCENES = [
    {"id": "macro", "visual_mode": "macro_illustration",
     "caption": "The violin's shape", "image_prompt": "Macro view of a violin"},
    {"id": "mechanism", "visual_mode": "mechanism_illustration",
     "caption": "How the bridge transfers vibration", "image_prompt": "Violin bridge and vibrating strings"},
    {"id": "waveform", "visual_mode": "waveform",
     "caption": "Sound travels as waves", "image_prompt": "Acoustic waves from a violin"},
    {"id": "melody-map", "visual_mode": "melody_map",
     "caption": "A melody moves through pitch", "image_prompt": "Original melody pitch contour"},
    {"id": "comparison", "visual_mode": "comparison",
     "caption": "Compare two sound patterns", "image_prompt": "Two sound-wave patterns"},
    {"id": "cover-performance", "visual_mode": "cover_performance",
     "caption": "The violin performance payoff", "image_prompt": "Violin and bow performance visual"},
]

STUDIO_PLAN = {
    "title": "Can your room change your violin mix?",
    "topic": (
        "How Audient's third-generation iD interfaces measure room acoustics, "
        "adjust studio monitor playback and run onboard DSP."
    ),
    "narration_script": (
        "Could your room change your violin mix? Modern audio interfaces feature "
        "RoomTune monitor correction. It measures your room's acoustics and adjusts "
        "monitor response. Onboard DSP also runs input EQ, compression and reverb with no latency."
    ),
}
STUDIO_SCENES = [
    {"id": "studio-room", "visual_mode": "macro_illustration",
     "caption": "YOUR ROOM. YOUR SOUND.", "image_prompt": "Studio monitors and room acoustics"},
    {"id": "studio-measurement", "visual_mode": "waveform",
     "caption": "MEASURE. CORRECT. LISTEN.", "image_prompt": "Measurement microphone and monitor correction"},
    {"id": "studio-violin-payoff", "visual_mode": "cover_performance",
     "caption": "HEAR THE VIOLIN. TRUST THE MIX.", "image_prompt": "Violin performance in a treated studio"},
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def render_one(scene: dict, index: int, plan: dict, output_dir: Path) -> dict:
    target = output_dir / f"{scene['id']}.jpg"
    illustrator.render_scene(scene, index, plan, target)
    with Image.open(target) as image:
        image.verify()
    with Image.open(target) as image:
        if image.size != (1024, 1792) or image.format != "JPEG":
            raise RuntimeError(f"{scene['id']}: unexpected asset properties {image.size} {image.format}")
        return {
            "id": scene["id"],
            "visual_mode": scene["visual_mode"],
            "caption": scene["caption"],
            "path": target.name,
            "width": image.width,
            "height": image.height,
            "format": image.format,
            "bytes": target.stat().st_size,
            "sha256": sha256(target),
        }


def render_preview(output_dir: Path) -> dict:
    output_dir.mkdir(parents=True, exist_ok=True)
    records = [
        render_one(scene, index, {"title": "Violin Prince preview"}, output_dir)
        for index, scene in enumerate(SCENES)
    ]
    studio_records = [
        render_one(scene, index, STUDIO_PLAN, output_dir)
        for index, scene in enumerate(STUDIO_SCENES)
    ]
    all_records = records + studio_records

    # Produce a contact sheet that is easy to inspect inside the Actions artifact.
    tile_w, tile_h = 320, 560
    margin, gap, label_h = 32, 24, 64
    cols = 3
    rows = (len(all_records) + cols - 1) // cols
    sheet = Image.new(
        "RGB",
        (margin * 2 + cols * tile_w + (cols - 1) * gap,
         margin * 2 + rows * (tile_h + label_h) + (rows - 1) * gap),
        (8, 17, 30),
    )
    draw = ImageDraw.Draw(sheet)
    for i, record in enumerate(all_records):
        image_path = output_dir / record["path"]
        with Image.open(image_path) as image:
            tile = image.convert("RGB").resize((tile_w, tile_h), Image.Resampling.LANCZOS)
        row, col = divmod(i, cols)
        left = margin + col * (tile_w + gap)
        top = margin + row * (tile_h + label_h + gap)
        sheet.paste(tile, (left, top))
        draw.rectangle((left, top, left + tile_w - 1, top + tile_h - 1),
                       outline=(226, 190, 122), width=2)
        draw.text((left, top + tile_h + 12),
                  record["id"] + " — " + record["caption"],
                  fill=(242, 229, 199))
    contact_path = output_dir / "contact-sheet.jpg"
    sheet.save(contact_path, "JPEG", quality=90, optimize=True)

    manifest = {
        "status": "rendered",
        "renderer": illustrator.RENDERER_VERSION,
        "network_calls": False,
        "modes": records,
        "story_profile": {
            "profile": illustrator._scene_profile(STUDIO_PLAN),
            "topic": STUDIO_PLAN["topic"],
            "all_three_scenes_passed": len(studio_records) == 3,
            "scenes": studio_records,
        },
        "contact_sheet": contact_path.name,
        "contact_sheet_sha256": sha256(contact_path),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return manifest


def main() -> int:
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "work/local-vector-preview")
    manifest = render_preview(output)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print("Local vector illustration preview passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
