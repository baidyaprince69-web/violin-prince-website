"""Extract modular head plates and a review catalogue from magenta-backed reference sheets.

The first sheet is intentionally catalogued without guessing anatomical labels.
Expressions and head angles are assigned only where their left-to-right ordering
is explicit in the supplied sheets. Every generated plate remains review-only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from PIL import Image, ImageDraw

from character_rig import validate_character_spec


EXPRESSION_ORDER = ("happy", "focused", "surprised", "neutral")
HEAD_ANGLE_ORDER = ("front", "three_quarter", "profile_right", "profile_left")

# The rigging sheet is a labelled visual catalogue, not a pixel-aligned rig.
# These semantic labels were assigned from the contact-sheet order; they
# describe what each crop depicts and do not cause automatic layer replacement.
REFERENCE_PART_ROLE_MAP = {
    1: ("head_portrait", "head", "high"),
    2: ("hair_shape", "head", "high"),
    3: ("jacket_torso", "torso", "high"),
    4: ("sleeve_panel", "arm_costume_reference", "medium"),
    5: ("sleeve_panel", "arm_costume_reference", "medium"),
    6: ("sleeve_panel", "arm_costume_reference", "medium"),
    7: ("eye_detail", "face", "high"),
    8: ("eye_detail", "face", "high"),
    9: ("nose_detail", "face", "high"),
    10: ("eye_detail", "face", "high"),
    11: ("eye_detail", "face", "high"),
    12: ("jacket_torso_variant", "torso", "high"),
    13: ("nose_detail", "face", "high"),
    14: ("trouser_lower_leg", "leg_costume_reference", "medium"),
    15: ("trouser_lower_leg", "leg_costume_reference", "medium"),
    16: ("trouser_lower_leg", "leg_costume_reference", "medium"),
    17: ("hand_pose", "hand_pose_reference", "high"),
    18: ("hand_pose", "hand_pose_reference", "high"),
    19: ("hand_pose", "hand_pose_reference", "high"),
    20: ("hand_pose", "hand_pose_reference", "high"),
    21: ("hand_pose", "hand_pose_reference", "high"),
    22: ("hand_pose", "hand_pose_reference", "high"),
    23: ("hand_pose", "hand_pose_reference", "high"),
    24: ("trouser_waist", "pelvis_costume_reference", "high"),
    25: ("violin_prop", "violin", "high"),
    26: ("bow_prop", "bow", "high"),
    27: ("trouser_thigh", "thigh_costume_reference", "medium"),
    28: ("trouser_thigh", "thigh_costume_reference", "medium"),
    29: ("trouser_waist_variant", "pelvis_costume_reference", "high"),
    30: ("trouser_leg", "leg_costume_reference", "medium"),
    31: ("trouser_leg", "leg_costume_reference", "medium"),
    32: ("shoe", "foot_costume_reference", "high"),
    33: ("shoe", "foot_costume_reference", "high"),
}


def _reference_part_mapping(part_number: int) -> dict[str, str]:
    reference_role, suggested_rig_role, confidence = REFERENCE_PART_ROLE_MAP.get(
        int(part_number),
        ("unclassified_reference_part", "manual_review", "low"),
    )
    return {
        "reference_role": reference_role,
        "suggested_rig_role": suggested_rig_role,
        "mapping_confidence": confidence,
        "use_policy": "reference_only_until_manual_alignment_review",
    }


class ReferenceSheetError(ValueError):
    """Raised when a reference sheet cannot be separated reliably."""


def _keyed_sheet(path: str | Path) -> tuple[Image.Image, np.ndarray]:
    with Image.open(Path(path).resolve(strict=True)) as opened:
        image = opened.convert("RGBA")
    rgba = np.asarray(image, dtype=np.uint8)
    rgb = rgba[:, :, :3].astype(np.int16)
    height, width = rgb.shape[:2]

    border = np.concatenate((
        rgb[:8, :, :].reshape(-1, 3),
        rgb[-8:, :, :].reshape(-1, 3),
        rgb[:, :8, :].reshape(-1, 3),
        rgb[:, -8:, :].reshape(-1, 3),
    ), axis=0)
    key = np.median(border, axis=0)
    distance = np.sqrt(np.sum((rgb - key) ** 2, axis=2))

    red, green, blue = rgb[:, :, 0], rgb[:, :, 1], rgb[:, :, 2]
    magenta_like = (
        (red > 125) & (blue > 125) &
        (green < 170) & ((red - green) > 48) & ((blue - green) > 48)
    )
    # The sheet's anti-aliased guide contour ranges from bright magenta
    # to very dark purple. Detect it by hue/saturation, not RGB brightness.
    hsv = cv2.cvtColor(rgba[:, :, :3], cv2.COLOR_RGB2HSV)
    hue, saturation, value = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
    purple_guide = (
        (hue >= 125) & (hue <= 177) &
        (saturation >= 80) & (value >= 30)
    )
    guide_pixels = magenta_like | purple_guide
    alpha = np.full((height, width), 255, dtype=np.uint8)
    keyed_alpha = np.clip((distance - 22.0) * (255.0 / 48.0), 0, 255)
    alpha[guide_pixels] = 0
    alpha = np.minimum(alpha, rgba[:, :, 3])
    return image, alpha


def _components(path: str | Path, *, minimum_area: int) -> list[dict[str, Any]]:
    image, alpha = _keyed_sheet(path)
    binary = (alpha > 18).astype(np.uint8)
    kernel = np.ones((3, 3), dtype=np.uint8)
    binary = cv2.morphologyEx(binary, cv2.MORPH_CLOSE, kernel)
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(binary, 8)
    results = []
    for label in range(1, count):
        x, y, width, height, area = [int(value) for value in stats[label]]
        if area < minimum_area:
            continue
        results.append({
            "label": label,
            "bbox": (x, y, width, height),
            "area": area,
            "image": image,
            "alpha": alpha,
            "labels": labels,
        })
    results.sort(key=lambda item: (item["bbox"][1], item["bbox"][0]))
    return results


def _save_component(component: dict[str, Any], destination: Path) -> dict[str, Any]:
    x, y, width, height = component["bbox"]
    labels = component["labels"][y:y + height, x:x + width]
    alpha = component["alpha"][y:y + height, x:x + width]
    matte = np.where(labels == component["label"], alpha, 0).astype(np.uint8)
    crop = component["image"].crop((x, y, x + width, y + height))
    crop.putalpha(Image.fromarray(matte, mode="L"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    crop.save(destination, format="PNG", optimize=True)
    return {
        "src": destination.name,
        "bbox": [x, y, x + width, y + height],
        "width": width,
        "height": height,
        "pixel_area": int(component["area"]),
    }


def _four_ordered_components(
    path: str | Path,
    *,
    minimum_area_ratio: float,
    top_region_ratio: float | None = None,
) -> list[dict[str, Any]]:
    with Image.open(Path(path).resolve(strict=True)) as opened:
        width, height = opened.size
    minimum_area = max(1200, int(width * height * minimum_area_ratio))
    components = _components(path, minimum_area=minimum_area)
    if top_region_ratio is not None:
        components = [
            item for item in components
            if item["bbox"][1] + item["bbox"][3] / 2 <= height * top_region_ratio
        ]
    components.sort(key=lambda item: item["area"], reverse=True)
    selected = components[:4]
    if len(selected) != 4:
        raise ReferenceSheetError(
            f"Expected four separated large subjects in {Path(path).name}; "
            f"found {len(selected)}. Inspect the magenta key and component separation."
        )
    selected.sort(key=lambda item: item["bbox"][0])
    return selected


def _head_plate_bounds(character: dict[str, Any]) -> dict[str, float]:
    head_layers = [
        layer for layer in character.get("layers", [])
        if layer.get("role") in {"head", "face"}
    ]
    if not head_layers:
        raise ReferenceSheetError("The base rig has no head or face layers for alignment.")
    x0 = min(float(layer["x"]) for layer in head_layers)
    y0 = min(float(layer["y"]) for layer in head_layers)
    x1 = max(float(layer["x"]) + float(layer["width"]) for layer in head_layers)
    y1 = max(float(layer["y"]) + float(layer["height"]) for layer in head_layers)
    pad_x = max(2.0, (x1 - x0) * 0.04)
    pad_y = max(2.0, (y1 - y0) * 0.04)
    return {
        "x": max(0.0, x0 - pad_x),
        "y": max(0.0, y0 - pad_y),
        "width": min(float(character["canvas"]["width"]), x1 + pad_x) - max(0.0, x0 - pad_x),
        "height": min(float(character["canvas"]["height"]), y1 + pad_y) - max(0.0, y0 - pad_y),
        "pivot_x": 0.5,
        "pivot_y": 0.92,
        "z_index": 85,
    }


def _write_component_contact_sheet(
    component_records: list[dict[str, Any]],
    destination: Path,
) -> None:
    columns = 5
    cell_width, cell_height = 190, 220
    rows = max(1, (len(component_records) + columns - 1) // columns)
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), (19, 27, 40))
    draw = ImageDraw.Draw(sheet)
    for index, record in enumerate(component_records):
        row, column = divmod(index, columns)
        x, y = column * cell_width, row * cell_height
        with Image.open(record["path"]) as opened:
            part = opened.convert("RGBA")
        part.thumbnail((cell_width - 16, cell_height - 42), Image.Resampling.LANCZOS)
        tile = Image.new("RGBA", part.size, (31, 42, 58, 255))
        tile.alpha_composite(part)
        sheet.paste(tile.convert("RGB"), (x + (cell_width - part.width) // 2, y + 38))
        draw.text((x + 8, y + 6), record["part_id"], fill=(245, 238, 224))
        draw.text(
            (x + 8, y + 19),
            str(record.get("reference_role") or "unclassified"),
            fill=(160, 190, 210),
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(destination, format="PNG", optimize=True)


def build_reference_sheet_rig(
    character_path: str | Path,
    bundle_dir: str | Path,
    *,
    rigging_sheet_path: str | Path,
    expression_sheet_path: str | Path,
    head_angle_sheet_path: str | Path,
) -> dict[str, Any]:
    character_path = Path(character_path).resolve(strict=True)
    bundle = Path(bundle_dir).resolve(strict=True)
    character = json.loads(character_path.read_text(encoding="utf-8"))

    # Extract independent components from the general rigging sheet. They are
    # catalogued for review rather than assigned to limbs by an unverified guess.
    with Image.open(Path(rigging_sheet_path).resolve(strict=True)) as opened:
        parts_width, parts_height = opened.size
    components = _components(
        rigging_sheet_path,
        minimum_area=max(180, int(parts_width * parts_height * 0.00004)),
    )
    if not components:
        raise ReferenceSheetError("No foreground components were detected in the character-parts sheet.")
    part_records = []
    for index, component in enumerate(components, start=1):
        part_id = f"reference-part-{index:03d}"
        destination = bundle / f"{part_id}.png"
        geometry = _save_component(component, destination)
        mapping = _reference_part_mapping(index)
        part_records.append({
            "part_id": part_id,
            "path": destination,
            "source_bbox": geometry["bbox"],
            "source_pixel_area": geometry["pixel_area"],
            **mapping,
        })
    _write_component_contact_sheet(
        part_records, bundle / "reference-parts-contact-sheet.png"
    )

    expression_components = _four_ordered_components(
        expression_sheet_path, minimum_area_ratio=0.012
    )
    angle_components = _four_ordered_components(
        head_angle_sheet_path,
        minimum_area_ratio=0.009,
        top_region_ratio=0.62,
    )
    head_bounds = _head_plate_bounds(character)

    head_variants = {}
    for name, component in zip(EXPRESSION_ORDER, expression_components, strict=True):
        filename = f"head-variant-{name}.png"
        _save_component(component, bundle / filename)
        head_variants[name] = {"src": filename, **head_bounds}

    head_angles = {}
    for name, component in zip(HEAD_ANGLE_ORDER, angle_components, strict=True):
        filename = f"head-angle-{name}.png"
        _save_component(component, bundle / filename)
        head_angles[name] = {"src": filename, **head_bounds}

    character["head_plate_bounds"] = head_bounds
    character["head_variants"] = head_variants
    character["head_angles"] = head_angles
    character = validate_character_spec(character)
    character_path.write_text(
        json.dumps(character, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    report = {
        "status": "modular_head_plates_and_reference_catalogue_created",
        "head_variant_names": list(head_variants),
        "head_angle_names": list(head_angles),
        "head_plate_bounds": head_bounds,
        "reference_part_count": len(part_records),
        "reference_parts": [
            {
                "part_id": item["part_id"],
                "source_bbox": item["source_bbox"],
                "source_pixel_area": item["source_pixel_area"],
                "reference_role": item["reference_role"],
                "suggested_rig_role": item["suggested_rig_role"],
                "mapping_confidence": item["mapping_confidence"],
                "use_policy": item["use_policy"],
            }
            for item in part_records
        ],
        "reference_parts_mapping": "curated_role_catalogue_review_only",
        "reference_part_mapping_file": "reference-part-map.json",
        "alignment": "head plates use shared head anchors; modular body assets remain reference-only pending manual joint alignment",
        "automatic_body_part_replacement": False,
        "magenta_key": "magenta/purple guide pixels removed by hue and saturation; source alpha preserved",
        "visual_review_required": True,
        "publishing": "disabled",
    }
    (bundle / "reference-sheets-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    mapping_payload = {
        "schema_version": 1,
        "source_sheet": Path(rigging_sheet_path).name,
        "alignment_policy": "reference_only_until_manual_alignment_review",
        "automatic_body_part_replacement": False,
        "parts": [
            {
                "part_id": item["part_id"],
                "src": Path(item["path"]).name,
                "source_bbox": item["source_bbox"],
                "source_pixel_area": item["source_pixel_area"],
                "reference_role": item["reference_role"],
                "suggested_rig_role": item["suggested_rig_role"],
                "mapping_confidence": item["mapping_confidence"],
                "use_policy": item["use_policy"],
            }
            for item in part_records
        ],
    }
    (bundle / "reference-part-map.json").write_text(
        json.dumps(mapping_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report
