#!/usr/bin/env python3
"""Prepare a cropped full-body Violin Prince master and separate instrument props.

The playing reference is the pose master. Its violin and bow are extracted into
transparent prop layers with fixed, reviewable source-space pivots. No publishing
or external image-generation service is involved.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw


def _skin_mask(rgb: np.ndarray) -> np.ndarray:
    red, green, blue = (rgb[:, :, i].astype(np.int16) for i in range(3))
    return (
        ((red - green) > 18) & ((green - blue) > 7) &
        (red > 85) & (red < 255) & (green > 30) & (green < 210) &
        (blue > 15) & (blue < 175)
    )


def build_props(master: Image.Image, reference_dir: Path) -> dict[str, Any]:
    """Create a transparent violin sprite and a continuous bow sprite."""
    rgba = master.convert("RGBA")
    pixels = np.asarray(rgba, dtype=np.uint8)
    height, width = pixels.shape[:2]
    rgb = pixels[:, :, :3]
    source_alpha = pixels[:, :, 3]
    skin = _skin_mask(rgb)
    yy, xx = np.mgrid[:height, :width]

    # Carefully traced contour in the cropped 441x755 performance canvas.
    violin_outline = Image.new("L", (width, height), 0)
    draw = ImageDraw.Draw(violin_outline)
    draw.polygon([
        (170, 140), (175, 128), (189, 119), (208, 114), (228, 117),
        (245, 126), (261, 138), (281, 139), (305, 145), (328, 152),
        (351, 161), (374, 170), (397, 181), (417, 192), (433, 203),
        (434, 212), (425, 222), (410, 226), (393, 222), (372, 215),
        (350, 207), (329, 201), (308, 197), (288, 193), (270, 189),
        (252, 183), (235, 177), (217, 169), (199, 161), (183, 153),
        (172, 146)
    ], fill=255)
    violin_mask = np.asarray(violin_outline, dtype=bool) & (source_alpha > 0)

    # Preserve the chin and both hands as character layers rather than baking
    # skin into the violin prop. These local windows match the supplied crop.
    face_roi = (xx >= 99) & (xx <= 247) & (yy >= 5) & (yy <= 150)
    left_hand_roi = (xx >= 324) & (xx <= 394) & (yy >= 161) & (yy <= 261)
    right_hand_roi = (xx >= 114) & (xx <= 209) & (yy >= 215) & (yy <= 315)
    violin_mask &= ~(skin & (face_roi | left_hand_roi | right_hand_roi))
    violin_image = rgba.copy()
    violin_image.putalpha(Image.fromarray(violin_mask.astype(np.uint8) * 255, mode="L"))
    violin_box = violin_image.getchannel("A").getbbox()
    if violin_box is None or (violin_box[2] - violin_box[0]) < 160:
        raise ValueError("Violin extraction did not contain a complete instrument silhouette.")
    violin_crop = violin_image.crop(violin_box)

    # Continuous bow stick plus horsehair; pivot sits where the bow is gripped.
    scale = 4
    bow = Image.new("RGBA", (width * scale, height * scale), (0, 0, 0, 0))
    bow_draw = ImageDraw.Draw(bow)
    start = (179 * scale, 287 * scale)
    end = (339 * scale, 45 * scale)
    bow_draw.line([start, end], fill=(52, 31, 20, 255), width=7 * scale)
    dx, dy = end[0] - start[0], end[1] - start[1]
    norm = max(1.0, (dx * dx + dy * dy) ** 0.5)
    ox, oy = -dy / norm * 2 * scale, dx / norm * 2 * scale
    bow_draw.line(
        [(start[0] + ox, start[1] + oy), (end[0] + ox, end[1] + oy)],
        fill=(231, 220, 198, 255), width=1 * scale
    )
    for cx, cy in (start, end):
        bow_draw.ellipse(
            (cx - 3 * scale, cy - 3 * scale, cx + 3 * scale, cy + 3 * scale),
            fill=(70, 47, 29, 255)
        )
    bow = bow.resize((width, height), Image.Resampling.LANCZOS)
    bow_box = bow.getchannel("A").getbbox()
    if bow_box is None:
        raise ValueError("Bow extraction returned an empty prop.")
    bow_crop = bow.crop(bow_box)

    reference_dir.mkdir(parents=True, exist_ok=True)
    violin_path = reference_dir / "violin.webp"
    bow_path = reference_dir / "bow.webp"
    violin_crop.save(violin_path, "WEBP", quality=96, method=6)
    bow_crop.save(bow_path, "WEBP", quality=96, method=6)

    # Props use exact master-canvas coordinates and are attached to the rig:
    # violin follows the torso; bow follows the bow-gripping screen-right hand.
    manifest = {
        "schema_version": 1,
        "canvas": {"width": width, "height": height},
        "props": {
            "violin": {
                "src": "violin.webp",
                "x": int(violin_box[0]), "y": int(violin_box[1]),
                "width": int(violin_crop.width), "height": int(violin_crop.height),
                "pivot_x": 0.22, "pivot_y": 0.5, "z_index": 25,
                "attach_to": "torso"
            },
            "bow": {
                "src": "bow.webp",
                "x": int(bow_box[0]), "y": int(bow_box[1]),
                "width": int(bow_crop.width), "height": int(bow_crop.height),
                "pivot_x": 0.035, "pivot_y": 0.976, "z_index": 35,
                "attach_to": "right_hand"
            }
        }
    }
    manifest_path = reference_dir / "instrument-props.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    # Four visible finger segments on the fingerboard hand are separate rig
    # candidates. Coordinates are authored against the tightly cropped playing
    # reference; the colour filter preserves skin pixels while the one-pixel
    # dilation retains their dark illustrated outlines.
    finger_manifest = {
        "schema_version": 1,
        "canvas": {"width": width, "height": height},
        "side": "right",
        "fingers": {
            "index": {
                "polygon": [[331,180],[333,177],[337,176],[341,178],[345,183],[347,193],[347,204],[344,211],[340,211],[337,206],[335,195],[332,190]],
                "pivot": [343,207],
            },
            "middle": {
                "polygon": [[344,176],[347,173],[351,174],[355,180],[358,191],[358,203],[356,209],[351,211],[347,205],[346,193]],
                "pivot": [355,205],
            },
            "ring": {
                "polygon": [[356,174],[359,171],[363,173],[367,181],[370,190],[371,199],[368,205],[363,207],[359,201],[357,190]],
                "pivot": [367,201],
            },
            "little": {
                "polygon": [[367,171],[370,169],[374,171],[377,179],[379,187],[379,192],[375,195],[371,191],[369,183]],
                "pivot": [376,190],
            },
        },
    }
    finger_path = reference_dir / "finger-regions.json"
    finger_path.write_text(json.dumps(finger_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def prepare(source_path: Path, neutral_reference: Path | None, output_dir: Path, reference_dir: Path) -> dict[str, Any]:
    with Image.open(source_path) as opened:
        source = opened.convert("RGBA")
    # This reference is already a tight full-body crop. For a larger source,
    # use its alpha silhouette to crop, retaining enough padding for the bow.
    alpha_box = source.getchannel("A").getbbox()
    if alpha_box is None:
        raise ValueError("The full-body performance reference is fully transparent.")
    if source.width > 800 or source.height > 1200:
        padding = 8
        x0, y0, x1, y1 = alpha_box
        source = source.crop((max(0, x0-padding), max(0, y0-padding),
                              min(source.width, x1+padding), min(source.height, y1+padding)))
    if source.height < 500 or source.width < 280:
        raise ValueError("The full-body performance source is too small for a production rig.")
    output_dir.mkdir(parents=True, exist_ok=True)
    master_path = output_dir / "master-character.webp"
    source.save(master_path, "WEBP", quality=94, method=6)
    manifest = build_props(source, reference_dir)

    neutral_metrics = {"provided": False}
    if neutral_reference is not None:
        with Image.open(neutral_reference) as opened:
            neutral = opened.convert("RGBA")
        neutral_bbox = neutral.getchannel("A").getbbox()
        if neutral_bbox is None:
            raise ValueError("The neutral A-pose reference is fully transparent.")
        neutral_metrics = {
            "provided": True,
            "width": neutral.width,
            "height": neutral.height,
            "visible_subject_bbox": list(neutral_bbox),
        }

    report = {
        "status": "full_body_reference_prepared",
        "master_source": master_path.name,
        "canvas": {"width": source.width, "height": source.height},
        "neutral_apose_reference": neutral_metrics,
        "props": {
            name: {
                "src": item["src"], "x": item["x"], "y": item["y"],
                "width": item["width"], "height": item["height"],
            }
            for name, item in manifest["props"].items()
        },
        "publishing": "disabled",
        "preview_only": True,
    }
    (output_dir / "reference-preparation-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True)
    parser.add_argument("--neutral-reference", default="")
    parser.add_argument("--output", required=True)
    parser.add_argument("--reference-dir", required=True)
    args = parser.parse_args()
    neutral = Path(args.neutral_reference).resolve() if args.neutral_reference else None
    result = prepare(
        Path(args.source).resolve(strict=True), neutral,
        Path(args.output).resolve(), Path(args.reference_dir).resolve(strict=True)
    )
    print("FULL_BODY_REFERENCE_RESULT=" + json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
