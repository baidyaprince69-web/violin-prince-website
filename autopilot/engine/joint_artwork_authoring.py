"""Prepare source-aligned lower-body joint artwork for manual artist review.

The tool creates magnified source crops and an empty polygon-authoring template.
It never paints replacement pixels or edits the rig's original limb assets.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

from full_body_performance_rig import _canvas_alpha_mask_for_layer


LOWER_BODY_JOINTS = (
    "left_hip", "right_hip",
    "left_knee", "right_knee",
    "left_ankle", "right_ankle",
)


def build_joint_artwork_review_pack(
    source_path: str | Path,
    bundle_dir: str | Path,
    regions_path: str | Path,
    output_dir: str | Path,
    *,
    crop_radius: int = 54,
    scale: int = 4,
) -> dict[str, Any]:
    """Create a contact sheet and blank, source-coordinate polygon template."""
    source_path = Path(source_path).resolve(strict=True)
    bundle = Path(bundle_dir).resolve(strict=True)
    output = Path(output_dir).resolve()
    output.mkdir(parents=True, exist_ok=True)

    with Image.open(source_path) as opened:
        source = opened.convert("RGBA")
    source_pixels = np.asarray(source, dtype=np.uint8)
    canvas_width, canvas_height = source.size

    character_path = bundle / "character.json"
    if not character_path.is_file():
        raise FileNotFoundError("The rig bundle is missing character.json.")
    character = json.loads(character_path.read_text(encoding="utf-8"))
    if character.get("canvas") != {"width": canvas_width, "height": canvas_height}:
        raise ValueError("The source artwork and rig canvas dimensions do not match.")

    regions = json.loads(Path(regions_path).read_text(encoding="utf-8"))
    joint_regions = (regions.get("joint_surfaces") or {}).get("regions") or {}
    joints = character.get("joints") or {}
    layers = {
        str(layer.get("role") or ""): layer
        for layer in character.get("layers", [])
    }

    template: dict[str, Any] = {
        "schema_version": 1,
        "coordinate_space": "absolute_source_pixels_top_left",
        "canvas": {"width": canvas_width, "height": canvas_height},
        "source_artwork": {
            "filename": source_path.name,
            "sha256": hashlib.sha256(source_path.read_bytes()).hexdigest(),
        },
        "authoring_instructions": [
            "Trace the actual clothing or shoe silhouette and fold structure visible in the source crop.",
            "Use artist_source_polygon as absolute [x, y] source-canvas coordinates.",
            "Do not use circles, capsules, ellipses, rounded rectangles or generic joint pads.",
            "The polygon must overlap both named parent_role and child_role source masks.",
            "Mark artwork_status as artist_approved only after visual review of the traced source boundary.",
            "The extraction stage copies original source pixels only; it does not paint or invent texture.",
        ],
        "protected_scope": {
            "included": list(LOWER_BODY_JOINTS),
            "excluded": [
                "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
                "wrists", "hands", "fingers", "bow", "violin",
            ],
            "reason": "Upper-body, arm, forearm, hand, finger and instrument assets are protected in this stage.",
        },
        "joint_surfaces": {
            "schema_version": 1,
            "coordinate_space": "absolute_source_pixels_top_left",
            "regions": {},
        },
    }

    cell_width = crop_radius * 2 * scale
    cell_height = crop_radius * 2 * scale
    label_height = 42
    columns = 3
    rows = (len(LOWER_BODY_JOINTS) + columns - 1) // columns
    sheet = Image.new(
        "RGB",
        (columns * cell_width, rows * (cell_height + label_height)),
        (15, 22, 32),
    )
    draw = ImageDraw.Draw(sheet)
    review_rows: list[dict[str, Any]] = []

    for index, joint_name in enumerate(LOWER_BODY_JOINTS):
        item = joint_regions.get(joint_name)
        if not isinstance(item, dict):
            raise ValueError(f"Performance-region manifest is missing {joint_name}.")
        anchor_name = str(item.get("anchor") or joint_name)
        anchor = joints.get(anchor_name)
        if not isinstance(anchor, dict):
            raise ValueError(f"Rig has no mapped joint anchor for {joint_name}.")
        center_x = float(anchor["x"]) * canvas_width
        center_y = float(anchor["y"]) * canvas_height
        parent_role = str(item.get("parent_role") or "")
        child_role = str(item.get("child_role") or "")
        if parent_role not in layers or child_role not in layers:
            raise ValueError(
                f"{joint_name} references missing body layers: {parent_role}/{child_role}."
            )

        parent_mask = _canvas_alpha_mask_for_layer(
            bundle, layers[parent_role],
            canvas_width=canvas_width, canvas_height=canvas_height,
        )
        child_mask = _canvas_alpha_mask_for_layer(
            bundle, layers[child_role],
            canvas_width=canvas_width, canvas_height=canvas_height,
        )
        cx, cy = int(round(center_x)), int(round(center_y))
        x0, y0 = max(0, cx - crop_radius), max(0, cy - crop_radius)
        x1, y1 = min(canvas_width, cx + crop_radius), min(canvas_height, cy + crop_radius)
        crop = source.crop((x0, y0, x1, y1))
        matte = Image.new("RGBA", crop.size, (25, 31, 42, 255))
        matte.alpha_composite(crop)
        magnified = matte.resize(
            (crop.width * scale, crop.height * scale),
            Image.Resampling.NEAREST,
        )
        overlay = ImageDraw.Draw(magnified, "RGBA")

        for mask, color in (
            (parent_mask, (48, 220, 236, 255)),
            (child_mask, (255, 172, 63, 255)),
        ):
            # _canvas_alpha_mask_for_layer already returns a boolean mask.
            # Comparing booleans with 12 would erase every contour.
            local = mask[y0:y1, x0:x1].astype(np.uint8)
            contours, _ = cv2.findContours(
                local, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            for contour in contours:
                if cv2.contourArea(contour) < 2:
                    continue
                points = [
                    (
                        int(round(float(point[0][0]) * scale)),
                        int(round(float(point[0][1]) * scale)),
                    )
                    for point in contour
                ]
                if len(points) > 1:
                    overlay.line(points + [points[0]], fill=color, width=2)

        anchor_x, anchor_y = (center_x - x0) * scale, (center_y - y0) * scale
        cross = 8 * scale
        overlay.line(
            (anchor_x - cross, anchor_y, anchor_x + cross, anchor_y),
            fill=(255, 70, 70, 255), width=3,
        )
        overlay.line(
            (anchor_x, anchor_y - cross, anchor_x, anchor_y + cross),
            fill=(255, 70, 70, 255), width=3,
        )

        canvas = Image.new("RGB", (cell_width, cell_height), (25, 31, 42))
        canvas.paste(magnified.convert("RGB"), (0, 0))
        column, row = index % columns, index // columns
        px, py = column * cell_width, row * (cell_height + label_height)
        sheet.paste(canvas, (px, py + label_height))
        draw.text(
            (px + 10, py + 5),
            f"{joint_name}  |  {parent_role} → {child_role}",
            fill=(241, 234, 219),
        )
        draw.text(
            (px + 10, py + 24),
            f"anchor ({center_x:.1f}, {center_y:.1f})  | cyan parent · amber child",
            fill=(170, 190, 204),
        )

        template["joint_surfaces"]["regions"][joint_name] = {
            "anchor": anchor_name,
            "anchor_px": [round(center_x, 3), round(center_y, 3)],
            "parent_role": parent_role,
            "child_role": child_role,
            "z_index": int(item.get("z_index", 20)),
            "minimum_pixels": int(item.get("minimum_pixels", 80)),
            "blend_axis_joints": list(item.get("blend_axis_joints") or []),
            "blend_axis_half_length_px": 18,
            "artist_source_polygon": [],
            "artwork_status": "awaiting_artist_alignment",
        }
        review_rows.append({
            "joint": joint_name,
            "parent_role": parent_role,
            "child_role": child_role,
            "anchor_px": [round(center_x, 3), round(center_y, 3)],
            "crop_bounds": [x0, y0, x1, y1],
            "parent_source_pixels": int(parent_mask[y0:y1, x0:x1].sum()),
            "child_source_pixels": int(child_mask[y0:y1, x0:x1].sum()),
        })

    sheet_path = output / "joint-artwork-contact-sheet.jpg"
    sheet.save(sheet_path, format="JPEG", quality=95, optimize=True)
    template_path = output / "joint-artwork-template.json"
    template_path.write_text(
        json.dumps(template, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = {
        "status": "review_pack_created",
        "source_dimensions": [canvas_width, canvas_height],
        "source_sha256": template["source_artwork"]["sha256"],
        "joint_count": len(review_rows),
        "joint_names": list(LOWER_BODY_JOINTS),
        "contact_sheet": sheet_path.name,
        "template": template_path.name,
        "production_art_assets_created": 0,
        "rig_layers_modified": 0,
        "original_source_pixels_modified": 0,
        "upper_body_and_hand_assets_touched": False,
        "joints": review_rows,
        "limitation": (
            "This is an artist-alignment pack, not approved joint artwork. "
            "The rig must continue deferring joint surfaces until reviewed "
            "artist_source_polygon masks are supplied."
        ),
    }
    (output / "joint-artwork-review-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--regions", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    args = parser.parse_args()
    report = build_joint_artwork_review_pack(
        args.source, args.bundle, args.regions, args.out_dir
    )
    print(json.dumps({
        "status": report["status"],
        "joint_count": report["joint_count"],
        "production_art_assets_created": report["production_art_assets_created"],
        "contact_sheet": report["contact_sheet"],
        "template": report["template"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
