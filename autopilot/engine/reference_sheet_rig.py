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


REFERENCE_PART_ALIGNMENT_RULES = {
    1:  {"target_kind": "layer", "target_role": "head", "group": "head", "variant": "head_portrait_with_neck", "canvas_box": [116, -8, 127, 154], "source_crop_ratio": [0.0, 0.0, 1.0, 0.75], "rotation_deg": 0, "assembly_z": 90},
    2:  {"target_kind": "layer", "target_role": "head", "group": "hair", "variant": "hair_overlay_alternative", "target_region": [0.04, 0.00, 0.92, 0.42], "rotation_deg": 0},
    3:  {"target_kind": "layer", "target_role": "torso", "group": "torso", "variant": "jacket_primary", "canvas_box": [76, 122, 190, 285], "rotation_deg": 0, "assembly_z": 40},
    4:  {"target_kind": "layer", "target_role": "left_upper_arm", "group": "sleeve", "variant": "left_sleeve_candidate", "canvas_box": [20, 141, 110, 145], "rotation_deg": -16, "assembly_z": 50},
    5:  {"target_kind": "layer", "target_role": "right_upper_arm", "group": "sleeve", "variant": "right_sleeve_candidate", "canvas_box": [216, 137, 110, 164], "rotation_deg": -42, "assembly_z": 50},
    6:  {"target_kind": "layer", "target_role": "left_forearm", "group": "sleeve", "variant": "left_forearm_sleeve_candidate", "canvas_box": [4, 215, 160, 64], "rotation_deg": 90, "assembly_z": 51},
    7:  {"target_kind": "layer", "target_role": "face", "group": "eye", "variant": "left_eye_open", "target_region": [0.08, 0.12, 0.38, 0.32], "rotation_deg": 0},
    8:  {"target_kind": "layer", "target_role": "face", "group": "eye", "variant": "right_eye_open", "target_region": [0.54, 0.12, 0.38, 0.32], "rotation_deg": 0},
    9:  {"target_kind": "layer", "target_role": "face", "group": "nose", "variant": "nose_primary", "target_region": [0.36, 0.34, 0.28, 0.46], "rotation_deg": 0},
    10: {"target_kind": "layer", "target_role": "face", "group": "eye", "variant": "left_eye_alternative", "target_region": [0.08, 0.12, 0.38, 0.32], "rotation_deg": 0},
    11: {"target_kind": "layer", "target_role": "face", "group": "eye", "variant": "right_eye_alternative", "target_region": [0.54, 0.12, 0.38, 0.32], "rotation_deg": 0},
    12: {"target_kind": "layer", "target_role": "torso", "group": "torso", "variant": "jacket_alternative", "target_region": [0.16, 0.02, 0.68, 0.96], "rotation_deg": 0},
    13: {"target_kind": "layer", "target_role": "face", "group": "nose", "variant": "nose_alternative", "target_region": [0.36, 0.34, 0.28, 0.46], "rotation_deg": 0},
    14: {"target_kind": "layer", "target_role": "left_calf", "group": "lower_leg", "variant": "left_lower_leg_alternative_a", "rotation_deg": 0},
    15: {"target_kind": "layer", "target_role": "right_calf", "group": "lower_leg", "variant": "right_lower_leg_alternative_a", "rotation_deg": 0},
    16: {"target_kind": "layer", "target_role": "left_calf", "group": "lower_leg", "variant": "lower_leg_alternative_b", "rotation_deg": 0},
    17: {"target_kind": "layer", "target_role": "left_hand", "group": "hand_pose", "variant": "left_open_hand", "rotation_deg": 0},
    18: {"target_kind": "layer", "target_role": "right_hand", "group": "hand_pose", "variant": "right_open_hand", "rotation_deg": 0},
    19: {"target_kind": "layer", "target_role": "left_hand", "group": "hand_pose", "variant": "left_cupped_hand", "rotation_deg": 0},
    20: {"target_kind": "layer", "target_role": "right_hand", "group": "hand_pose", "variant": "right_cupped_hand", "rotation_deg": 0},
    21: {"target_kind": "layer", "target_role": "left_hand", "group": "hand_pose", "variant": "left_grip_hand", "rotation_deg": 0},
    22: {"target_kind": "layer", "target_role": "right_hand", "group": "hand_pose", "variant": "right_fingerboard_hand", "rotation_deg": 0},
    23: {"target_kind": "layer", "target_role": "left_hand", "group": "hand_pose", "variant": "left_bow_grip_alternative", "rotation_deg": 0},
    24: {"target_kind": "layer", "target_role": "torso", "group": "waist", "variant": "waist_primary", "canvas_box": [84, 372, 172, 78], "rotation_deg": 0, "assembly_z": 30},
    25: {"target_kind": "prop", "target_prop": "violin", "group": "instrument", "variant": "reference_violin", "rotation_deg": -90},
    26: {"target_kind": "prop", "target_prop": "bow", "group": "instrument", "variant": "reference_bow", "rotation_deg": -29},
    27: {"target_kind": "layer", "target_role": "left_thigh", "group": "thigh", "variant": "left_thigh_primary", "rotation_deg": 0},
    28: {"target_kind": "layer", "target_role": "right_thigh", "group": "thigh", "variant": "right_thigh_primary", "rotation_deg": 0},
    29: {"target_kind": "layer", "target_role": "torso", "group": "waist", "variant": "waist_alternative", "target_region": [0.08, 0.72, 0.84, 0.28], "rotation_deg": 0},
    30: {"target_kind": "layer", "target_role": "left_calf", "group": "lower_leg", "variant": "left_lower_leg_primary", "rotation_deg": 0},
    31: {"target_kind": "layer", "target_role": "right_calf", "group": "lower_leg", "variant": "right_lower_leg_primary", "rotation_deg": 0},
    32: {"target_kind": "layer", "target_role": "left_foot", "group": "shoe", "variant": "left_shoe", "rotation_deg": 0},
    33: {"target_kind": "layer", "target_role": "right_foot", "group": "shoe", "variant": "right_shoe", "rotation_deg": 0},
}


def _reference_part_mapping(part_number: int) -> dict[str, Any]:
    reference_role, suggested_rig_role, confidence = REFERENCE_PART_ROLE_MAP.get(
        int(part_number),
        ("unclassified_reference_part", "manual_review", "low"),
    )
    return {
        "reference_role": reference_role,
        "suggested_rig_role": suggested_rig_role,
        "mapping_confidence": confidence,
        "alignment_rule": dict(REFERENCE_PART_ALIGNMENT_RULES.get(int(part_number), {})),
        "use_policy": "alignment_candidate_created_pending_visual_review",
    }


def _reference_part_alignment_candidates(
    part_records: list[dict[str, Any]],
    character: dict[str, Any],
) -> list[dict[str, Any]]:
    """Compute explicit fit transforms without activating unreviewed body art."""
    layer_by_role = {
        str(layer.get("role") or ""): layer
        for layer in character.get("layers", [])
    }
    props = character.get("props") or {}
    canvas = character.get("canvas") or {}
    canvas_width = float(canvas.get("width", 0))
    canvas_height = float(canvas.get("height", 0))
    candidates = []
    for item in part_records:
        number = int(str(item["part_id"]).rsplit("-", 1)[-1])
        rule = dict(REFERENCE_PART_ALIGNMENT_RULES.get(number, {}))
        target_kind = str(rule.get("target_kind") or "layer")
        target_role = str(rule.get("target_role") or item.get("suggested_rig_role") or "manual_review")
        if target_kind == "prop":
            target_id = str(rule.get("target_prop") or "")
            target = props.get(target_id)
            target_source = f"props.{target_id}"
        else:
            target_id = target_role
            target = layer_by_role.get(target_role)
            target_source = f"layers.role:{target_role}"
        target_available = isinstance(target, dict)
        direct_box = rule.get("canvas_box")
        if isinstance(direct_box, list) and len(direct_box) == 4:
            tx, ty, tw, th = [float(value) for value in direct_box]
            target_source = "character.canvas.manual_alignment_box"
            target_available = canvas_width > 0 and canvas_height > 0
        elif target_available:
            tx, ty = float(target.get("x", 0)), float(target.get("y", 0))
            tw, th = float(target.get("width", 1)), float(target.get("height", 1))
            region = rule.get("target_region")
            if isinstance(region, list) and len(region) == 4:
                rx, ry, rw, rh = [float(value) for value in region]
                original_width, original_height = tw, th
                tx, ty = tx + original_width * rx, ty + original_height * ry
                tw, th = original_width * rw, original_height * rh
        else:
            tx, ty, tw, th = 0.0, 0.0, canvas_width, canvas_height

        source_width = float(item["source_bbox"][2] - item["source_bbox"][0])
        source_height = float(item["source_bbox"][3] - item["source_bbox"][1])
        source_crop = None
        crop_ratio = rule.get("source_crop_ratio")
        if isinstance(crop_ratio, list) and len(crop_ratio) == 4:
            rx, ry, rw, rh = [float(value) for value in crop_ratio]
            source_crop = [
                max(0, int(round(source_width * rx))),
                max(0, int(round(source_height * ry))),
                min(int(source_width), int(round(source_width * (rx + rw)))),
                min(int(source_height), int(round(source_height * (ry + rh)))),
            ]
            source_width = max(1, source_crop[2] - source_crop[0])
            source_height = max(1, source_crop[3] - source_crop[1])
        rotation = float(rule.get("rotation_deg", 0))
        radians = np.deg2rad(rotation)
        rotated_width = abs(source_width * float(np.cos(radians))) + abs(source_height * float(np.sin(radians)))
        rotated_height = abs(source_width * float(np.sin(radians))) + abs(source_height * float(np.cos(radians)))
        scale = min(tw / max(rotated_width, 1.0), th / max(rotated_height, 1.0))
        placed_width, placed_height = rotated_width * scale, rotated_height * scale
        x, y = tx + (tw - placed_width) / 2, ty + (th - placed_height) / 2
        candidates.append({
            "part_id": item["part_id"],
            "src": Path(item["path"]).name,
            "target_kind": target_kind,
            "target_id": target_id,
            "target_role": target_role,
            "target_source": target_source,
            "target_geometry_available": target_available,
            "target_box": [round(tx, 3), round(ty, 3), round(tw, 3), round(th, 3)],
            "target_region": rule.get("target_region"),
            "source_crop_px": source_crop,
            "group": str(rule.get("group") or "unclassified"),
            "variant": str(rule.get("variant") or item["part_id"]),
            "rotation_deg": rotation,
            "assembly_z": int(rule.get("assembly_z", 40)),
            "fit_policy": "contain_preserving_aspect_after_rotation",
            "candidate_transform": {
                "x": round(x, 3), "y": round(y, 3),
                "width": round(placed_width, 3), "height": round(placed_height, 3),
                "scale": round(scale, 6), "rotation_deg": rotation,
                "pivot": [0.5, 0.5],
            },
            "alignment_status": "candidate_not_active",
        })
    return candidates


def _alpha_composite_clipped(destination: Image.Image, source: Image.Image, x: int, y: int) -> None:
    """Alpha-composite source at x/y, safely clipping outside the destination."""
    left, top = max(0, int(x)), max(0, int(y))
    right, bottom = min(destination.width, int(x) + source.width), min(destination.height, int(y) + source.height)
    if right <= left or bottom <= top:
        return
    sx, sy = left - int(x), top - int(y)
    destination.alpha_composite(source.crop((sx, sy, sx + right - left, sy + bottom - top)), (left, top))


def _write_reference_part_alignment_preview(
    part_records: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    bundle: Path,
) -> str:
    """Compare each candidate cut-out over its proposed source-aligned target crop."""
    source_path = bundle / "preserved-full-body-source.png"
    source = None
    if source_path.is_file():
        with Image.open(source_path) as opened:
            source = opened.convert("RGBA")
    columns, cell_width, cell_height = 4, 250, 190
    rows = max(1, (len(part_records) + columns - 1) // columns)
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), (18, 27, 41))
    draw = ImageDraw.Draw(sheet)
    by_candidate = {item["part_id"]: item for item in candidates}
    for index, item in enumerate(part_records):
        part_id = item["part_id"]
        candidate = by_candidate[part_id]
        row, column = divmod(index, columns)
        left, top = column * cell_width, row * cell_height
        draw.text((left + 8, top + 5), f"{part_id}  {candidate['target_role']}", fill=(245, 238, 224))
        draw.text((left + 8, top + 19), f"{candidate['group']} / {candidate['variant']}", fill=(150, 190, 214))
        tx, ty, tw, th = candidate["target_box"]
        preview = Image.new("RGBA", (max(1, int(round(tw))), max(1, int(round(th)))), (30, 42, 60, 255))
        if source is not None:
            sx0, sy0 = max(0, int(round(tx))), max(0, int(round(ty)))
            sx1, sy1 = min(source.width, int(round(tx + tw))), min(source.height, int(round(ty + th)))
            if sx1 > sx0 and sy1 > sy0:
                preview.alpha_composite(source.crop((sx0, sy0, sx1, sy1)), (sx0 - int(round(tx)), sy0 - int(round(ty))))
        part = Image.open(item["path"]).convert("RGBA")
        if candidate.get("source_crop_px"):
            part = part.crop(tuple(int(value) for value in candidate["source_crop_px"]))
        angle = float(candidate["rotation_deg"])
        if angle:
            part = part.rotate(angle, expand=True, resample=Image.Resampling.BICUBIC)
        transform = candidate["candidate_transform"]
        part = part.resize((
            max(1, int(round(transform["width"]))),
            max(1, int(round(transform["height"]))),
        ), Image.Resampling.LANCZOS)
        part.putalpha(part.getchannel("A").point(lambda value: int(value * 0.62)))
        _alpha_composite_clipped(preview, part, int(round(transform["x"] - tx)), int(round(transform["y"] - ty)))
        preview.thumbnail((cell_width - 16, cell_height - 48), Image.Resampling.LANCZOS)
        sheet.paste(preview.convert("RGB"), (left + (cell_width - preview.width) // 2, top + 38))
        draw.text(
            (left + 8, top + cell_height - 17),
            "TARGET FOUND" if candidate["target_geometry_available"] else "TARGET ROLE MISSING",
            fill=(130, 220, 166) if candidate["target_geometry_available"] else (238, 170, 110),
        )
    destination = bundle / "reference-part-alignment-review.jpg"
    sheet.save(destination, format="JPEG", quality=93)
    return destination.name


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


def _catalogue_facial_components(
    sheet_path: str | Path,
    bundle: Path,
    *,
    minimum_area: int = 55,
    maximum_area: int = 16000,
) -> tuple[list[dict[str, Any]], str]:
    """Extract separate eye, lid, brow, mouth, nose and accessory components."""
    components = [
        item for item in _components(sheet_path, minimum_area=minimum_area)
        if item["area"] <= maximum_area
    ]
    if not components:
        raise ReferenceSheetError("No separate facial feature components were detected.")

    records = []
    for index, component in enumerate(components, start=1):
        part_id = f"facial-part-{index:03d}"
        destination = bundle / f"{part_id}.png"
        geometry = _save_component(component, destination)
        x, y, width, height = geometry["bbox"]
        center_x, center_y = x + width / 2, y + height / 2
        if center_y >= 390 and center_x < 470:
            zone = "mouth_feature_bank"
        elif center_y >= 390 and center_x < 850:
            zone = "eyelid_feature_bank"
        elif center_x >= 860 and center_y < 390:
            zone = "brow_eye_expression_bank"
        elif center_x >= 1100:
            zone = "nose_glasses_accessory_bank"
        else:
            zone = "unclassified_face_feature"
        records.append({
            "part_id": part_id,
            "path": destination,
            "source_bbox": geometry["bbox"],
            "width": geometry["width"],
            "height": geometry["height"],
            "pixel_area": geometry["pixel_area"],
            "source_zone": zone,
        })

    columns, cell_width, cell_height = 5, 190, 175
    rows = max(1, (len(records) + columns - 1) // columns)
    sheet = Image.new("RGB", (columns * cell_width, rows * cell_height), (19, 27, 40))
    draw = ImageDraw.Draw(sheet)
    for index, record in enumerate(records):
        row, column = divmod(index, columns)
        x, y = column * cell_width, row * cell_height
        with Image.open(record["path"]) as opened:
            part = opened.convert("RGBA")
        part.thumbnail((cell_width - 16, cell_height - 52), Image.Resampling.LANCZOS)
        tile = Image.new("RGBA", part.size, (31, 42, 58, 255))
        tile.alpha_composite(part)
        sheet.paste(tile.convert("RGB"), (x + (cell_width - part.width) // 2, y + 35))
        draw.text((x + 7, y + 5), record["part_id"], fill=(245, 238, 224))
        draw.text((x + 7, y + 19), record["source_zone"], fill=(160, 190, 210))
        draw.text((x + 7, y + cell_height - 14), str(record["source_bbox"]), fill=(190, 205, 220))
    contact_path = bundle / "facial-parts-contact-sheet.png"
    sheet.save(contact_path, format="PNG", optimize=True)
    return records, contact_path.name


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


def _save_neck_anchored_head_plate(
    component: dict[str, Any],
    destination: Path,
    bounds: dict[str, float],
) -> dict[str, Any]:
    """Normalize a head plate to one shared canvas and neck pivot.

    This removes per-image scale/placement jumps between supplied plates. It
    does not create a continuous 3D turn or replace missing anatomical artwork.
    """
    geometry = _save_component(component, destination)
    with Image.open(destination) as opened:
        plate = opened.convert("RGBA")

    target_width = max(1, int(round(float(bounds["width"]))))
    target_height = max(1, int(round(float(bounds["height"]))))
    scale = min(target_width / plate.width, target_height / plate.height)
    scaled_width = max(1, min(target_width, int(round(plate.width * scale))))
    scaled_height = max(1, min(target_height, int(round(plate.height * scale))))
    resized = plate.resize(
        (scaled_width, scaled_height),
        Image.Resampling.LANCZOS,
    )

    anchor_x = float(bounds.get("pivot_x", 0.5))
    anchor_y = float(bounds.get("pivot_y", 0.92))
    left = int(round(anchor_x * target_width - anchor_x * scaled_width))
    top = int(round(anchor_y * target_height - anchor_y * scaled_height))
    canvas = Image.new("RGBA", (target_width, target_height), (0, 0, 0, 0))
    canvas.alpha_composite(resized, (left, top))
    canvas.save(destination, format="PNG", optimize=True)
    return {
        **geometry,
        "normalized_canvas": [target_width, target_height],
        "shared_anchor": [anchor_x, anchor_y],
        "placement": [left, top],
        "scale": round(scale, 6),
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



PRIMARY_ASSEMBLY_PARTS = (
    "reference-part-001", "reference-part-003",
    "reference-part-004", "reference-part-005", "reference-part-006",
    "reference-part-021", "reference-part-022",
    "reference-part-024", "reference-part-025",
    "reference-part-027", "reference-part-028",
    "reference-part-030", "reference-part-031",
    "reference-part-032", "reference-part-033",
)
ASSEMBLY_Z_ORDER = {
    32: 5, 33: 5,
    30: 10, 31: 10,
    27: 20, 28: 20,
    24: 30,
    3: 40,
    4: 50, 5: 50, 6: 51,
    25: 60,
    21: 70, 22: 70,
    1: 90,
}
# Candidate-only pixel corrections bring the bow grip opening onto the bow shaft
# and close the fingerboard wrist gap without altering the preserved live rig.
ASSEMBLY_MANUAL_OFFSETS = {
    "reference-part-021": (20, -3),
    "reference-part-022": (-14, 10),
}


def _reference_assembly_joint_pivots(
    render_items: list[tuple[int, str, Image.Image, int, int]],
    width: int,
    height: int,
    character: dict[str, Any],
    *,
    strict: bool = False,
) -> dict[str, dict[str, Any]]:
    """Estimate candidate pivots from the shared opaque pixels at each seam.

    These are assembly-specific estimates, not artist approvals. The evidence
    records the exact overlapping parts and pixel count so a later reviewer can
    confirm or correct every pivot before the candidate is animated.
    """
    masks: dict[str, np.ndarray] = {}
    for _z, layer_id, sprite, x, y in render_items:
        alpha = np.asarray(sprite.getchannel("A"), dtype=np.uint8) > 8
        canvas_mask = np.zeros((height, width), dtype=bool)
        left, top = max(0, int(x)), max(0, int(y))
        right = min(width, int(x) + sprite.width)
        bottom = min(height, int(y) + sprite.height)
        if right > left and bottom > top:
            crop = alpha[top - int(y):bottom - int(y), left - int(x):right - int(x)]
            canvas_mask[top:bottom, left:right] = crop
        masks[str(layer_id)] = canvas_mask
        masks[str(layer_id).replace("_", "-")] = canvas_mask

    connections = {
        "left_shoulder": (
            "reference-part-003", "reference-part-004", 100,
        ),
        "left_elbow": (
            "reference-part-004", "reference-part-006", 100,
        ),
        "left_wrist": (
            "reference-part-006", "reference-part-021", 40,
        ),
        "right_shoulder": (
            "reference-part-003", "reference-part-005", 100,
        ),
        "right_elbow": (
            "reference-part-005", "source-bridge-right-forearm", 100,
        ),
        "right_wrist": (
            "source-bridge-right-forearm", "reference-part-022", 40,
        ),
        "left_hip": (
            "reference-part-024", "reference-part-027", 100,
        ),
        "right_hip": (
            "reference-part-024", "reference-part-028", 100,
        ),
        "left_knee": (
            "reference-part-027", "reference-part-030", 40,
        ),
        "right_knee": (
            "reference-part-028", "reference-part-031", 40,
        ),
        "left_ankle": (
            "reference-part-030", "reference-part-032", 30,
        ),
        "right_ankle": (
            "reference-part-031", "reference-part-033", 30,
        ),
    }
    pivots: dict[str, dict[str, Any]] = {}
    for joint_name, (parent_id, child_id, minimum_overlap) in connections.items():
        parent_mask = masks.get(parent_id)
        child_mask = masks.get(child_id)
        if parent_mask is None or child_mask is None:
            if strict:
                raise ReferenceSheetError(
                    f"Cannot estimate {joint_name}: missing assembly layer "
                    f"{parent_id if parent_mask is None else child_id}."
                )
            continue
        overlap = parent_mask & child_mask
        ys, xs = np.where(overlap)
        overlap_pixels = int(xs.size)
        if overlap_pixels < minimum_overlap:
            if strict:
                raise ReferenceSheetError(
                    f"Candidate {joint_name} has only {overlap_pixels} shared pixels; "
                    f"requires at least {minimum_overlap}."
                )
            continue
        x, y = float(xs.mean()), float(ys.mean())
        pivots[joint_name] = {
            "x": round(x, 3),
            "y": round(y, 3),
            "normalized": {
                "x": round(x / width, 6),
                "y": round(y / height, 6),
            },
            "parent_layer": parent_id,
            "child_layer": child_id,
            "overlap_pixels": overlap_pixels,
            "minimum_overlap_pixels": minimum_overlap,
            "method": "centroid_of_intersection_of_source_alpha_masks",
            "status": "candidate_estimate_pending_visual_joint_review",
            "approved": False,
        }

    # The head's neck anchor already comes from the preserved source rig. Keep
    # that author-authored coordinate rather than replacing it with a broad
    # overlap centroid between the cropped head and the neck backplate.
    neck = (character.get("joints") or {}).get("neck")
    if isinstance(neck, dict):
        x = float(neck["x"]) * width
        y = float(neck["y"]) * height
        pivots["neck"] = {
            "x": round(x, 3),
            "y": round(y, 3),
            "normalized": {
                "x": round(x / width, 6),
                "y": round(y / height, 6),
            },
            "parent_layer": "reference-part-001",
            "child_layer": "source-bridge-head-neck",
            "overlap_pixels": None,
            "minimum_overlap_pixels": None,
            "method": "preserved_source_rig_neck_joint",
            "status": "source_coordinate_preserved_pending_candidate_visual_review",
            "approved": False,
        }
    return pivots


def _source_aligned_character_assembly(
    character: dict[str, Any],
    bundle: Path,
) -> tuple[Image.Image | None, dict[str, Any] | None]:
    """Composite the actual source-aligned rig layers on their shared canvas.

    The reference catalogue contains front-facing costume/pose examples and
    must not be stacked onto the three-quarter violin-playing master. When a
    complete source-aligned rig is available, use its own extracted layers and
    exact canvas coordinates for the assembly review instead.
    """
    canvas = character.get("canvas") or {}
    width, height = int(canvas.get("width", 0)), int(canvas.get("height", 0))
    base_art = character.get("base_art")
    layers = character.get("layers") or []
    if width <= 0 or height <= 0 or not isinstance(base_art, dict) or not layers:
        return None, None

    required_roles = {
        "torso", "head", "face",
        "left_upper_arm", "right_upper_arm",
        "left_thigh", "right_thigh", "left_foot", "right_foot",
    }
    available_roles = {
        str(layer.get("role") or "") for layer in layers if isinstance(layer, dict)
    }
    if not required_roles.issubset(available_roles):
        return None, None

    entries: list[tuple[int, int, str, dict[str, Any]]] = [
        (int(base_art.get("z_index", 0)), -1, "base_art", base_art)
    ]
    for index, layer in enumerate(layers):
        if not isinstance(layer, dict):
            return None, None
        entries.append((
            int(layer.get("z_index", index + 1)),
            index,
            str(layer.get("role") or layer.get("id") or f"layer_{index}"),
            layer,
        ))

    props = character.get("props") or {}
    if not isinstance(props, dict):
        return None, None
    # The source composition deliberately preserves the original violin in
    # the segmented base plate. Re-overlaying the extracted violin prop would
    # double the instrument. The bow, however, is removed from that plate and
    # must be restored from its approved source asset at its authored geometry.
    violin_is_preserved = bool(base_art.get("violin_source_underlay_preserved"))
    for index, (prop_id, prop) in enumerate(props.items()):
        if not isinstance(prop, dict):
            return None, None
        if str(prop_id) == "violin" and violin_is_preserved:
            continue
        entries.append((
            int(prop.get("z_index", 30 + index)),
            len(layers) + index,
            f"prop_{prop_id}",
            prop,
        ))

    # Fall back to the catalogue-only image if even one source layer is absent.
    # A partial composite could look anatomically broken and must not be shown.
    resolved: list[tuple[int, int, str, Image.Image, int, int]] = []
    used_assets: list[str] = []
    for z_index, order, role, entry in sorted(entries, key=lambda item: (item[0], item[1])):
        src = str(entry.get("src") or "")
        asset_path = (bundle / src).resolve()
        if not src or not asset_path.is_file():
            return None, None
        x = int(round(float(entry.get("x", 0))))
        y = int(round(float(entry.get("y", 0))))
        target_width = int(round(float(entry.get("width", width))))
        target_height = int(round(float(entry.get("height", height))))
        if target_width <= 0 or target_height <= 0:
            return None, None
        try:
            with Image.open(asset_path) as opened:
                sprite = opened.convert("RGBA")
        except (OSError, ValueError):
            return None, None
        if sprite.size != (target_width, target_height):
            sprite = sprite.resize(
                (target_width, target_height), Image.Resampling.LANCZOS
            )
        if sprite.getchannel("A").getbbox() is None:
            # Empty compatibility anchors are harmless but do not count as
            # visible character layers.
            continue
        resolved.append((z_index, order, role, sprite, x, y))
        used_assets.append(src)

    if not resolved:
        return None, None
    assembled = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for _z_index, _order, _role, sprite, x, y in resolved:
        _alpha_composite_clipped(assembled, sprite, x, y)
    if assembled.getchannel("A").getbbox() is None:
        return None, None

    visible_props = [
        item[2][5:] for item in resolved if item[2].startswith("prop_")
    ]
    visible_layers = [
        item[2] for item in resolved if not item[2].startswith("prop_")
    ]
    report = {
        "method": "source_aligned_character_layers_and_props_on_shared_master_canvas",
        "source_pose": (
            (character.get("reference_part_alignment") or {}).get("source_pose")
            or "preserved_character_source_pose"
        ),
        "canvas": {"width": width, "height": height},
        "base_art": str(base_art.get("src") or ""),
        "visible_layer_count": len(visible_layers),
        "visible_layer_roles": visible_layers,
        "visible_prop_count": len(visible_props),
        "visible_prop_ids": visible_props,
        "source_props_used": visible_props,
        "source_assets": used_assets,
        "violin_source_underlay_preserved": violin_is_preserved,
        "reference_sheet_parts_used": [],
        "reference_sheet_cutouts_activated": False,
        "pose_mismatch_avoided": True,
        "joint_pivots_validated": False,
        "activation_policy": "review_only_preserve_live_character_and_production_rig",
    }
    return assembled, report


def _write_reference_part_assembly_candidate(
    part_records: list[dict[str, Any]],
    candidates: list[dict[str, Any]],
    character: dict[str, Any],
    bundle: Path,
) -> tuple[str, str, dict[str, Any]]:
    """Create a review-only assembly preview without mixing incompatible poses."""
    canvas = character.get("canvas") or {}
    width, height = int(canvas.get("width", 0)), int(canvas.get("height", 0))
    if width <= 0 or height <= 0:
        raise ReferenceSheetError("Reference-part assembly requires a valid character canvas.")
    part_by_id = {item["part_id"]: item for item in part_records}
    candidate_by_id = {item["part_id"]: item for item in candidates}
    assembled = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    placements, bridges, missing, render_items = [], [], [], []

    ordered_parts = sorted(PRIMARY_ASSEMBLY_PARTS, key=lambda pid: ASSEMBLY_Z_ORDER.get(int(pid.rsplit("-", 1)[-1]), 40))
    for part_id in ordered_parts:
        item, candidate = part_by_id.get(part_id), candidate_by_id.get(part_id)
        if item is None or candidate is None:
            missing.append(part_id + ":not_found")
            continue
        if not candidate.get("target_geometry_available"):
            missing.append(part_id + ":target_geometry_missing")
            continue
        transform = candidate["candidate_transform"]
        with Image.open(item["path"]) as opened:
            part = opened.convert("RGBA")
        if candidate.get("source_crop_px"):
            part = part.crop(tuple(int(value) for value in candidate["source_crop_px"]))
        rotation = float(candidate["rotation_deg"])
        if rotation:
            part = part.rotate(rotation, expand=True, resample=Image.Resampling.BICUBIC)
        part = part.resize((
            max(1, int(round(float(transform["width"])))),
            max(1, int(round(float(transform["height"])))),
        ), Image.Resampling.LANCZOS)
        base_x, base_y = int(round(float(transform["x"]))), int(round(float(transform["y"])))
        offset_x, offset_y = ASSEMBLY_MANUAL_OFFSETS.get(part_id, (0, 0))
        x, y = base_x + offset_x, base_y + offset_y
        z_index = ASSEMBLY_Z_ORDER.get(int(part_id.rsplit("-", 1)[-1]), 40)
        render_items.append((z_index, part_id, part, x, y))
        placements.append({
            "part_id": part_id, "src": Path(item["path"]).name,
            "target_role": candidate["target_role"], "variant": candidate["variant"],
            "z_index": z_index,
            "transform": {
                "x": x, "y": y, "width": part.width, "height": part.height,
                "rotation_deg": rotation, "scale": transform["scale"],
                "source_crop_px": candidate.get("source_crop_px"),
                "manual_alignment_offset_px": [offset_x, offset_y],
            },
        })

    layer_by_role = {str(layer.get("role") or ""): layer for layer in character.get("layers", [])}
    props = character.get("props") or {}

    def add_source_bridge(bridge_id: str, path: Path, geometry: dict[str, Any], z: int, reason: str) -> None:
        if not path.is_file():
            missing.append("bridge:" + bridge_id + ":asset_missing")
            return
        with Image.open(path) as opened:
            sprite = opened.convert("RGBA")
        sprite = sprite.resize((
            max(1, int(round(float(geometry["width"])))),
            max(1, int(round(float(geometry["height"])))),
        ), Image.Resampling.LANCZOS)
        x, y = int(round(float(geometry["x"]))), int(round(float(geometry["y"])))
        render_items.append((z, "source-bridge-" + bridge_id, sprite, x, y))
        bridges.append({
            "id": bridge_id, "src": path.name, "x": x, "y": y,
            "width": sprite.width, "height": sprite.height, "z_index": z, "reason": reason,
        })

    # The portrait sheet supplies a full neck, while the jacket and violin
    # must pass in front of its lower portion. Split the same supplied head
    # artwork into an upper portrait and a neck backplate so the neck is not
    # visibly cut off at the crop edge.
    head_record = part_by_id.get("reference-part-001")
    head_candidate = candidate_by_id.get("reference-part-001")
    if head_record is not None and head_candidate is not None:
        with Image.open(head_record["path"]) as opened:
            full_head = opened.convert("RGBA")
        source_width, source_height = full_head.size
        neck_top = max(1, min(source_height - 1, int(round(source_height * 0.68))))
        head_transform = head_candidate["candidate_transform"]
        head_scale = float(head_transform["width"]) / max(1, source_width)
        neck_sprite = full_head.crop((0, neck_top, source_width, source_height))
        neck_width = max(1, int(round(float(head_transform["width"]))))
        neck_height = max(1, int(round(neck_sprite.height * head_scale)))
        neck_sprite = neck_sprite.resize(
            (neck_width, neck_height), Image.Resampling.LANCZOS
        )
        neck_filename = "reference-part-001-neck-backplate.png"
        neck_sprite.save(bundle / neck_filename, format="PNG", optimize=True)
        neck_x = int(round(float(head_transform["x"])))
        neck_y = int(round(float(head_transform["y"]) + neck_top * head_scale))
        render_items.append((45, "source-bridge-head-neck", neck_sprite, neck_x, neck_y))
        bridges.append({
            "id": "head_neck", "src": neck_filename,
            "x": neck_x, "y": neck_y, "width": neck_sprite.width,
            "height": neck_sprite.height, "z_index": 45,
            "reason": "lower neck crop from the supplied head portrait; drawn above the jacket and behind the violin to preserve a continuous neck",
        })
    else:
        missing.append("bridge:head_neck:part_missing")

    forearm_layer = layer_by_role.get("right_forearm")
    if forearm_layer:
        forearm_geometry = dict(forearm_layer)
        forearm_geometry["x"] = float(forearm_layer.get("x", 0)) - 12
        forearm_geometry["y"] = float(forearm_layer.get("y", 0)) - 28
        add_source_bridge(
            "right_forearm", bundle / str(forearm_layer.get("src") or ""),
            forearm_geometry, 52,
            "the approved source forearm is shifted up and left, with a small rightward correction to overlap the fingerboard hand wrist",
        )
    else:
        missing.append("bridge:right_forearm:layer_missing")

    bow_prop = props.get("bow")
    if bow_prop:
        add_source_bridge(
            "bow", bundle / str(bow_prop.get("src") or ""),
            bow_prop, 65,
            "the extracted bow retains magenta guide colour; the approved wooden bow is retained",
        )
    else:
        missing.append("bridge:bow:prop_missing")

    ordered_render_items = sorted(render_items, key=lambda entry: entry[0])
    joint_pivots = _reference_assembly_joint_pivots(
        ordered_render_items, width, height, character,
        strict=len(part_records) == 33,
    )
    for _z, _id, sprite, x, y in ordered_render_items:
        _alpha_composite_clipped(assembled, sprite, x, y)

    # Export the assembled artwork as independent transparent sprites as well
    # as the flattened comparison image. This is still a review-only candidate:
    # joint pivots are hints until each attachment is visually validated.
    placement_by_id = {item["part_id"]: item for item in placements}
    bridge_by_render_id = {}
    for item in bridges:
        bridge_key = str(item["id"])
        bridge_by_render_id["source-bridge-" + bridge_key] = item
        # Some source bridge IDs contain underscores while the render IDs
        # normalize them to hyphens (for example head_neck -> head-neck).
        bridge_by_render_id[
            "source-bridge-" + bridge_key.replace("_", "-")
        ] = item
    layer_exports: list[dict[str, Any]] = []
    pivot_hints = {
        "head": [0.5, 0.92],
        "left_upper_arm": [0.5, 0.12],
        "right_upper_arm": [0.5, 0.12],
        "left_forearm": [0.5, 0.88],
        "right_forearm": [0.5, 0.88],
        "left_hand": [0.5, 0.85],
        "right_hand": [0.5, 0.85],
        "left_thigh": [0.5, 0.08],
        "right_thigh": [0.5, 0.08],
        "left_calf": [0.5, 0.08],
        "right_calf": [0.5, 0.08],
        "left_foot": [0.5, 0.18],
        "right_foot": [0.5, 0.18],
        "violin": [0.5, 0.12],
        "bow": [0.5, 0.98],
        "neck_bridge": [0.5, 0.9],
        "torso": [0.5, 0.5],
    }
    joint_for_role = {
        "head": "neck",
        "neck_bridge": "neck",
        "left_upper_arm": "left_shoulder",
        "left_forearm": "left_elbow",
        "left_hand": "left_wrist",
        "right_upper_arm": "right_shoulder",
        "right_forearm": "right_elbow",
        "right_hand": "right_wrist",
        "left_thigh": "left_hip",
        "right_thigh": "right_hip",
        "left_calf": "left_knee",
        "right_calf": "right_knee",
        "left_foot": "left_ankle",
        "right_foot": "right_ankle",
    }
    for z_index, layer_id, sprite, x, y in ordered_render_items:
        safe_id = "".join(
            character.lower() if character.isalnum() else "-"
            for character in str(layer_id)
        ).strip("-")
        filename = f"reference-assembly-layer-{safe_id}.png"
        sprite.save(bundle / filename, format="PNG", optimize=True)
        placement = placement_by_id.get(layer_id)
        bridge = bridge_by_render_id.get(layer_id)
        if placement is not None:
            target_role = str(placement.get("target_role") or "unmapped")
            layer_kind = "reference_sheet_part"
            part_id = layer_id
            bridge_id = None
            transform = placement.get("transform") or {}
            scale = transform.get("scale")
            rotation = transform.get("rotation_deg", 0)
        elif bridge is not None:
            bridge_id = str(bridge.get("id") or "")
            target_role = (
                "neck_bridge" if bridge_id == "head_neck" else bridge_id
            )
            layer_kind = "approved_source_bridge"
            part_id = None
            scale = None
            rotation = 0
        else:
            raise ReferenceSheetError(
                f"Could not identify exported assembly layer {layer_id}."
            )
        alpha_bounds = sprite.getchannel("A").getbbox()
        if alpha_bounds is None:
            raise ReferenceSheetError(
                f"Assembly layer {layer_id} has no visible alpha pixels."
            )
        joint_name = joint_for_role.get(target_role)
        pivot_record = joint_pivots.get(joint_name) if joint_name else None
        if pivot_record:
            pivot_x = (float(pivot_record["x"]) - int(x)) / max(1, sprite.width)
            pivot_y = (float(pivot_record["y"]) - int(y)) / max(1, sprite.height)
            layer_pivot_hint = [
                round(pivot_x, 6), round(pivot_y, 6)
            ]
            pivot_status = "alpha_overlap_candidate_estimate_not_approved"
        else:
            layer_pivot_hint = pivot_hints.get(target_role, [0.5, 0.5])
            pivot_status = "static_layer_no_joint_pivot"
        layer_exports.append({
            "layer_id": str(layer_id),
            "src": filename,
            "kind": layer_kind,
            "part_id": part_id,
            "bridge_id": bridge_id,
            "target_role": target_role,
            "x": int(x),
            "y": int(y),
            "width": int(sprite.width),
            "height": int(sprite.height),
            "z_index": int(z_index),
            "rotation_deg": float(rotation),
            "scale": scale,
            "pivot_hint_normalized": layer_pivot_hint,
            "pivot_joint": joint_name,
            "pivot_status": pivot_status,
            "visible_alpha_bounds_px": list(alpha_bounds),
        })

    layered_manifest_name = "reference-part-assembled-layer-candidate.json"
    layered_manifest = {
        "schema_version": 1,
        "status": "layered_candidate_exported_pending_joint_pivot_alignment",
        "activation_policy": "review_only_do_not_replace_live_or_production_layers",
        "canvas": {"width": width, "height": height},
        "layers": layer_exports,
        "layer_count": len(layer_exports),
        "joint_pivots": joint_pivots,
        "joint_pivot_count": len(joint_pivots),
        "joint_pivot_method": "alpha_overlap_centroids_with_preserved_source_neck_anchor",
        "primary_part_count": len(placements),
        "source_bridge_count": len(bridges),
        "missing_or_unplaced": missing,
        "joint_pivots_validated": False,
        "animation_ready": False,
        "production_layer_replacement_enabled": False,
        "facial_state_assets": {},
        "facial_state_build_status": "not_attached",
        "facial_state_alignment_status": "awaiting_candidate_head_alignment",
        "note": (
            "These extracted assets remain a reference-sheet catalogue. The catalogue "
            "pose is front-facing and is not a pixel-aligned match for the three-quarter "
            "violin-playing master. Do not use these catalogue pivots or cutouts as the "
            "master character rig; the assembly review image uses the preserved "
            "source-aligned character layers when those layers are available."
        ),
    }
    (bundle / layered_manifest_name).write_text(
        json.dumps(layered_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # Prefer the source-aligned character rig for the visible assembly review.
    # The independently extracted reference-sheet pieces belong to a different
    # front-facing pose; rendering them over the three-quarter master creates
    # oversized, disconnected limbs and a ghost-like composite.
    source_aligned_assembly, source_aligned_report = (
        _source_aligned_character_assembly(character, bundle)
    )
    if source_aligned_assembly is not None:
        # The catalogue layers remain exported separately for inspection, but
        # are not mixed into this assembled violin-playing character.
        assembled = source_aligned_assembly
        source_manifest_path = bundle / "reference-part-source-aligned-assembly.json"
        source_manifest_path.write_text(
            json.dumps(source_aligned_report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    transparent_path = bundle / "reference-part-assembled-candidate.png"
    assembled.save(transparent_path, format="PNG", optimize=True)
    background = (26, 35, 50, 255)
    source_view = Image.new("RGBA", (width, height), background)
    source_path = bundle / "preserved-full-body-source.png"
    if source_path.is_file():
        with Image.open(source_path) as opened:
            source_view.alpha_composite(opened.convert("RGBA").resize((width, height), Image.Resampling.LANCZOS))
    candidate_view = Image.new("RGBA", (width, height), background)
    candidate_view.alpha_composite(assembled)
    comparison = Image.new("RGB", (width * 2 + 48, height + 48), (12, 19, 31))
    draw = ImageDraw.Draw(comparison)
    comparison.paste(source_view.convert("RGB"), (12, 34))
    comparison.paste(candidate_view.convert("RGB"), (width + 36, 34))
    draw.text((12, 10), "SOURCE REFERENCE", fill=(240, 235, 224))
    candidate_label = (
        "SOURCE-ALIGNED BODY-PART ASSEMBLY"
        if source_aligned_assembly is not None
        else "REFERENCE-CATALOGUE ASSEMBLY REVIEW ONLY"
    )
    draw.text((width + 36, 10), candidate_label, fill=(240, 235, 224))
    comparison_path = bundle / "reference-part-assembled-comparison.jpg"
    comparison.save(comparison_path, format="JPEG", quality=94)

    for placement in placements:
        placement["rendered_in_assembly_preview"] = False
        placement["source_role"] = "front_facing_reference_catalogue_only"

    payload = {
        "schema_version": 1,
        "status": "assembled_candidate_not_active_pending_visual_review",
        "rendered_assembly_method": (
            source_aligned_report["method"]
            if source_aligned_report is not None
            else "reference_sheet_catalogue_fallback_review_only"
        ),
        "source_aligned_assembly_manifest": (
            "reference-part-source-aligned-assembly.json"
            if source_aligned_report is not None
            else None
        ),
        "reference_sheet_pose_mismatch": source_aligned_report is not None,
        "reference_sheet_parts_used_in_render": (
            [] if source_aligned_report is not None else list(PRIMARY_ASSEMBLY_PARTS)
        ),
        "source_aligned_layer_count": (
            source_aligned_report["visible_layer_count"]
            if source_aligned_report is not None else 0
        ),
        "production_layer_replacement_enabled": False,
        "canvas": {"width": width, "height": height},
        "primary_part_ids": list(PRIMARY_ASSEMBLY_PARTS),
        "placements": placements,
        "source_bridge_layers": bridges,
        "review_exclusions": {
            "reference-part-014": "alternate trouser lower leg; primary parts are 030 and 031",
            "reference-part-015": "alternate trouser lower leg; primary parts are 030 and 031",
            "reference-part-016": "alternate lower-leg variant",
            "reference-part-026": "magenta guide-coloured bow; approved wooden bow retained as a source bridge",
            "reference-part-002": "hair overlay is redundant with the complete head portrait",
            "reference-part-007_to_013": "eye/nose details are reserved for the facial-expression rig",
        },
        "missing_or_unplaced": missing,
        "primary_part_count": len(placements),
        "source_asset_count": len(placements) + len(bridges),
        "source_bridge_count": len(bridges),
        "layered_candidate_manifest": layered_manifest_name,
        "layer_export_count": len(layer_exports),
        "layered_candidate_activation_enabled": False,
        "note": (
            "The visible assembly preview uses the original source-aligned character "
            "layers on their shared master canvas when available. Front-facing reference "
            "catalogue cutouts are not mixed into the three-quarter violin-playing pose. "
            "The reference catalogue and its provisional pivots remain review-only; no "
            "live character layer or production animation is modified."
        ),
    }
    (bundle / "reference-part-assembled-candidate.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return transparent_path.name, comparison_path.name, payload


def _build_facial_state_head_variants(
    facial_parts: list[dict[str, Any]],
    head_variants: dict[str, dict[str, Any]],
    bundle: Path,
) -> tuple[dict[str, dict[str, Any]], str | None, str]:
    """Composite real eye and mouth cut-outs into distinct full-head state plates."""
    required = {15, 16, 17, 20, 28, 31, 32, 33, 34}
    by_number = {
        int(str(item["part_id"]).rsplit("-", 1)[-1]): item
        for item in facial_parts
    }
    missing = sorted(required - set(by_number))
    if missing or "neutral" not in head_variants:
        return {}, None, "skipped_missing_required_components:" + ",".join(map(str, missing))

    neutral_path = bundle / str(head_variants["neutral"]["src"])
    with Image.open(neutral_path) as opened:
        neutral = opened.convert("RGBA")

    samples = [
        neutral.getpixel((x, y))[:3]
        for x, y in ((34, 91), (100, 91), (48, 96), (88, 96), (68, 93))
        if 0 <= x < neutral.width and 0 <= y < neutral.height
        and neutral.getpixel((x, y))[3] > 180
    ]
    if samples:
        skin = tuple(int(value) for value in np.median(np.asarray(samples), axis=0)) + (255,)
    else:
        skin = (181, 122, 83, 255)

    eye_open_boxes = ((42, 68, 60, 80), (80, 68, 98, 80))
    # The supplied closed-eye plates include the full eyelid and surrounding
    # skin, so give them a slightly taller target than the narrow open-eye crop.
    eye_closed_boxes = ((40, 66, 62, 82), (78, 66, 100, 82))
    eye_hole_boxes = ((38, 65, 63, 84), (77, 65, 102, 84))
    mouth_box = (50, 98, 89, 119)

    def load_part(number: int) -> Image.Image:
        with Image.open(by_number[number]["path"]) as opened:
            return opened.convert("RGBA")

    def compose_state(
        name: str,
        *,
        eye_ids: tuple[int, int] | None = None,
        mouth_id: int | None = None,
        closed_eye: bool = False,
    ) -> dict[str, Any]:
        image = neutral.copy()
        draw = ImageDraw.Draw(image)

        if eye_ids:
            for box in eye_hole_boxes:
                draw.rounded_rectangle(box, radius=4, fill=skin)
            target_boxes = eye_closed_boxes if closed_eye else eye_open_boxes
            for number, box in zip(eye_ids, target_boxes, strict=True):
                feature = load_part(number)
                feature = feature.resize(
                    (box[2] - box[0], box[3] - box[1]),
                    Image.Resampling.LANCZOS,
                )
                image.alpha_composite(feature, (box[0], box[1]))

        if mouth_id is not None:
            draw = ImageDraw.Draw(image)
            draw.rounded_rectangle(mouth_box, radius=7, fill=skin)
            mouth = load_part(mouth_id)
            mouth = mouth.resize(
                (mouth_box[2] - mouth_box[0], mouth_box[3] - mouth_box[1]),
                Image.Resampling.LANCZOS,
            )
            image.alpha_composite(mouth, (mouth_box[0], mouth_box[1]))

        filename = f"head-variant-{name}.png"
        image.save(bundle / filename, format="PNG", optimize=True)
        return {**head_variants["neutral"], "src": filename}

    states = {
        "speaking_open": compose_state("speaking_open", mouth_id=31),
        "speaking_closed": compose_state("speaking_closed", mouth_id=20),
        "blink_closed": compose_state(
            "blink_closed", eye_ids=(32, 33), closed_eye=True
        ),
        "sad": compose_state("sad", mouth_id=28),
        "shocked_open": compose_state(
            "shocked_open", eye_ids=(15, 16), mouth_id=17
        ),
        "smile": compose_state("smile", mouth_id=34),
    }

    columns, cell_width, cell_height = 4, 190, 205
    rows = max(1, (len(states) + columns - 1) // columns)
    contact = Image.new("RGB", (columns * cell_width, rows * cell_height), (18, 27, 41))
    draw = ImageDraw.Draw(contact)
    for index, (name, asset) in enumerate(states.items()):
        row, column = divmod(index, columns)
        x, y = column * cell_width, row * cell_height
        with Image.open(bundle / asset["src"]) as opened:
            plate = opened.convert("RGBA")
        plate.thumbnail((cell_width - 18, cell_height - 42), Image.Resampling.LANCZOS)
        tile = Image.new("RGBA", plate.size, (30, 42, 58, 255))
        tile.alpha_composite(plate)
        contact.paste(tile.convert("RGB"), (x + (cell_width - plate.width) // 2, y + 34))
        draw.text((x + 8, y + 8), name, fill=(245, 238, 224))
    contact_path = bundle / "facial-state-head-contact-sheet.png"
    contact.save(contact_path, format="PNG", optimize=True)
    return states, contact_path.name, "created_from_separate_eye_and_mouth_assets"


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
    alignment_candidates = _reference_part_alignment_candidates(part_records, character)
    alignment_preview_file = _write_reference_part_alignment_preview(
        part_records, alignment_candidates, bundle
    )
    alignment_payload = {
        "schema_version": 1,
        "status": "candidate_not_active_pending_visual_review",
        "activation_policy": "do_not_replace_production_layers_until_candidate_review",
        "coordinate_space": "character_canvas_top_left_pixels",
        "parts": alignment_candidates,
    }
    alignment_path = bundle / "reference-part-alignment-candidate.json"
    alignment_path.write_text(
        json.dumps(alignment_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    expression_components = _four_ordered_components(
        expression_sheet_path, minimum_area_ratio=0.012
    )
    angle_components = _four_ordered_components(
        head_angle_sheet_path,
        minimum_area_ratio=0.009,
        top_region_ratio=0.62,
    )
    facial_parts, facial_parts_contact_sheet = _catalogue_facial_components(
        head_angle_sheet_path, bundle
    )
    assembly_png, assembly_comparison, assembly_report = _write_reference_part_assembly_candidate(
        part_records, alignment_candidates, character, bundle
    )
    head_bounds = _head_plate_bounds(character)
    # All eight plates share one exact pixel canvas and the same bottom-centre
    # neck anchor; source component dimensions no longer drive renderer scale.
    head_bounds["width"] = float(max(1, int(round(head_bounds["width"]))))
    head_bounds["height"] = float(max(1, int(round(head_bounds["height"]))))

    head_variants = {}
    for name, component in zip(EXPRESSION_ORDER, expression_components, strict=True):
        filename = f"head-variant-{name}.png"
        _save_neck_anchored_head_plate(
            component, bundle / filename, head_bounds
        )
        head_variants[name] = {"src": filename, **head_bounds}

    head_angles = {}
    for name, component in zip(HEAD_ANGLE_ORDER, angle_components, strict=True):
        filename = f"head-angle-{name}.png"
        _save_neck_anchored_head_plate(
            component, bundle / filename, head_bounds
        )
        head_angles[name] = {"src": filename, **head_bounds}

    facial_state_variants, facial_state_contact_sheet, facial_state_status = (
        _build_facial_state_head_variants(facial_parts, head_variants, bundle)
    )
    head_variants.update(facial_state_variants)

    layered_manifest_path = bundle / "reference-part-assembled-layer-candidate.json"
    if layered_manifest_path.is_file():
        layered_manifest = json.loads(
            layered_manifest_path.read_text(encoding="utf-8")
        )
        layered_manifest["facial_state_assets"] = {
            name: {
                "src": str(asset["src"]),
                "alignment_status": "awaiting_candidate_head_alignment",
            }
            for name, asset in facial_state_variants.items()
        }
        layered_manifest["facial_state_build_status"] = facial_state_status
        layered_manifest["facial_state_alignment_status"] = (
            "awaiting_candidate_head_alignment"
            if facial_state_variants else "not_available"
        )
        layered_manifest_path.write_text(
            json.dumps(layered_manifest, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    character["head_plate_bounds"] = head_bounds
    character["head_variants"] = head_variants
    character["head_angles"] = head_angles
    character["facial_part_catalogue"] = {
        "status": "extracted_pending_feature_alignment",
        "source_sheet": Path(head_angle_sheet_path).name,
        "contact_sheet": facial_parts_contact_sheet,
        "part_count": len(facial_parts),
        "components": [
            {
                "part_id": item["part_id"],
                "src": Path(item["path"]).name,
                "source_bbox": item["source_bbox"],
                "width": item["width"],
                "height": item["height"],
                "pixel_area": item["pixel_area"],
                "source_zone": item["source_zone"],
            }
            for item in facial_parts
        ],
        "state_variant_names": list(facial_state_variants),
        "state_contact_sheet": facial_state_contact_sheet,
        "state_build_status": facial_state_status,
        "production_face_overlay_enabled": False,
    }
    character["reference_part_alignment"] = {
        "status": "candidate_not_active_pending_visual_review",
        "alignment_file": alignment_path.name,
        "preview_file": alignment_preview_file,
        "assembly_png": assembly_png,
        "assembly_comparison": assembly_comparison,
        "assembly_manifest": "reference-part-assembled-candidate.json",
        "layered_assembly_manifest": "reference-part-assembled-layer-candidate.json",
        "part_count": len(alignment_candidates),
        "production_layer_replacement_enabled": False,
        "parts": alignment_candidates,
    }
    character = validate_character_spec(character)
    character_path.write_text(
        json.dumps(character, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    report = {
        "status": "modular_head_plates_and_reference_catalogue_created",
        "head_variant_names": list(head_variants),
        "head_angle_names": list(head_angles),
        "facial_state_names": list(facial_state_variants),
        "facial_state_build_status": facial_state_status,
        "facial_state_contact_sheet": facial_state_contact_sheet,
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
        "reference_parts_mapping": "explicit_rig_role_and_target_geometry_candidates",
        "reference_part_mapping_file": "reference-part-map.json",
        "reference_part_alignment_file": alignment_path.name,
        "reference_part_alignment_preview": alignment_preview_file,
        "reference_part_assembly_png": assembly_png,
        "reference_part_assembly_comparison": assembly_comparison,
        "reference_part_assembly_report": assembly_report,
        "facial_part_count": len(facial_parts),
        "facial_parts_contact_sheet": facial_parts_contact_sheet,
        "facial_feature_catalogue_status": "extracted_pending_feature_alignment",
        "reference_part_alignment_candidate_count": len(alignment_candidates),
        "alignment": "all 33 cut-outs have a provisional target rig role, target box, variant group and aspect-preserving transform; none are activated in production until visual review",
        "head_plate_normalization": "fixed_canvas_bottom_centre_neck_anchor",
        "head_plate_canvas": [
            int(head_bounds["width"]), int(head_bounds["height"])
        ],
        "automatic_body_part_replacement": False,
        "candidate_layer_activation": "disabled_until_visual_review",
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
                "alignment_candidate": next(
                    candidate for candidate in alignment_candidates
                    if candidate["part_id"] == item["part_id"]
                ),
            }
            for item in part_records
        ],
        "facial_feature_catalogue": [
            {
                "part_id": item["part_id"],
                "src": Path(item["path"]).name,
                "source_bbox": item["source_bbox"],
                "source_zone": item["source_zone"],
            }
            for item in facial_parts
        ],
        "facial_parts_contact_sheet": facial_parts_contact_sheet,
        "facial_state_names": list(facial_state_variants),
        "facial_state_build_status": facial_state_status,
        "facial_state_contact_sheet": facial_state_contact_sheet,
        "facial_feature_activation": "composited_head_state_variants_available_for_preview_sequence",
        "alignment_policy": "explicit_candidate_not_active_pending_visual_review",
        "alignment_candidate_file": alignment_path.name,
        "alignment_preview_file": alignment_preview_file,
    }
    (bundle / "reference-part-map.json").write_text(
        json.dumps(mapping_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report
