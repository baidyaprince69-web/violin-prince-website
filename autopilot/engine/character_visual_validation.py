"""Raster-space diagnostics for separated character layers and joint anchors."""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

JOINT_LAYER_PAIRS = {
    "neck": ("head", "torso"),
    "left_shoulder": ("torso", "left_upper_arm"),
    "left_elbow": ("left_upper_arm", "left_forearm"),
    "left_wrist": ("left_forearm", "left_hand"),
    "right_shoulder": ("torso", "right_upper_arm"),
    "right_elbow": ("right_upper_arm", "right_forearm"),
    "right_wrist": ("right_forearm", "right_hand"),
}


def _nearest_alpha_distance(mask: np.ndarray, x: float, y: float, *, radius: int = 32) -> float | None:
    height, width = mask.shape
    cx, cy = int(round(x)), int(round(y))
    x0, x1 = max(0, cx - radius), min(width, cx + radius + 1)
    y0, y1 = max(0, cy - radius), min(height, cy + radius + 1)
    region = mask[y0:y1, x0:x1]
    ys, xs = np.nonzero(region)
    if len(xs) == 0:
        return None
    distances = np.sqrt((xs + x0 - x) ** 2 + (ys + y0 - y) ** 2)
    return float(np.min(distances))


def verify_character_visuals(character: dict[str, Any], bundle_dir: str | Path) -> dict[str, Any]:
    root = Path(bundle_dir).resolve(strict=True)
    canvas = character.get("canvas") or {}
    canvas_width, canvas_height = int(canvas.get("width", 0)), int(canvas.get("height", 0))
    if canvas_width <= 0 or canvas_height <= 0:
        raise ValueError("Character canvas dimensions must be positive.")

    layer_masks: dict[str, np.ndarray] = {}
    layer_records = []
    errors: list[str] = []
    warnings: list[str] = []
    for layer in character.get("layers", []):
        role = str(layer.get("role") or layer.get("id") or "")
        raw_source = Path(str(layer.get("src") or ""))
        source = raw_source.resolve() if raw_source.is_absolute() else (root / raw_source).resolve()
        if (source != root and root not in source.parents) or not source.is_file():
            errors.append(f"missing_or_unsafe_layer:{role}")
            continue
        with Image.open(source) as opened:
            rgba = opened.convert("RGBA")
            width, height = rgba.size
            alpha = np.asarray(rgba.getchannel("A"), dtype=np.uint8)
        expected = (int(round(float(layer.get("width", 0)))), int(round(float(layer.get("height", 0)))))
        if (width, height) != expected:
            errors.append(f"layer_dimensions_mismatch:{role}")
        x, y = int(round(float(layer.get("x", 0)))), int(round(float(layer.get("y", 0))))
        if x < 0 or y < 0 or x + width > canvas_width or y + height > canvas_height:
            errors.append(f"layer_outside_canvas:{role}")
        coverage = float(np.count_nonzero(alpha)) / float(alpha.size)
        if coverage <= 0:
            errors.append(f"empty_alpha_layer:{role}")
        elif coverage < 0.015:
            warnings.append(f"very_sparse_alpha_layer:{role}")
        layer_masks[role] = alpha > 8
        layer_records.append({
            "role": role,
            "src": source.name,
            "width": width,
            "height": height,
            "alpha_coverage": round(coverage, 6),
            "canvas_bounds": [x, y, x + width, y + height],
            "z_index": int(layer.get("z_index", 0)),
        })

    joints = character.get("joints") or {}
    joint_records = []
    for joint_name, pair in JOINT_LAYER_PAIRS.items():
        point = joints.get(joint_name) or {}
        px = float(point.get("x", -1)) * canvas_width
        py = float(point.get("y", -1)) * canvas_height
        sides = []
        for role in pair:
            layer = next((item for item in character.get("layers", []) if item.get("role") == role), None)
            mask = layer_masks.get(role)
            if layer is None or mask is None:
                sides.append({"role": role, "status": "missing"})
                continue
            local_x = px - float(layer.get("x", 0))
            local_y = py - float(layer.get("y", 0))
            distance = _nearest_alpha_distance(mask, local_x, local_y)
            sides.append({
                "role": role,
                "nearest_alpha_distance_px": round(distance, 2) if distance is not None else None,
                "within_32px": distance is not None,
            })
        aligned = all(item.get("within_32px") is True for item in sides)
        if not aligned:
            warnings.append(f"joint_anchor_needs_visual_review:{joint_name}")
        joint_records.append({
            "joint": joint_name,
            "canvas_xy": [round(px, 2), round(py, 2)],
            "adjacent_layers": sides,
            "alignment_status": "passed" if aligned else "warning",
        })

    # Pairwise occlusion diagnostics use actual overlapping non-transparent
    # pixels and report the declared front-to-back order without rewriting it.
    occlusion_records = []
    by_role = {str(item.get("role")): item for item in character.get("layers", [])}
    for joint_name, pair in JOINT_LAYER_PAIRS.items():
        first, second = (by_role.get(pair[0]), by_role.get(pair[1]))
        if not first or not second or pair[0] not in layer_masks or pair[1] not in layer_masks:
            continue
        ax, ay = int(round(float(first["x"]))), int(round(float(first["y"])))
        bx, by = int(round(float(second["x"]))), int(round(float(second["y"])))
        aw, ah = layer_masks[pair[0]].shape[1], layer_masks[pair[0]].shape[0]
        bw, bh = layer_masks[pair[1]].shape[1], layer_masks[pair[1]].shape[0]
        x0, y0 = max(ax, bx), max(ay, by)
        x1, y1 = min(ax + aw, bx + bw), min(ay + ah, by + bh)
        overlap_pixels = 0
        if x1 > x0 and y1 > y0:
            first_crop = layer_masks[pair[0]][y0 - ay:y1 - ay, x0 - ax:x1 - ax]
            second_crop = layer_masks[pair[1]][y0 - by:y1 - by, x0 - bx:x1 - bx]
            overlap_pixels = int(np.count_nonzero(first_crop & second_crop))
        z_first, z_second = int(first.get("z_index", 0)), int(second.get("z_index", 0))
        occlusion_records.append({
            "joint": joint_name,
            "layer_pair": list(pair),
            "overlap_pixels": overlap_pixels,
            "declared_front_layer": pair[0] if z_first > z_second else pair[1],
            "declared_order_conflict": z_first == z_second,
        })
        if z_first == z_second:
            warnings.append(f"ambiguous_layer_order:{pair[0]}:{pair[1]}")

    return {
        "status": "failed" if errors else ("warning" if warnings else "passed"),
        "character_id": str(character.get("id") or ""),
        "canvas": {"width": canvas_width, "height": canvas_height},
        "layer_count": len(layer_records),
        "joint_count": len(joint_records),
        "layers": layer_records,
        "joint_alignment": joint_records,
        "occlusion_diagnostics": occlusion_records,
        "visual_review_required": True,
        "visual_review_note": "Raster checks support review; they do not certify finger-edge quality, semantic correctness, or final artistic approval.",
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
    }
