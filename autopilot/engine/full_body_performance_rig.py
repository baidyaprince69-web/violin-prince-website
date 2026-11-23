"""Extend the existing Violin Prince rig with full-body legs and instrument controls.

This stage is candidate generation only. All segmentation and manually authored
prop/finger masks are reported for visual review; it never publishes.
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from character_autorig import (
    AutoRigError,
    ManualReviewRequired,
    PASCAL_MODEL,
    PASCAL_REVISION,
    SCHPOnnxParser,
    _bbox,
    _joint_between,
    _morph,
    _normalise_joint,
)
from character_rig import validate_character_spec


# SCHP PASCAL-person-part label map: 5=upper legs, 6=lower legs.
LEG_LABELS = {"upper_leg": 5, "lower_leg": 6}
LEG_ROLE_Z = {
    # Parent-to-child draw order: upper legs behind calves, calves behind feet.
    "left_thigh": 4, "right_thigh": 5,
    "left_calf": 6, "right_calf": 7,
    "left_foot": 8, "right_foot": 9,
}
FINGER_Z = {
    "finger_index": 43, "finger_index_middle": 44, "finger_index_tip": 45,
    "finger_middle": 46, "finger_middle_middle": 47, "finger_middle_tip": 48,
    "finger_ring": 49, "finger_ring_middle": 50, "finger_ring_tip": 51,
    "finger_little": 52, "finger_little_middle": 53, "finger_little_tip": 54,
}


def _save_rgba_layer(
    source: Image.Image,
    mask: np.ndarray,
    destination: Path,
    *,
    padding: int = 8,
) -> dict[str, Any]:
    mask = np.asarray(mask, dtype=bool)
    if mask.shape != (source.height, source.width) or not mask.any():
        raise ManualReviewRequired(f"Cannot save an empty or mismatched layer: {destination.name}")
    x0, y0, x1, y1 = _bbox(mask)
    x0, y0 = max(0, x0 - padding), max(0, y0 - padding)
    x1, y1 = min(source.width, x1 + padding), min(source.height, y1 + padding)
    crop = source.convert("RGBA").crop((x0, y0, x1, y1))
    alpha = np.asarray(crop.getchannel("A"), dtype=np.uint8)
    cut = mask[y0:y1, x0:x1]
    crop.putalpha(Image.fromarray(np.where(cut, alpha, 0).astype(np.uint8), mode="L"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    crop.save(destination, format="PNG", optimize=True)
    return {
        "src": destination.name,
        "x": x0, "y": y0,
        "width": x1 - x0, "height": y1 - y0,
        "pixel_area": int(mask.sum()),
    }


def _largest_component(mask: np.ndarray) -> np.ndarray:
    """Return the largest 8-connected region without adding a runtime dependency."""
    import cv2

    binary = np.asarray(mask, dtype=np.uint8)
    count, labels, stats, _centroids = cv2.connectedComponentsWithStats(binary, 8)
    if count <= 1:
        return np.zeros_like(binary, dtype=bool)
    index = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    return labels == index


def _foot_mask(
    rgb: np.ndarray,
    alpha: np.ndarray,
    *,
    side: str,
    split_x: float,
) -> np.ndarray:
    height, width = alpha.shape
    yy, xx = np.mgrid[:height, :width]
    screen_side = xx < split_x if side == "left" else xx >= split_x
    # Shoes are darker and substantially wider than the trouser cuff. Locate
    # the largest bottom-connected dark component, then find the row where its
    # silhouette widens into footwear. This retains the complete shoe rather
    # than cropping only the bottom half.
    dark = rgb.max(axis=2) <= 145
    candidate = (alpha > 12) & dark & screen_side & (yy >= int(height * 0.875))
    candidate = _morph(_morph(candidate, 2, "dilate"), 2, "erode")
    component = _largest_component(candidate)
    if int(component.sum()) < 70:
        raise ManualReviewRequired(
            f"Could not isolate the {side} shoe from the full-body reference."
        )

    row_width = np.zeros(height, dtype=np.int32)
    for row in range(int(height * 0.875), height):
        xs = np.where(component[row])[0]
        row_width[row] = int(xs.max() - xs.min() + 1) if xs.size else 0
    foot_top = None
    for row in range(int(height * 0.89), height - 4):
        previous = row_width[max(0, row - 18):max(0, row - 5)]
        previous = previous[previous > 0]
        current = row_width[row:row + 5]
        current = current[current > 0]
        if previous.size >= 5 and current.size >= 3:
            cuff_width = float(np.median(previous))
            shoe_width = float(np.median(current))
            if cuff_width > 0 and shoe_width >= cuff_width * 1.32:
                foot_top = row
                break
    if foot_top is None:
        foot_top = int(height * 0.925)
    shoe = component & (yy >= max(0, foot_top - 2))
    shoe = _morph(shoe, 1, "dilate") & (alpha > 0)
    if int(shoe.sum()) < 70:
        raise ManualReviewRequired(
            f"The {side} shoe-width transition was too ambiguous for a safe ankle cut."
        )
    return shoe


def _leg_layers(
    source: Image.Image,
    labels: np.ndarray,
    character: dict[str, Any],
    bundle_dir: Path,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, float]], dict[str, Any]]:
    rgba = source.convert("RGBA")
    pixels = np.asarray(rgba, dtype=np.uint8)
    rgb, alpha = pixels[:, :, :3], pixels[:, :, 3]
    height, width = alpha.shape
    torso = labels == 2
    if int(torso.sum()) < 100:
        raise ManualReviewRequired("The body parser could not locate a stable torso for hip anchors.")
    tx0, _ty0, tx1, _ty1 = _bbox(torso)
    split_x = (tx0 + tx1) / 2.0
    thigh_all = (labels == LEG_LABELS["upper_leg"]) & (alpha > 8)
    calf_all = (labels == LEG_LABELS["lower_leg"]) & (alpha > 8)
    if int(thigh_all.sum()) < 300 or int(calf_all.sum()) < 200:
        raise ManualReviewRequired(
            "The full-body parser did not identify both upper-leg and lower-leg regions reliably."
        )

    layers: list[dict[str, Any]] = []
    joints: dict[str, dict[str, float]] = {}
    report: dict[str, Any] = {
        "label_ids": dict(LEG_LABELS),
        "screen_side_split_x": round(split_x, 2),
        "parts": {},
        "review_required": True,
    }
    for side in ("left", "right"):
        side_mask = (
            np.broadcast_to(np.arange(width)[None, :] < split_x, (height, width))
            if side == "left"
            else np.broadcast_to(np.arange(width)[None, :] >= split_x, (height, width))
        )
        thigh = _morph(_morph(thigh_all & side_mask, 2, "dilate"), 2, "erode") & (alpha > 0)
        calf = _morph(_morph(calf_all & side_mask, 2, "dilate"), 2, "erode") & (alpha > 0)
        foot = _foot_mask(rgb, alpha, side=side, split_x=split_x)

        if int(thigh.sum()) < 100 or int(calf.sum()) < 80:
            raise ManualReviewRequired(
                f"The {side} thigh/calf masks are too small; inspect the semantic segmentation."
            )

        fx0, fy0, fx1, fy1 = _bbox(foot)
        ankle_y = min(height - 1, fy0 + 3)
        # Keep a small cuff overlap under the ankle pivot so foot rotation cannot expose a gap.
        calf &= np.indices(calf.shape)[0] <= ankle_y + 10
        if int(calf.sum()) < 80:
            raise ManualReviewRequired(f"The {side} calf was lost while isolating the shoe.")

        hip_point = _joint_between(torso, thigh)
        knee_point = _joint_between(thigh, calf)
        shoe_top = foot & (np.indices(foot.shape)[0] <= fy0 + 7)
        ankle_point = (
            float(np.mean(np.where(shoe_top)[1])) if shoe_top.any() else (fx0 + fx1 - 1) / 2.0,
            float(ankle_y),
        )
        joints[f"{side}_hip"] = _normalise_joint(hip_point, width, height)
        joints[f"{side}_knee"] = _normalise_joint(knee_point, width, height)
        joints[f"{side}_ankle"] = _normalise_joint(ankle_point, width, height)

        # Slight underlaps at hips, knees and ankles keep connected parts sealed during rotation.
        thigh = thigh | (_morph(torso, 4, "dilate") & thigh_all & side_mask)
        calf = calf | (_morph(thigh, 6, "dilate") & calf_all & side_mask)
        # The shoe sprite carries a small source-colour overlap above its ankle pivot.

        for role, mask in (
            (f"{side}_thigh", thigh),
            (f"{side}_calf", calf),
            (f"{side}_foot", foot),
        ):
            geometry = _save_rgba_layer(
                rgba, mask, bundle_dir / f"{role}.png", padding=10
            )
            layers.append({
                "id": role, "role": role, **geometry,
                "pivot_x": 0.5, "pivot_y": 0.5,
                "z_index": LEG_ROLE_Z[f"{side}_{role.split('_', 1)[1]}"],
            })
            report["parts"][role] = {
                "pixel_area": int(mask.sum()),
                "bbox": list(_bbox(mask)),
            }
    return layers, joints, report


def _subtract_prop_from_layer(
    bundle_dir: Path,
    layer: dict[str, Any],
    prop_canvas_alpha: np.ndarray,
) -> int:
    path = bundle_dir / str(layer["src"])
    with Image.open(path) as opened:
        image = opened.convert("RGBA")
    x, y = int(layer["x"]), int(layer["y"])
    local_alpha = np.asarray(image.getchannel("A"), dtype=np.uint8).copy()
    prop = prop_canvas_alpha[y:y + image.height, x:x + image.width]
    if prop.shape != local_alpha.shape:
        raise AutoRigError(f"Prop mask does not fit body layer {layer['role']}.")
    removed = int(np.count_nonzero((local_alpha > 0) & (prop > 0)))
    local_alpha[prop > 0] = 0
    image.putalpha(Image.fromarray(local_alpha, mode="L"))
    image.save(path, format="PNG", optimize=True)
    return removed


def _prepare_fingers(
    source: Image.Image,
    bundle_dir: Path,
    character: dict[str, Any],
    finger_manifest_path: Path,
) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, float]],
    dict[str, int],
    dict[str, Any],
]:
    if not finger_manifest_path.is_file():
        return [], {}, {}, {}
    import cv2

    manifest = json.loads(finger_manifest_path.read_text(encoding="utf-8"))
    width, height = source.size
    canvas = manifest.get("canvas") or {}
    if int(canvas.get("width", 0)) != width or int(canvas.get("height", 0)) != height:
        raise ManualReviewRequired("Finger-region manifest canvas does not match the master character.")
    hand_role = str(manifest.get("side") or "right") + "_hand"
    hand_layer = next((layer for layer in character["layers"] if layer["role"] == hand_role), None)
    if hand_layer is None:
        raise ManualReviewRequired(f"Finger controls require the {hand_role} layer.")

    hand_path = bundle_dir / hand_layer["src"]
    with Image.open(hand_path) as opened:
        hand_image = opened.convert("RGBA")
    hand_alpha = np.asarray(hand_image.getchannel("A"), dtype=np.uint8).copy()
    hx, hy = int(hand_layer["x"]), int(hand_layer["y"])
    hand_canvas_alpha = np.zeros((height, width), dtype=np.uint8)
    hand_y1 = min(height, hy + hand_image.height)
    hand_x1 = min(width, hx + hand_image.width)
    hand_y0, hand_x0 = max(0, hy), max(0, hx)
    if hand_x1 <= hand_x0 or hand_y1 <= hand_y0:
        raise ManualReviewRequired(f"The {hand_role} layer lies outside the source canvas.")
    hand_canvas_alpha[hand_y0:hand_y1, hand_x0:hand_x1] = hand_alpha[
        hand_y0 - hy:hand_y1 - hy,
        hand_x0 - hx:hand_x1 - hx,
    ]
    layers, joints, areas = [], {}, {}
    segment_pixel_areas: dict[str, int] = {}
    joint_overlap_pixels: dict[str, int] = {}
    chain_segment_counts: dict[str, int] = {}
    yy, xx = np.mgrid[:height, :width]

    for name, specification in (manifest.get("fingers") or {}).items():
        finger_name = str(name).strip().casefold()
        role = "finger_" + finger_name
        polygon = specification.get("polygon") or []
        pivot = specification.get("pivot") or []
        if len(polygon) < 3 or len(pivot) != 2:
            raise ManualReviewRequired(f"Finger {name} needs a polygon and a two-coordinate pivot.")
        region = Image.new("L", (width, height), 0)
        ImageDraw.Draw(region).polygon([tuple(point) for point in polygon], fill=255)
        region_mask = np.asarray(region, dtype=np.uint8) > 0
        # Expand the authored outline by one source pixel, then clip it back to
        # the existing hand alpha. This recovers narrow contour pixels without
        # painting new skin or crossing into the violin, bow or jacket.
        region_mask = cv2.dilate(
            region_mask.astype(np.uint8),
            np.ones((3, 3), dtype=np.uint8),
            iterations=1,
        ) > 0
        # Every articulated pixel must belong to the independently extracted
        # skin hand. This excludes violin/bow and jacket pixels from the rig.
        finger_mask = _largest_component(region_mask & (hand_canvas_alpha > 12))
        if int(finger_mask.sum()) < 20:
            raise ManualReviewRequired(
                f"Finger region {name} does not overlap the source-aligned {hand_role} skin mask."
            )

        joint_spec = specification.get("joints") or {}
        if all(len(joint_spec.get(key) or []) == 2 for key in ("pip", "dip", "tip")):
            base_point = (float(pivot[0]), float(pivot[1]))
            pip_point = (float(joint_spec["pip"][0]), float(joint_spec["pip"][1]))
            dip_point = (float(joint_spec["dip"][0]), float(joint_spec["dip"][1]))
            tip_point = (float(joint_spec["tip"][0]), float(joint_spec["tip"][1]))
            axis_x = base_point[0] - tip_point[0]
            axis_y = base_point[1] - tip_point[1]
            axis_length_squared = axis_x * axis_x + axis_y * axis_y
            if axis_length_squared < 16:
                raise ManualReviewRequired(f"Finger {name} phalanx landmarks are too close together.")
            pip_t = (
                (pip_point[0] - tip_point[0]) * axis_x +
                (pip_point[1] - tip_point[1]) * axis_y
            ) / axis_length_squared
            dip_t = (
                (dip_point[0] - tip_point[0]) * axis_x +
                (dip_point[1] - tip_point[1]) * axis_y
            ) / axis_length_squared
            if not 0.08 < dip_t < pip_t < 0.94:
                raise ManualReviewRequired(
                    f"Finger {name} joints must progress from fingertip through DIP and PIP to palm."
                )
            projection = (
                (xx - tip_point[0]) * axis_x +
                (yy - tip_point[1]) * axis_y
            ) / axis_length_squared
            # Use a measured source-pixel seam band. The previous fixed 8%
            # overlap left the short little-finger tip with only eight opaque
            # pixels; a 2.8 px target keeps adjacent phalanges connected while
            # respecting the different lengths of the four source fingers.
            axis_length = float(np.sqrt(axis_length_squared))
            overlap = min(0.20, max(0.08, 2.8 / axis_length))
            segment_specs = [
                (role, (projection >= pip_t - overlap), base_point),
                (
                    role + "_middle",
                    (projection >= dip_t - overlap) & (projection <= pip_t + overlap),
                    pip_point,
                ),
                (role + "_tip", (projection <= dip_t + overlap), dip_point),
            ]
            joints[f"right_{finger_name}_base"] = _normalise_joint(base_point, width, height)
            joints[f"right_{finger_name}_pip"] = _normalise_joint(pip_point, width, height)
            joints[f"right_{finger_name}_dip"] = _normalise_joint(dip_point, width, height)
            segment_masks: dict[str, np.ndarray] = {}
            chain_segment_counts[finger_name] = len(segment_specs)
            for segment_role, projection_mask, segment_pivot in segment_specs:
                segment_mask = finger_mask & projection_mask
                segment_masks[segment_role] = segment_mask
                segment_pixels = int(segment_mask.sum())
                segment_pixel_areas[segment_role] = segment_pixels
                if segment_pixels < 4:
                    raise ManualReviewRequired(
                        f"Finger {name} {segment_role.rsplit('_', 1)[-1]} segment has only "
                        f"{segment_pixels} source pixels; at least 4 are required for a separate control."
                    )
                geometry = _save_rgba_layer(
                    source,
                    segment_mask,
                    bundle_dir / f"{segment_role}.png",
                    padding=3,
                )
                layers.append({
                    "id": segment_role, "role": segment_role, **geometry,
                    "pivot_x": 0.5, "pivot_y": 0.5,
                    "z_index": FINGER_Z.get(segment_role, 54),
                })
            base_role, middle_role, tip_role = (
                role, role + "_middle", role + "_tip"
            )
            joint_overlap_pixels[f"{finger_name}_mcp_pip"] = int(np.count_nonzero(
                segment_masks[base_role] & segment_masks[middle_role]
            ))
            joint_overlap_pixels[f"{finger_name}_pip_dip"] = int(np.count_nonzero(
                segment_masks[middle_role] & segment_masks[tip_role]
            ))
        else:
            # Backwards-compatible one-piece finger for older hand manifests.
            geometry = _save_rgba_layer(
                source, finger_mask, bundle_dir / f"{role}.png", padding=3
            )
            layers.append({
                "id": role, "role": role, **geometry,
                "pivot_x": 0.5, "pivot_y": 0.5,
                "z_index": FINGER_Z.get(role, 46),
            })
            segment_pixel_areas[role] = int(finger_mask.sum())
            chain_segment_counts[finger_name] = 1
            joints[f"right_{finger_name}_base"] = _normalise_joint(
                (float(pivot[0]), float(pivot[1])), width, height
            )

        areas[role] = int(finger_mask.sum())

        # Remove the complete original finger silhouette from the stationary
        # palm; the source pixels are then supplied by the overlapping phalanges.
        fx0, fy0, fx1, fy1 = _bbox(finger_mask)
        x0, y0 = max(hx, fx0), max(hy, fy0)
        x1, y1 = min(hx + hand_image.width, fx1), min(hy + hand_image.height, fy1)
        if x1 > x0 and y1 > y0:
            cut = finger_mask[y0:y1, x0:x1]
            local = hand_alpha[y0 - hy:y1 - hy, x0 - hx:x1 - hx]
            local[cut] = 0

    # The stationary palm should be one connected source silhouette. Remove
    # detached alpha fragments left by the original cutout after all four
    # fingers have been moved to their own articulated layers.
    palm_binary = (hand_alpha > 12).astype(np.uint8)
    palm_component_total, _palm_labels, _palm_stats, _palm_centroids = (
        cv2.connectedComponentsWithStats(palm_binary, connectivity=8)
    )
    palm_components_before = max(0, int(palm_component_total) - 1)
    palm_pixels_before = int(np.count_nonzero(palm_binary))
    palm_keep = _largest_component(palm_binary) if palm_components_before else np.zeros_like(
        palm_binary, dtype=bool
    )
    palm_alpha_after = np.where(palm_keep, hand_alpha, 0).astype(np.uint8)
    palm_pixels_after = int(np.count_nonzero(palm_alpha_after))
    hand_alpha = palm_alpha_after
    palm_components_after = 1 if palm_pixels_after else 0

    hand_image.putalpha(Image.fromarray(hand_alpha, mode="L"))
    hand_image.save(hand_path, format="PNG", optimize=True)
    quality = {
        "method": "one_pixel_source_mask_expansion_metric_joint_seams_connected_palm_cleanup",
        "polygon_expansion_radius_px": 1,
        "target_joint_overlap_px": 2.8,
        "chain_count": len(chain_segment_counts),
        "segments_per_chain": chain_segment_counts,
        "minimum_segment_pixels": min(segment_pixel_areas.values(), default=0),
        "minimum_joint_overlap_pixels": min(joint_overlap_pixels.values(), default=0),
        "little_fingertip_pixels": segment_pixel_areas.get("finger_little_tip", 0),
        "segment_pixel_areas": segment_pixel_areas,
        "joint_overlap_pixels": joint_overlap_pixels,
        "palm_components_before_cleanup": palm_components_before,
        "palm_components_after_cleanup": palm_components_after,
        "palm_speckle_components_removed": max(0, palm_components_before - palm_components_after),
        "palm_speckle_pixels_removed": max(0, palm_pixels_before - palm_pixels_after),
    }
    return layers, joints, areas, quality


def _polygon_mask(
    shape: tuple[int, int],
    polygon: list[list[float]] | list[tuple[float, float]],
) -> np.ndarray:
    """Rasterize one source-aligned polygon into a full-canvas boolean mask."""
    height, width = shape
    if len(polygon) < 3:
        raise ManualReviewRequired("Every authored performance region needs at least three polygon points.")
    points = []
    for point in polygon:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ManualReviewRequired("Performance region polygon points must be [x, y] pairs.")
        x, y = float(point[0]), float(point[1])
        if not np.isfinite(x) or not np.isfinite(y):
            raise ManualReviewRequired("Performance region polygon coordinates must be finite.")
        if not 0 <= x < width or not 0 <= y < height:
            raise ManualReviewRequired(
                f"Performance region point ({x:.1f}, {y:.1f}) lies outside the {width}x{height} source."
            )
        points.append((round(x), round(y)))
    canvas = Image.new("L", (width, height), 0)
    ImageDraw.Draw(canvas).polygon(points, fill=255)
    return np.asarray(canvas, dtype=np.uint8) > 0


def _skin_material_mask(
    source: Image.Image,
    allowed: np.ndarray,
    *,
    thresholds: dict[str, Any],
    excluded: tuple[np.ndarray, ...] = (),
) -> np.ndarray:
    """Find skin only inside a reviewed hand polygon, excluding prop silhouettes."""
    rgba = np.asarray(source.convert("RGBA"), dtype=np.uint8)
    red, green, blue = (rgba[:, :, index].astype(np.int16) for index in range(3))
    red_min = int(thresholds.get("red_min", 90))
    red_max = int(thresholds.get("red_max", 240))
    green_min = int(thresholds.get("green_min", 45))
    blue_min = int(thresholds.get("blue_min", 0))
    red_green_min = int(thresholds.get("red_minus_green_min", 20))
    green_blue_min = int(thresholds.get("green_minus_blue_min", 10))
    red_blue_min = int(thresholds.get("red_minus_blue_min", 35))
    skin = (
        (red >= red_min) & (red <= red_max) &
        (green >= green_min) & (blue >= blue_min) &
        ((red - green) >= red_green_min) &
        ((green - blue) >= green_blue_min) &
        ((red - blue) >= red_blue_min) &
        (rgba[:, :, 3] > 12) &
        np.asarray(allowed, dtype=bool)
    )
    for blocked in excluded:
        skin &= ~np.asarray(blocked, dtype=bool)
    try:
        import cv2
    except ImportError as exc:
        raise AutoRigError("OpenCV is required for source-aligned hand segmentation.") from exc
    skin = cv2.morphologyEx(
        skin.astype(np.uint8),
        cv2.MORPH_CLOSE,
        np.ones((3, 3), dtype=np.uint8),
    ) > 0
    # Retain a narrow outline fringe without expanding into nearby instrument pixels.
    skin = cv2.dilate(
        skin.astype(np.uint8),
        np.ones((3, 3), dtype=np.uint8),
        iterations=1,
    ) > 0
    skin &= np.asarray(allowed, dtype=bool) & (rgba[:, :, 3] > 12)
    for blocked in excluded:
        skin &= ~np.asarray(blocked, dtype=bool)
    return skin


def _reconstruct_violin_fingerboard_backplate(
    source: Image.Image,
    bundle_dir: Path,
    *,
    violin_specification: dict[str, Any],
    hand_layer: dict[str, Any],
    violin_canvas_alpha: np.ndarray,
    dilation_radius: int = 1,
    inpaint_radius: int = 6,
) -> dict[str, int | str | bool]:
    """Restore the violin fingerboard beneath the source-aligned fretting hand.

    The supplied violin prop has an incomplete alpha cutout along the neck.
    The independent palm/finger layers cover the original hand, but gaps
    between their small sprites reveal the inpainted body plate through those
    missing neck pixels. This creates a narrow, authored fingerboard backplate
    from the preserved source crop, reconstructs source-hidden wood/string
    texture beneath the hand, and extends the violin prop mask so the parent
    underpaint is cleared behind the restored instrument.
    """
    if not 0 <= dilation_radius <= 3:
        raise ValueError("Hand/finger seam dilation must be between zero and three pixels.")
    if not 1 <= inpaint_radius <= 15:
        raise ValueError("Fingerboard inpaint radius must be between one and fifteen pixels.")
    try:
        import cv2
    except ImportError as exc:
        raise AutoRigError("OpenCV is required to reconstruct the violin fingerboard backplate.") from exc

    hand_path = bundle_dir / str(hand_layer["src"])
    violin_path = bundle_dir / f"prop-violin{Path(str(violin_specification['src'])).suffix.lower()}"
    if not hand_path.is_file() or not violin_path.is_file():
        raise AutoRigError("The source-derived hand or violin prop asset is missing.")
    with Image.open(hand_path) as opened:
        hand_alpha = np.asarray(opened.convert("RGBA").getchannel("A"), dtype=np.uint8)
    with Image.open(violin_path) as opened:
        violin_image = opened.convert("RGBA")
    violin_rgba = np.asarray(violin_image, dtype=np.uint8).copy()

    source_rgba = source.convert("RGBA")
    source_width, source_height = source_rgba.size
    x, y = int(violin_specification["x"]), int(violin_specification["y"])
    height, width = violin_rgba.shape[:2]
    if x < 0 or y < 0 or x + width > source_width or y + height > source_height:
        raise ManualReviewRequired("The violin prop crop lies outside the preserved source canvas.")
    if np.asarray(violin_canvas_alpha).shape != (source_height, source_width):
        raise AutoRigError("The global violin prop mask does not match the source canvas.")

    polygon = violin_specification.get("hand_backplate_polygon") or []
    if len(polygon) < 3:
        raise ManualReviewRequired("The violin manifest must define a source-aligned hand backplate polygon.")
    for point in polygon:
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ManualReviewRequired("Backplate polygon points must be [x, y] prop-local pairs.")
        px, py = float(point[0]), float(point[1])
        if not np.isfinite(px) or not np.isfinite(py) or not (0 <= px < width and 0 <= py < height):
            raise ManualReviewRequired("A backplate polygon point lies outside the violin prop crop.")

    # Rasterize at 4x resolution so the neck extension has antialiased edges.
    supersample = 4
    polygon_image = Image.new("L", (width * supersample, height * supersample), 0)
    ImageDraw.Draw(polygon_image).polygon(
        [(round(float(px) * supersample), round(float(py) * supersample)) for px, py in polygon],
        fill=255,
    )
    backplate_alpha = np.asarray(
        polygon_image.resize((width, height), Image.Resampling.LANCZOS),
        dtype=np.uint8,
    )
    source_crop = source_rgba.crop((x, y, x + width, y + height))
    source_pixels = np.asarray(source_crop, dtype=np.uint8)
    source_alpha = source_pixels[:, :, 3]
    backplate_alpha = np.minimum(backplate_alpha, source_alpha)

    # Map the complete source-aligned palm/finger silhouette into prop space.
    hand_canvas = np.zeros((source_height, source_width), dtype=np.uint8)
    hand_x, hand_y = int(hand_layer["x"]), int(hand_layer["y"])
    hx0, hy0 = max(0, hand_x), max(0, hand_y)
    hx1, hy1 = min(source_width, hand_x + hand_alpha.shape[1]), min(source_height, hand_y + hand_alpha.shape[0])
    if hx1 > hx0 and hy1 > hy0:
        hand_canvas[hy0:hy1, hx0:hx1] = hand_alpha[
            hy0 - hand_y:hy1 - hand_y,
            hx0 - hand_x:hx1 - hand_x,
        ]
    local_hand = hand_canvas[y:y + height, x:x + width] > 12
    if dilation_radius:
        kernel = np.ones((dilation_radius * 2 + 1, dilation_radius * 2 + 1), dtype=np.uint8)
        local_hand = cv2.dilate(local_hand.astype(np.uint8), kernel, iterations=1) > 0

    original_prop_alpha = violin_rgba[:, :, 3].copy()
    original_prop_mask = np.asarray(violin_canvas_alpha, dtype=np.uint8).copy()
    backplate_mask = backplate_alpha > 12
    repair_mask = local_hand & backplate_mask
    # Restore the underlying source crop outside the hand, and use local
    # inpainting only for the pixels hidden by source skin. The hand sprite
    # itself remains the foreground layer at render time.
    repaired_source_rgb = cv2.inpaint(
        source_pixels[:, :, :3],
        repair_mask.astype(np.uint8) * 255,
        inpaint_radius,
        cv2.INPAINT_TELEA,
    ) if repair_mask.any() else source_pixels[:, :, :3].copy()

    patch_rgb = source_pixels[:, :, :3].copy()
    patch_rgb[repair_mask] = repaired_source_rgb[repair_mask]
    violin_rgba[backplate_mask, :3] = patch_rgb[backplate_mask]
    violin_rgba[:, :, 3] = np.maximum(violin_rgba[:, :, 3], backplate_alpha)

    # Preserve the legacy overlap repair for any source skin already present
    # elsewhere inside the extracted violin alpha, but never cut prop pixels.
    outside_backplate_hand = local_hand & ~backplate_mask & (original_prop_alpha > 12)
    if outside_backplate_hand.any():
        additional_rgb = cv2.inpaint(
            violin_rgba[:, :, :3],
            outside_backplate_hand.astype(np.uint8) * 255,
            inpaint_radius,
            cv2.INPAINT_TELEA,
        )
        violin_rgba[outside_backplate_hand, :3] = additional_rgb[outside_backplate_hand]

    new_local_alpha = violin_rgba[:, :, 3]
    global_view = original_prop_mask[y:y + height, x:x + width]
    global_view[:, :] = np.maximum(global_view, new_local_alpha)
    violin_canvas_alpha[:, :] = original_prop_mask
    Image.fromarray(violin_rgba, mode="RGBA").save(
        violin_path, format="WEBP", quality=98, method=6
    )

    added_alpha = int(np.count_nonzero((backplate_alpha > 12) & (original_prop_alpha <= 12)))
    hand_holes_filled = int(np.count_nonzero(repair_mask & (original_prop_alpha <= 12)))
    return {
        "method": "source_aligned_fingerboard_backplate_rgb_reconstruction",
        "backplate_pixels_added": added_alpha,
        "hand_hole_pixels_filled": hand_holes_filled,
        "source_hand_pixels_reconstructed": int(repair_mask.sum()),
        "existing_hand_overlap_pixels_reconstructed": int(outside_backplate_hand.sum()),
        "hand_pixels": int(np.count_nonzero(hand_alpha)),
        "dilation_radius": int(dilation_radius),
        "prop_alpha_extended": bool(added_alpha > 0),
        "parent_prop_mask_updated": True,
        "asset": violin_path.name,
    }


def _decontaminate_edge_matte_rgb(
    source: Image.Image,
    *,
    protected_masks: tuple[np.ndarray, ...] = (),
    minimum_brightness: int = 105,
    maximum_channel_spread: int = 65,
    minimum_interior_contrast: int = 24,
    edge_band_radius: float = 4.2,
    sample_radius: int = 5,
) -> tuple[Image.Image, dict[str, Any]]:
    """Remove pale matte spill several pixels inside the silhouette boundary.

    The previous pass considered only pixels touching transparency. That left
    multi-pixel white fringes on dark hair, jacket edges and shoes untouched.
    This pass measures distance from the exterior alpha boundary, then replaces
    only bright, nearly neutral edge pixels whose local interior is materially
    darker. It samples nearby *interior* character pixels, not the backdrop.

    Alpha and silhouette geometry are never changed. Instrument masks and a
    small perimeter around them are protected so bow hair and violin highlights
    remain source-faithful. Genuine interior highlights are outside the edge
    band and are therefore preserved.
    """
    if not 0 <= int(minimum_brightness) <= 255:
        raise ValueError("Matte brightness threshold must be between zero and 255.")
    if not 0 <= int(maximum_channel_spread) <= 255:
        raise ValueError("Matte channel spread must be between zero and 255.")
    if not 1 <= int(minimum_interior_contrast) <= 180:
        raise ValueError("Interior contrast threshold must be between one and 180.")
    if not np.isfinite(edge_band_radius) or edge_band_radius <= 0:
        raise ValueError("Edge band radius must be a positive finite value.")
    if not 1 <= int(sample_radius) <= 12:
        raise ValueError("Matte sample radius must be between one and twelve.")

    import cv2

    rgba = source.convert("RGBA")
    pixels = np.asarray(rgba, dtype=np.uint8).copy()
    rgb = pixels[:, :, :3]
    alpha = pixels[:, :, 3]
    height, width = alpha.shape
    visible = alpha > 12

    protected = np.zeros((height, width), dtype=bool)
    for mask in protected_masks:
        candidate_mask = np.asarray(mask, dtype=bool)
        if candidate_mask.shape != (height, width):
            raise AutoRigError("A protected matte-cleanup region does not match the source canvas.")
        protected |= candidate_mask

    # Protect the immediate prop perimeter as well as visible prop pixels.
    if protected.any():
        protected = cv2.dilate(
            protected.astype(np.uint8),
            cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
            iterations=1,
        ) > 0

    # The alpha distance transform also finds edges around enclosed transparent
    # holes, where background-removal tools sometimes leave pale islands.
    interior_distance = cv2.distanceTransform(
        visible.astype(np.uint8), cv2.DIST_L2, 5
    )
    minimum = rgb.min(axis=2).astype(np.int16)
    maximum = rgb.max(axis=2).astype(np.int16)
    luminance = rgb.astype(np.float32).mean(axis=2)

    neutral_edge_band = (
        visible
        & ~protected
        & (interior_distance <= float(edge_band_radius))
        & (minimum >= int(minimum_brightness))
        & ((maximum - minimum) <= int(maximum_channel_spread))
    )
    candidate_y, candidate_x = np.where(neutral_edge_band)
    matte_candidates = np.zeros((height, width), dtype=bool)
    changed = 0
    radius = int(sample_radius)

    # Inspect only the relatively small set of pale edge candidates. A
    # candidate is corrected only when its local interior samples are darker
    # by the configured contrast threshold; warm skin and actual highlights
    # are not blanket-colour-shifted.
    for y, x in zip(candidate_y.tolist(), candidate_x.tolist()):
        y0 = max(0, y - radius)
        y1 = min(height, y + radius + 1)
        x0 = max(0, x - radius)
        x1 = min(width, x + radius + 1)

        local_visible = visible[y0:y1, x0:x1]
        local_protected = protected[y0:y1, x0:x1]
        local_distance = interior_distance[y0:y1, x0:x1]
        local_candidates = neutral_edge_band[y0:y1, x0:x1]
        local_rgb = rgb[y0:y1, x0:x1]

        # Move inward relative to this sample's distance from the exterior.
        # Excluding other pale candidates prevents a multi-pixel halo from
        # contaminating its own replacement colour.
        local_interior = (
            local_visible
            & ~local_protected
            & ~local_candidates
            & (local_distance >= float(interior_distance[y, x]) + 1.0)
        )
        if int(local_interior.sum()) < 3:
            continue

        interior_rgb = local_rgb[local_interior].astype(np.float32)
        replacement = np.median(interior_rgb, axis=0)
        interior_luminance = float(replacement.mean())
        if float(luminance[y, x]) < interior_luminance + float(minimum_interior_contrast):
            continue

        pixels[y, x, :3] = np.clip(np.rint(replacement), 0, 255).astype(np.uint8)
        matte_candidates[y, x] = True
        changed += 1

    # A source-level invariant: this pass must preserve the complete alpha plane.
    if not np.array_equal(pixels[:, :, 3], alpha):
        raise AutoRigError("Edge matte colour repair unexpectedly changed source alpha.")

    report = {
        "method": "distance_aware_neutral_matte_decontamination",
        "edge_band_radius": float(edge_band_radius),
        "sample_radius": int(sample_radius),
        "candidate_pixels": int(neutral_edge_band.sum()),
        "pixels_recoloured": changed,
        "protected_prop_pixels": int(protected.sum()),
        "minimum_brightness": int(minimum_brightness),
        "maximum_channel_spread": int(maximum_channel_spread),
        "minimum_interior_contrast": int(minimum_interior_contrast),
        "source_alpha_preserved": True,
        "source_silhouette_geometry_preserved": True,
        "instrument_props_protected": True,
        "interior_highlights_preserved": True,
        "visual_review_required": True,
    }
    return Image.fromarray(pixels, mode="RGBA"), report

def _authored_performance_layers(
    source: Image.Image,
    bundle_dir: Path,
    *,
    regions_manifest_path: Path,
    prop_masks: dict[str, np.ndarray],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, float]], dict[str, Any], np.ndarray]:
    """Extract limb layers from reviewed, source-aligned polygons, not human-parser guesses.

    The manifest is tied to the exact 441x755 source canvas and keeps the hand,
    sleeve, thigh, calf and shoe boundaries editable and auditable.
    """
    manifest = json.loads(regions_manifest_path.read_text(encoding="utf-8"))
    canvas = manifest.get("canvas") or {}
    width, height = source.size
    if int(canvas.get("width", 0)) != width or int(canvas.get("height", 0)) != height:
        raise ManualReviewRequired(
            "The authored performance-region manifest canvas does not match the intact source."
        )
    if int(manifest.get("schema_version", 0)) != 1:
        raise ManualReviewRequired("Unsupported performance-region manifest schema.")
    regions = manifest.get("regions") or {}
    required_roles = {
        "left_upper_arm", "left_forearm", "left_hand",
        "right_upper_arm", "right_forearm", "right_hand",
        "left_thigh", "left_calf", "left_foot",
        "right_thigh", "right_calf", "right_foot",
    }
    missing = sorted(required_roles - set(regions))
    if missing:
        raise ManualReviewRequired("Performance-region manifest is missing: " + ", ".join(missing))

    source_rgba = source.convert("RGBA")
    pixels = np.asarray(source_rgba, dtype=np.uint8)
    alpha = pixels[:, :, 3]
    rgb = pixels[:, :, :3]
    shape = alpha.shape
    blocked_props = tuple(
        np.asarray(mask, dtype=bool)
        for name, mask in prop_masks.items()
        if name in {"violin", "bow"}
    )
    # Hand polygons are narrow and material-filtered; retain skin over both
    # instrument props so the hands can be composited in front of violin and bow.
    skin_thresholds = manifest.get("skin_mask") or {}
    polygon_masks: dict[str, np.ndarray] = {}
    for role, specification in regions.items():
        method = str(specification.get("method") or "polygon")
        if method == "dark_connected_bottom_component":
            continue
        polygon_masks[role] = _polygon_mask(shape, specification.get("polygon") or [])

    screen_split_x = float(manifest.get("screen_side_split_x", width / 2))
    if not 0 < screen_split_x < width:
        raise ManualReviewRequired("The performance-region screen-side split is outside the source canvas.")

    moving_masks: dict[str, np.ndarray] = {}
    hand_masks: dict[str, np.ndarray] = {}
    for role in ("left_hand", "right_hand"):
        specification = regions[role]
        allowed = polygon_masks[role]
        hand_masks[role] = _skin_material_mask(
            source_rgba,
            allowed,
            thresholds=skin_thresholds,
            excluded=(),
        )
        minimum = int(specification.get("minimum_pixels", 200))
        if int(hand_masks[role].sum()) < minimum:
            raise ManualReviewRequired(
                f"The {role} source-aligned skin mask contains only {int(hand_masks[role].sum())} pixels."
            )

    layers: list[dict[str, Any]] = []
    joints: dict[str, dict[str, float]] = {}
    report: dict[str, Any] = {
        "method": "authored_source_aligned_polygon_regions_v1",
        "manifest": regions_manifest_path.name,
        "canvas": [width, height],
        "screen_side_split_x": round(screen_split_x, 2),
        "parts": {},
        "joint_anchors_px": manifest.get("joints") or {},
        "review_required": True,
    }

    # Upper arm polygons stop at the elbow. The distal polygon owns the
    # forearm; a small circular overlap is retained under the child segment.
    for side in ("left", "right"):
        upper_role = f"{side}_upper_arm"
        forearm_role = f"{side}_forearm"
        upper_spec = regions[upper_role]
        forearm_spec = regions[forearm_role]
        upper_region = polygon_masks[upper_role]
        forearm_region = polygon_masks[forearm_role]
        anchor = (manifest.get("joints") or {}).get(f"{side}_elbow")
        if not anchor or len(anchor) != 2:
            raise ManualReviewRequired(f"The {side} elbow anchor must be authored as [x, y].")
        ex, ey = float(anchor[0]), float(anchor[1])
        overlap_radius = int(upper_spec.get("elbow_overlap_radius", 8))
        yy, xx = np.ogrid[:height, :width]
        joint_underlap = (xx - ex) ** 2 + (yy - ey) ** 2 <= overlap_radius ** 2
        upper_region = upper_region & (~forearm_region | joint_underlap)
        forearm_mask = forearm_region & (alpha > 12)
        forearm_mask &= ~hand_masks[f"{side}_hand"]
        wrist = (manifest.get("joints") or {}).get(f"{side}_wrist")
        if not wrist or len(wrist) != 2:
            raise ManualReviewRequired(f"The {side} wrist anchor must be authored as [x, y].")
        wx, wy = float(wrist[0]), float(wrist[1])
        wrist_radius = int(regions[forearm_role].get("wrist_overlap_radius", 8))
        wrist_underlap = (xx - wx) ** 2 + (yy - wy) ** 2 <= wrist_radius ** 2
        # The forearm carries a tiny copy beneath the hand; the hand remains
        # the upper layer and owns the visible skin contour at the wrist.
        forearm_mask |= wrist_underlap & hand_masks[f"{side}_hand"] & (alpha > 12)
        for role, mask in (
            (upper_role, upper_region & (alpha > 12)),
            (forearm_role, forearm_mask),
        ):
            mask &= ~hand_masks[f"{side}_hand"] if role == upper_role else np.ones(shape, dtype=bool)
            for blocked in blocked_props:
                mask &= ~blocked
            minimum = int(regions[role].get("minimum_pixels", 100))
            area = int(mask.sum())
            if area < minimum:
                raise ManualReviewRequired(
                    f"The {role} source-aligned sleeve mask contains only {area} pixels."
                )
            moving_masks[role] = mask

    for role, mask in hand_masks.items():
        moving_masks[role] = mask

    # The distal part owns the knee and ankle seams. Keep only local overlap
    # disks so rotation cannot expose the inpainted parent plate at either joint.
    for side in ("left", "right"):
        knee = (manifest.get("joints") or {}).get(f"{side}_knee")
        ankle = (manifest.get("joints") or {}).get(f"{side}_ankle")
        if not knee or len(knee) != 2 or not ankle or len(ankle) != 2:
            raise ManualReviewRequired(f"The {side} knee and ankle anchors are required.")
        kx, ky = float(knee[0]), float(knee[1])
        ax, ay = float(ankle[0]), float(ankle[1])
        yy, xx = np.ogrid[:height, :width]
        knee_radius = int(regions[f"{side}_thigh"].get("knee_overlap_radius", 9))
        ankle_radius = int(regions[f"{side}_calf"].get("ankle_overlap_radius", 8))
        knee_underlap = (xx - kx) ** 2 + (yy - ky) ** 2 <= knee_radius ** 2
        ankle_underlap = (xx - ax) ** 2 + (yy - ay) ** 2 <= ankle_radius ** 2

        thigh = polygon_masks[f"{side}_thigh"] & (alpha > 12)
        calf = polygon_masks[f"{side}_calf"] & (alpha > 12)
        foot_role = f"{side}_foot"
        foot_spec = regions[foot_role]
        if str(foot_spec.get("method") or "") != "dark_connected_bottom_component":
            foot_mask = polygon_masks[foot_role] & (alpha > 12)
        else:
            foot_mask = _foot_mask(
                rgb,
                alpha,
                side=side,
                split_x=screen_split_x,
            )
        thigh &= ~calf | knee_underlap
        # The source polygon can extend into the shoe, especially after Auto-Rig
        # restores transparent body holes. Remove that duplicate area first,
        # then retain only the small authored ankle overlap disk.
        calf &= ~foot_mask | ankle_underlap
        calf |= ankle_underlap & foot_mask
        # Keep leg material separate from shoes and preserve a small shared seam.
        minimum_thigh = int(regions[f"{side}_thigh"].get("minimum_pixels", 500))
        minimum_calf = int(regions[f"{side}_calf"].get("minimum_pixels", 500))
        if int(thigh.sum()) < minimum_thigh:
            raise ManualReviewRequired(f"The {side} thigh mask became too small after knee seam extraction.")
        if int(calf.sum()) < minimum_calf:
            raise ManualReviewRequired(f"The {side} calf mask became too small after ankle seam extraction.")
        if int(foot_mask.sum()) < int(foot_spec.get("minimum_pixels", 500)):
            raise ManualReviewRequired(
                f"The {foot_role} shoe mask contains only {int(foot_mask.sum())} pixels."
            )
        moving_masks[f"{side}_thigh"] = thigh
        moving_masks[f"{side}_calf"] = calf
        moving_masks[foot_role] = foot_mask

    # Save all twelve independently controllable limb/hand layers.
    z_defaults = {
        "left_upper_arm": 20, "right_upper_arm": 21,
        "left_forearm": 30, "right_forearm": 31,
        "left_hand": 40, "right_hand": 42,
        "left_thigh": 4, "right_thigh": 5,
        "left_calf": 6, "right_calf": 7,
        "left_foot": 8, "right_foot": 9,
    }
    for role in sorted(required_roles, key=lambda item: z_defaults[item]):
        mask = moving_masks[role]
        specification = regions[role]
        geometry = _save_rgba_layer(
            source_rgba,
            mask,
            bundle_dir / f"{role}.png",
            padding=6,
        )
        layer = {
            "id": role,
            "role": role,
            **geometry,
            "pivot_x": 0.5,
            "pivot_y": 0.5,
            "z_index": int(specification.get("z_index", z_defaults[role])),
        }
        layers.append(layer)
        ys, xs = np.where(mask)
        report["parts"][role] = {
            "pixel_area": int(mask.sum()),
            "bbox": [int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1],
            "material": "skin" if role.endswith("_hand") else "source_rgba",
            "minimum_pixels": int(specification.get("minimum_pixels", 0)),
        }

    # Validate every joint overlap stays local; these parent underlaps seal
    # articulated seams without copying broad duplicate areas.
    for side in ("left", "right"):
        elbow_overlap = int((moving_masks[f"{side}_upper_arm"] & moving_masks[f"{side}_forearm"]).sum())
        wrist_overlap = int((moving_masks[f"{side}_forearm"] & moving_masks[f"{side}_hand"]).sum())
        knee_overlap = int((moving_masks[f"{side}_thigh"] & moving_masks[f"{side}_calf"]).sum())
        ankle_overlap = int((moving_masks[f"{side}_calf"] & moving_masks[f"{side}_foot"]).sum())
        overlaps = {
            f"{side}_elbow": elbow_overlap,
            f"{side}_wrist": wrist_overlap,
            f"{side}_knee": knee_overlap,
            f"{side}_ankle": ankle_overlap,
        }
        for joint_name, overlap_pixels in overlaps.items():
            if overlap_pixels > 500:
                raise ManualReviewRequired(
                    f"The {joint_name} underlap is too broad ({overlap_pixels} pixels); refine the boundary."
                )
            report.setdefault("joint_overlap_pixels", {})[joint_name] = overlap_pixels

    joint_manifest = manifest.get("joints") or {}
    expected_joints = (
        "left_shoulder", "left_elbow", "left_wrist",
        "right_shoulder", "right_elbow", "right_wrist",
        "left_hip", "left_knee", "left_ankle",
        "right_hip", "right_knee", "right_ankle",
    )
    for name in expected_joints:
        point = joint_manifest.get(name)
        if not isinstance(point, (list, tuple)) or len(point) != 2:
            raise ManualReviewRequired(f"Missing authored joint anchor {name}.")
        x, y = float(point[0]), float(point[1])
        if not 0 <= x < width or not 0 <= y < height:
            raise ManualReviewRequired(f"Joint anchor {name} lies outside the source canvas.")
        joints[name] = _normalise_joint((x, y), width, height)

    moving_union = np.zeros(shape, dtype=bool)
    for mask in moving_masks.values():
        moving_union |= mask
    report["moving_region_pixels"] = int(moving_union.sum())
    report["independent_layer_count"] = len(layers)
    report["visual_review_required"] = True
    return layers, joints, report, moving_union


def _restore_bow_hair_in_prop_asset(
    source: Image.Image,
    bundle_dir: Path,
    bow_specification: dict[str, Any],
    bow_canvas_alpha: np.ndarray,
) -> dict[str, Any]:
    """Move the pale bow-hair strand into the same animated sprite as its stick.

    The source illustration contains both the wooden bow stick and a separate
    near-white hair strand. The existing extracted prop only captured the
    stick, leaving the hair baked into static torso pixels. Extract the largest
    bright neutral component in a narrow band beside the stick, add those exact
    source pixels to the bow sprite, and extend the source-clear mask so both
    parts receive identical transforms at render time.
    """
    try:
        import cv2
    except ImportError as exc:
        raise AutoRigError("OpenCV is required to separate the pale bow-hair strand.") from exc

    source_rgba = source.convert("RGBA")
    source_pixels = np.asarray(source_rgba, dtype=np.uint8)
    height, width = source_pixels.shape[:2]
    bow_mask = np.asarray(bow_canvas_alpha, dtype=np.uint8) > 12
    if bow_mask.shape != (height, width):
        raise AutoRigError("The bow mask must match the source canvas.")

    x, y = int(round(float(bow_specification["x"]))), int(round(float(bow_specification["y"])))
    prop_path = bundle_dir / str(bow_specification["src"])
    if not prop_path.is_file():
        raise AutoRigError(f"Missing extracted bow sprite: {prop_path.name}")
    with Image.open(prop_path) as opened:
        bow_sprite = opened.convert("RGBA")
    sprite_width, sprite_height = bow_sprite.size
    if x < 0 or y < 0 or x + sprite_width > width or y + sprite_height > height:
        raise ManualReviewRequired("The bow sprite does not fit the full-body source coordinate frame.")

    source_crop = source_rgba.crop((x, y, x + sprite_width, y + sprite_height))
    local_rgb = source_pixels[y:y + sprite_height, x:x + sprite_width, :3].astype(np.int16)
    local_alpha = source_pixels[y:y + sprite_height, x:x + sprite_width, 3]
    local_bow = bow_mask[y:y + sprite_height, x:x + sprite_width]

    distance = cv2.distanceTransform(
        (~bow_mask).astype(np.uint8),
        cv2.DIST_L2,
        5,
    )[y:y + sprite_height, x:x + sprite_width]
    luminance = local_rgb.mean(axis=2)
    channel_spread = local_rgb.max(axis=2) - local_rgb.min(axis=2)
    candidates = (
        (local_alpha > 12)
        & ~local_bow
        & (distance >= 1.0)
        & (distance <= 6.0)
        & (luminance >= 150.0)
        & (channel_spread <= 90)
    )

    component_count, labels, stats, _centroids = cv2.connectedComponentsWithStats(
        candidates.astype(np.uint8),
        8,
    )
    if component_count <= 1:
        raise ManualReviewRequired("No separate bright bow-hair strand was found beside the bow stick.")
    largest_index = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    hair_pixels = int(stats[largest_index, cv2.CC_STAT_AREA])
    if hair_pixels < 250:
        raise ManualReviewRequired(
            f"The extracted bow-hair component is too small ({hair_pixels} pixels)."
        )
    hair_mask = labels == largest_index
    ys, xs = np.where(hair_mask)
    hair_bbox = [
        int(xs.min()) + x,
        int(ys.min()) + y,
        int(xs.max()) + x + 1,
        int(ys.max()) + y + 1,
    ]

    hair_pixels_rgba = np.zeros_like(np.asarray(bow_sprite, dtype=np.uint8))
    hair_pixels_rgba[hair_mask] = np.asarray(source_crop, dtype=np.uint8)[hair_mask]
    hair_layer = Image.fromarray(hair_pixels_rgba, mode="RGBA")
    combined = Image.alpha_composite(bow_sprite, hair_layer)

    destination = bundle_dir / "prop-bow-with-hair.png"
    combined.save(destination, format="PNG", optimize=True)

    # Extend the source-coordinate mask with the recovered hair so static
    # plates, underpaint and limb extraction all remove the same original pixels.
    updated_mask = np.asarray(bow_canvas_alpha, dtype=np.uint8).copy()
    local_updated = updated_mask[y:y + sprite_height, x:x + sprite_width]
    local_updated[hair_mask] = np.maximum(
        local_updated[hair_mask],
        local_alpha[hair_mask],
    )
    return {
        "method": "largest_neutral_source_component_recovered_into_animated_bow",
        "src": destination.name,
        "pixels_added": hair_pixels,
        "candidate_pixels": int(candidates.sum()),
        "selected_component_count": 1,
        "hair_bbox": hair_bbox,
        "source_alpha_preserved": True,
        "shared_bow_transform": True,
        "source_mask_extended": True,
        "review_required": True,
    }, updated_mask


def _extend_torso_layer_with_violin_backplate(
    source: Image.Image,
    bundle_dir: Path,
    character: dict[str, Any],
    prop_masks: dict[str, np.ndarray],
    *,
    moving_mask: np.ndarray,
) -> dict[str, Any]:
    """Extend the torso plate with source-faithful violin pixels behind its prop.

    The violin is torso-mounted, so its source pixels can remain on the torso
    plate beneath the separate violin sprite. This restores the complete
    instrument underlay (including pixels beyond the old torso crop) and
    closes tiny alpha pinholes using original source RGB rather than inpaint.
    Bow and independently moving body pixels are excluded to prevent ghost
    copies. The torso's absolute pivot is preserved when its crop is extended.
    """
    try:
        import cv2
    except ImportError as exc:
        raise AutoRigError("OpenCV is required to extend the violin source backplate.") from exc

    torso_layer = next(
        (layer for layer in character.get("layers", []) if layer.get("role") == "torso"),
        None,
    )
    if torso_layer is None:
        raise ManualReviewRequired("A torso layer is required for the violin source backplate.")
    if "violin" not in prop_masks or "bow" not in prop_masks:
        raise ManualReviewRequired("Both violin and bow source masks are required for the torso backplate.")

    source_rgba = source.convert("RGBA")
    source_pixels = np.asarray(source_rgba, dtype=np.uint8)
    height, width = source_pixels.shape[:2]
    source_alpha = source_pixels[:, :, 3]
    violin = np.asarray(prop_masks["violin"], dtype=np.uint8) > 12
    bow = np.asarray(prop_masks["bow"], dtype=np.uint8) > 12
    moving = np.asarray(moving_mask, dtype=bool)
    if any(mask.shape != (height, width) for mask in (violin, bow, moving)):
        raise AutoRigError("Violin, bow and moving masks must match the source canvas.")

    asset_path = bundle_dir / str(torso_layer.get("src") or "")
    if not asset_path.is_file():
        raise AutoRigError(f"Missing torso source plate: {asset_path.name}")
    with Image.open(asset_path) as opened:
        original_torso = opened.convert("RGBA")

    old_x = int(round(float(torso_layer["x"])))
    old_y = int(round(float(torso_layer["y"])))
    old_width, old_height = original_torso.size
    old_pivot_x = float(torso_layer.get("pivot_x", 0.5))
    old_pivot_y = float(torso_layer.get("pivot_y", 0.5))
    pivot_source_x = old_x + old_width * old_pivot_x
    pivot_source_y = old_y + old_height * old_pivot_y

    # Close only very small holes inside the extracted violin silhouette.
    # The resulting pixels still come from the original full-body source.
    closed_violin = cv2.morphologyEx(
        violin.astype(np.uint8),
        cv2.MORPH_CLOSE,
        np.ones((3, 3), dtype=np.uint8),
    ) > 0
    bow_overlap_pixels = int(np.count_nonzero(closed_violin & bow))
    moving_overlap_pixels = int(np.count_nonzero(closed_violin & moving))
    backplate_mask = (
        closed_violin &
        (source_alpha > 12) &
        ~bow &
        ~moving
    )
    backplate_pixels = int(np.count_nonzero(backplate_mask))
    if backplate_pixels < 1000:
        raise ManualReviewRequired(
            f"The source-aligned violin backplate is too small ({backplate_pixels} pixels)."
        )

    full_canvas = source_pixels.copy()
    full_canvas[:, :, 3] = 0
    old_view = full_canvas[
        old_y:old_y + old_height,
        old_x:old_x + old_width,
    ]
    if old_view.shape[:2] != (old_height, old_width):
        raise ManualReviewRequired("The original torso crop lies outside the source canvas.")
    old_view[:, :, :] = np.asarray(original_torso, dtype=np.uint8)

    previous_alpha = full_canvas[:, :, 3].copy()
    added_mask = backplate_mask & (previous_alpha <= 12)
    full_canvas[backplate_mask, :3] = source_pixels[backplate_mask, :3]
    full_canvas[backplate_mask, 3] = source_alpha[backplate_mask]
    full_mask = full_canvas[:, :, 3] > 12
    if not full_mask.any():
        raise ManualReviewRequired("The extended torso backplate is empty.")

    x0, y0, x1, y1 = _bbox(full_mask)
    destination = bundle_dir / "torso-with-violin-backplate.png"
    Image.fromarray(full_canvas[y0:y1, x0:x1], mode="RGBA").save(
        destination, format="PNG", optimize=True
    )

    new_width, new_height = x1 - x0, y1 - y0
    new_pivot_x = (pivot_source_x - x0) / max(1.0, new_width)
    new_pivot_y = (pivot_source_y - y0) / max(1.0, new_height)
    torso_layer.update({
        "src": destination.name,
        "x": x0,
        "y": y0,
        "width": new_width,
        "height": new_height,
        "pivot_x": round(new_pivot_x, 6),
        "pivot_y": round(new_pivot_y, 6),
        "pixel_area": int(full_mask.sum()),
    })

    return {
        "method": "source_aligned_full_violin_underlay_in_extended_torso_plate",
        "asset": destination.name,
        "violin_backplate_pixels": backplate_pixels,
        "pixels_added": int(added_mask.sum()),
        "bow_pixels_excluded": bow_overlap_pixels,
        "moving_part_pixels_excluded": moving_overlap_pixels,
        "alpha_pinholes_closed": int(np.count_nonzero(closed_violin & ~violin)),
        "original_bbox": [old_x, old_y, old_x + old_width, old_y + old_height],
        "extended_bbox": [x0, y0, x1, y1],
        "torso_pivot_preserved": bool(
            abs((x0 + new_width * new_pivot_x) - pivot_source_x) < 0.01 and
            abs((y0 + new_height * new_pivot_y) - pivot_source_y) < 0.01
        ),
        "backplate_policy": "torso_parented_source_violin_underlay_beneath_attached_violin_prop",
    }


def _remove_embedded_props_from_static_layers(
    bundle_dir: Path,
    character: dict[str, Any],
    prop_masks: dict[str, np.ndarray],
) -> dict[str, Any]:
    """Remove mobile bow pixels while retaining the torso-mounted violin backplate.

    The violin prop is attached to the torso and has no independent movement.
    Keep its exact source pixels in the static torso plate underneath the
    separate violin sprite. This source-aligned underlay fills tiny alpha gaps
    in the extracted prop without leaving Telea-smudged wood/strings visible.

    The bow is attached to the moving left hand, so its original baked pixels
    must still be removed from static plates to prevent a second stationary bow.
    Moving limb/hand layers are handled independently.
    """
    try:
        import cv2
    except ImportError as exc:
        raise AutoRigError("OpenCV is required to remove embedded instrument pixels from static layers.") from exc

    roles_to_clean = {"torso", "head", "face"}
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    report: dict[str, Any] = {
        "method": "mobile_bow_removed_static_violin_retained_as_torso_underlay",
        "layers": {},
        "total_pixels_removed": 0,
        "automatic_layer_replacement": False,
        "source_alpha_geometry_preserved": True,
        "violin_backplate_policy": "source_aligned_torso_underlay_behind_attached_violin_prop",
    }

    for layer in character.get("layers", []):
        role = str(layer.get("role") or "")
        if role not in roles_to_clean:
            continue
        asset_path = bundle_dir / str(layer.get("src") or "")
        if not asset_path.is_file():
            raise AutoRigError(f"Missing static body plate for prop cleanup: {asset_path.name}")
        with Image.open(asset_path) as opened:
            plate = opened.convert("RGBA")
        pixels = np.asarray(plate, dtype=np.uint8).copy()
        alpha = pixels[:, :, 3]
        x, y = int(round(float(layer["x"]))), int(round(float(layer["y"])))
        height, width = alpha.shape

        role_report: dict[str, int] = {}
        remove_union = np.zeros((height, width), dtype=bool)
        for prop_name, canvas_mask in prop_masks.items():
            mask = np.asarray(canvas_mask, dtype=bool)
            if mask.ndim != 2:
                raise AutoRigError(f"The {prop_name} prop mask must be a two-dimensional canvas.")
            local = mask[y:y + height, x:x + width]
            if local.shape != (height, width):
                raise AutoRigError(
                    f"The {prop_name} prop mask does not fit static layer {role}."
                )
            expanded = cv2.dilate(local.astype(np.uint8), kernel, iterations=1) > 0
            count = int(np.count_nonzero((alpha > 12) & expanded))
            if role == "torso" and prop_name == "violin":
                # This prop is torso-mounted and does not move independently.
                # Keep the original source pixels underneath it as a crisp
                # backplate, so alpha gaps reveal the real illustration rather
                # than reconstructed/inpainted colour smears.
                role_report["violin_pixels_removed"] = 0
                role_report["violin_backplate_pixels_preserved"] = count
                continue
            role_report[f"{prop_name}_pixels_removed"] = count
            remove_union |= expanded

        removed = int(np.count_nonzero((alpha > 12) & remove_union))
        if removed:
            alpha[remove_union] = 0
            pixels[:, :, 3] = alpha
            Image.fromarray(pixels, mode="RGBA").save(asset_path, format="PNG", optimize=True)
        role_report["total_pixels_removed"] = removed
        role_report["asset"] = asset_path.name
        report["layers"][role] = role_report
        report["total_pixels_removed"] += removed

    report["layers_cleaned"] = sorted(report["layers"])
    report["separate_instrument_props_preserved"] = True
    return report


def _canvas_alpha_mask_for_layers(
    bundle_dir: Path,
    layers: list[dict[str, Any]],
    *,
    canvas_width: int,
    canvas_height: int,
    roles: tuple[str, ...],
) -> np.ndarray:
    """Combine selected cropped layer alpha planes into a source-canvas mask."""
    result = np.zeros((canvas_height, canvas_width), dtype=np.uint8)
    selected = [layer for layer in layers if str(layer.get("role") or "") in set(roles)]
    if not selected:
        raise ManualReviewRequired(
            "A segmented full-body plate requires source-aligned head and face layers."
        )
    for layer in selected:
        asset_path = bundle_dir / str(layer.get("src") or "")
        if not asset_path.is_file():
            raise AutoRigError(f"Missing source-aligned {layer.get('role')} plate: {asset_path.name}")
        with Image.open(asset_path) as opened:
            alpha = np.asarray(opened.convert("RGBA").getchannel("A"), dtype=np.uint8)
        x, y = int(round(float(layer["x"]))), int(round(float(layer["y"])))
        height, width = alpha.shape
        x0, y0 = max(0, x), max(0, y)
        x1, y1 = min(canvas_width, x + width), min(canvas_height, y + height)
        if x1 <= x0 or y1 <= y0:
            continue
        local = alpha[y0 - y:y1 - y, x0 - x:x1 - x]
        result[y0:y1, x0:x1] = np.maximum(result[y0:y1, x0:x1], local)
    if int((result > 12).sum()) < 500:
        raise ManualReviewRequired("The source-aligned head/face cutout is too small to replace safely.")
    return result


def _build_segmented_source_base(
    source: Image.Image,
    bundle_dir: Path,
    *,
    bow_canvas_alpha: np.ndarray,
    violin_canvas_alpha: np.ndarray,
    moving_mask: np.ndarray,
    head_canvas_alpha: np.ndarray | None = None,
) -> dict[str, Any]:
    """Inpaint limb cutouts into a source-aligned parent plate behind moving layers."""
    try:
        import cv2
    except ImportError as exc:
        raise AutoRigError("OpenCV is required to create the segmented source parent plate.") from exc

    rgba = np.asarray(source.convert("RGBA"), dtype=np.uint8).copy()
    height, width = rgba.shape[:2]
    bow = np.asarray(bow_canvas_alpha, dtype=np.uint8) > 12
    violin = np.asarray(violin_canvas_alpha, dtype=np.uint8) > 12
    moving = np.asarray(moving_mask, dtype=bool)
    head = (
        np.asarray(head_canvas_alpha, dtype=np.uint8) > 12
        if head_canvas_alpha is not None
        else np.zeros((height, width), dtype=bool)
    )
    if any(mask.shape != (height, width) for mask in (bow, violin, moving, head)):
        raise AutoRigError("Bow, violin, head and moving-region masks must match the source canvas.")
    # Keep the original source head/face artwork as a static backplate behind
    # the source-aligned head and face plates. Their artwork comes from this
    # same image, so retaining it fills any small plate-alpha gaps with real
    # illustration pixels instead of a broad inpainted face/neck smear.
    # The moving limbs and props still need their own parent underpaint.
    # The violin is fixed to the torso and has an exact source-pixel underlay
    # in the extended torso plate. Do not erase or inpaint it in this parent
    # plate: the original pixels remain a clean fallback beneath the prop and
    # close any mask pinholes without smudged reconstruction.
    source_aligned_cut = moving | bow | head
    cut = (moving | bow) & (rgba[:, :, 3] > 12)
    legacy_expanded = _morph(source_aligned_cut, 2, "dilate") & (rgba[:, :, 3] > 12)
    exact_source_union = source_aligned_cut & (rgba[:, :, 3] > 12)
    expanded_halo_pixels_excluded = int(np.count_nonzero(legacy_expanded & ~exact_source_union))
    head_backplate_pixels_preserved = int(np.count_nonzero(head & (rgba[:, :, 3] > 12)))
    violin_source_pixels_preserved = int(np.count_nonzero(violin & (rgba[:, :, 3] > 12)))
    if int(exact_source_union.sum()) < 1000:
        raise ManualReviewRequired("The complete source-aligned limb/prop/head coverage is unexpectedly small.")
    # Fully transparent pixels may still retain white/striped RGB from the
    # original matte. Never allow those pixels to seed inpainting at a cutout
    # near the silhouette edge: classify them as unknown during reconstruction.
    # Keep the original alpha plane untouched and copy reconstructed RGB only
    # into the visible cut region.
    visible_source = rgba[:, :, 3] > 12
    reconstruction_mask = cut | ~visible_source
    repaired = cv2.inpaint(
        rgba[:, :, :3],
        reconstruction_mask.astype(np.uint8) * 255,
        5,
        cv2.INPAINT_TELEA,
    )
    rgba[cut, :3] = repaired[cut]
    destination = bundle_dir / "performance-segmented-base.png"
    Image.fromarray(rgba, mode="RGBA").save(destination, format="PNG", optimize=True)
    return {
        "src": destination.name,
        "x": 0,
        "y": 0,
        "width": width,
        "height": height,
        "z_index": 1,
        "mode": "segmented_source_body",
        "pixels_cut_from_source": int(cut.sum()),
        "moving_region_pixels": int(moving.sum()),
        "cutout_mask_dilation_px": 0,
        "expanded_halo_pixels_excluded": expanded_halo_pixels_excluded,
        "cutout_boundary_method": "exact_source_aligned_alpha_union",
        "bow_pixels_reconstructed": int((bow & cut).sum()),
        "violin_pixels_reconstructed": 0,
        "violin_source_underlay_preserved": True,
        "violin_source_pixels_preserved": violin_source_pixels_preserved,
        "head_pixels_reconstructed": 0,
        "head_backplate_pixels_preserved": head_backplate_pixels_preserved,
        "head_source_backplate_preserved": bool(head_backplate_pixels_preserved > 0),
        "head_plate_replacement_enabled": bool(head.any()),
        "head_cutout_method": "source_aligned_head_backplate_preserved",
        "source_alpha_preserved": True,
        "source_pixels_outside_cut_mask_preserved": True,
        "inpaint": "opencv_telea_radius_5_alpha_aware",
        "underpaint_quality": "source_aligned_static_violin_preserved_no_violin_inpaint",
        "transparent_source_pixels_excluded_from_inpaint": int((~visible_source).sum()),
        "transparent_rgb_excluded_from_reconstruction": True,
    }


def _restore_torso_hidden_overlap_from_reference(
    bundle_dir: Path,
    character: dict[str, Any],
    *,
    reference_transform: tuple[int, int, int, int] = (76, 148, 210, 262),
) -> dict[str, Any]:
    """Replace locally inpainted hidden jacket pixels with aligned source artwork.

    The patch is restricted to the union of the exact parser hidden-overlap
    mask and the authored full-body moving-limb mask, and to opaque pixels from
    the supplied jacket reference. The violin and bow footprints are excluded.
    Only torso RGB is changed: alpha, crop geometry, limb/hand sprites and
    their animation data stay intact.
    """
    canvas_spec = character.get("canvas", {})
    canvas_width = int(canvas_spec.get("width", 0))
    canvas_height = int(canvas_spec.get("height", 0))
    if canvas_width <= 0 or canvas_height <= 0:
        raise AutoRigError("Torso source-art restoration requires a valid character canvas.")

    hidden_path = bundle_dir / "torso-hidden-overlap-mask.png"
    moving_path = bundle_dir / "full-body-moving-mask.png"
    reference_path = bundle_dir / "reference-part-003.png"
    if not hidden_path.is_file() or not moving_path.is_file():
        raise ManualReviewRequired(
            "The exact parser and full-body moving masks are required for safe torso source-art restoration."
        )
    if not reference_path.is_file():
        raise ManualReviewRequired(
            "The supplied jacket torso reference is missing; source-art restoration cannot proceed safely."
        )

    with Image.open(hidden_path) as opened:
        hidden_image = opened.convert("L")
    with Image.open(moving_path) as opened:
        moving_image = opened.convert("L")
    if hidden_image.size != (canvas_width, canvas_height):
        raise AutoRigError("The torso hidden-overlap mask does not match the character canvas.")
    if moving_image.size != (canvas_width, canvas_height):
        raise AutoRigError("The full-body moving mask does not match the character canvas.")
    hidden = np.asarray(hidden_image, dtype=np.uint8) > 0
    moving = np.asarray(moving_image, dtype=np.uint8) > 0
    hidden_count = int(hidden.sum())
    moving_count = int(moving.sum())
    restoration_source_mask = hidden | moving
    if hidden_count < 100 or moving_count < 1000:
        raise ManualReviewRequired(
            "The parser hidden-overlap or authored moving-region mask is too small for reliable torso restoration."
        )

    torso_layer = next(
        (layer for layer in character.get("layers", []) if layer.get("role") == "torso"),
        None,
    )
    if torso_layer is None:
        raise ManualReviewRequired("A torso layer is required for hidden jacket restoration.")

    torso_path = bundle_dir / str(torso_layer["src"])
    if not torso_path.is_file():
        raise ManualReviewRequired("The active torso backplate asset is missing.")
    torso_x = int(round(float(torso_layer["x"])))
    torso_y = int(round(float(torso_layer["y"])))
    with Image.open(torso_path) as opened:
        torso_image = opened.convert("RGBA")
    expected_size = (
        int(round(float(torso_layer["width"]))),
        int(round(float(torso_layer["height"]))),
    )
    if torso_image.size != expected_size:
        raise AutoRigError("Torso backplate dimensions disagree with the character layer geometry.")
    torso_pixels = np.asarray(torso_image, dtype=np.uint8).copy()
    original_alpha = torso_pixels[:, :, 3].copy()
    original_pixels = torso_pixels.copy()

    ref_x, ref_y, ref_width, ref_height = (
        int(value) for value in reference_transform
    )
    if min(ref_width, ref_height) <= 0 or ref_x < 0 or ref_y < 0:
        raise ValueError("The jacket reference transform must be a positive in-canvas rectangle.")
    if ref_x + ref_width > canvas_width or ref_y + ref_height > canvas_height:
        raise ManualReviewRequired("The jacket reference transform extends beyond the character canvas.")

    with Image.open(reference_path) as opened:
        reference = opened.convert("RGBA")
    reference = reference.resize(
        (ref_width, ref_height), Image.Resampling.LANCZOS
    )
    reference_canvas = np.zeros((canvas_height, canvas_width, 4), dtype=np.uint8)
    reference_canvas[ref_y:ref_y + ref_height, ref_x:ref_x + ref_width] = np.asarray(
        reference, dtype=np.uint8
    )

    # Keep the instrument's source pixels authoritative; do not replace any
    # violin or bow pixel with the jacket reference, even where masks overlap.
    prop_mask = np.zeros((canvas_height, canvas_width), dtype=bool)
    for prop in character.get("props", {}).values():
        prop_src = prop.get("src")
        if not prop_src:
            continue
        prop_path = bundle_dir / str(prop_src)
        if not prop_path.is_file():
            raise ManualReviewRequired(f"A prop needed for the torso exclusion mask is missing: {prop_src}")
        px, py = int(round(float(prop.get("x", 0)))), int(round(float(prop.get("y", 0))))
        pw, ph = int(round(float(prop.get("width", 0)))), int(round(float(prop.get("height", 0))))
        if pw <= 0 or ph <= 0 or px < 0 or py < 0 or px + pw > canvas_width or py + ph > canvas_height:
            raise ManualReviewRequired(f"Prop {prop_src} has invalid source-canvas geometry.")
        with Image.open(prop_path) as opened:
            sprite = opened.convert("RGBA").resize(
                (pw, ph), Image.Resampling.LANCZOS
            )
        alpha = np.asarray(sprite.getchannel("A"), dtype=np.uint8)
        prop_mask[py:py + ph, px:px + pw] |= alpha > 12

    x0, y0 = torso_x, torso_y
    x1, y1 = x0 + torso_pixels.shape[1], y0 + torso_pixels.shape[0]
    if x0 < 0 or y0 < 0 or x1 > canvas_width or y1 > canvas_height:
        raise AutoRigError("The torso backplate crop lies outside the character canvas.")

    local_hidden = hidden[y0:y1, x0:x1]
    local_moving = moving[y0:y1, x0:x1]
    local_source_mask = restoration_source_mask[y0:y1, x0:x1]
    local_reference_alpha = reference_canvas[y0:y1, x0:x1, 3]
    local_reference_rgb = reference_canvas[y0:y1, x0:x1, :3]
    local_prop_mask = prop_mask[y0:y1, x0:x1]
    local_visible_torso = original_alpha > 12

    restoration_mask = (
        local_source_mask
        & (local_reference_alpha >= 240)
        & local_visible_torso
        & ~local_prop_mask
    )
    restored_pixels = int(restoration_mask.sum())
    if restored_pixels < 100:
        raise ManualReviewRequired(
            f"Only {restored_pixels} hidden or moving torso pixels align with the jacket reference; refusing a weak patch."
        )

    torso_pixels[restoration_mask, :3] = local_reference_rgb[restoration_mask]
    if not np.array_equal(torso_pixels[:, :, 3], original_alpha):
        raise AutoRigError("Torso source-art restoration unexpectedly changed the layer alpha.")
    if not np.array_equal(
        torso_pixels[~restoration_mask], original_pixels[~restoration_mask]
    ):
        raise AutoRigError("Torso source-art restoration modified pixels outside its approved mask.")

    Image.fromarray(torso_pixels, mode="RGBA").save(
        torso_path, format="PNG", optimize=True
    )
    full_restoration_mask = np.zeros((canvas_height, canvas_width), dtype=np.uint8)
    full_restoration_mask[y0:y1, x0:x1] = restoration_mask.astype(np.uint8) * 255
    Image.fromarray(full_restoration_mask, mode="L").save(
        bundle_dir / "torso-reference-restoration-mask.png",
        format="PNG",
        optimize=True,
    )

    return {
        "method": "aligned_supplied_jacket_reference_on_authored_moving_and_hidden_torso_masks",
        "reference_asset": reference_path.name,
        "reference_transform": {
            "x": ref_x, "y": ref_y,
            "width": ref_width, "height": ref_height,
            "resampling": "lanczos",
        },
        "restoration_mask_asset": "torso-reference-restoration-mask.png",
        "hidden_overlap_pixels": hidden_count,
        "authored_moving_region_pixels": moving_count,
        "reference_covered_moving_and_hidden_pixels": int(
            np.count_nonzero(restoration_source_mask & (reference_canvas[:, :, 3] >= 240))
        ),
        "prop_pixels_excluded": int(np.count_nonzero(restoration_source_mask & prop_mask)),
        "pixels_restored": restored_pixels,
        "layer_alpha_preserved": True,
        "torso_crop_geometry_preserved": True,
        "hand_forearm_assets_modified": 0,
        "hand_animation_data_modified": False,
        "source_pixels_outside_restoration_mask_preserved": True,
        "visual_review_required": True,
    }


def _build_bow_grip_hand_overlay(
    source: Image.Image,
    bundle_dir: Path,
    character: dict[str, Any],
) -> dict[str, Any]:
    """Extract the bow hand's warm-skin silhouette without carrying the old bow."""
    try:
        import cv2
    except ImportError as exc:
        raise AutoRigError("OpenCV is required to prepare the bow-grip hand overlay.") from exc

    original_layer = next(
        (layer for layer in character.get("layers", []) if layer.get("role") == "left_hand"),
        None,
    )
    if original_layer is None:
        raise ManualReviewRequired("The complete-body preview requires a source left-hand region.")

    width, height = source.size
    x0 = max(0, int(original_layer["x"]) - 12)
    y0 = max(0, int(original_layer["y"]) - 12)
    x1 = min(width, int(original_layer["x"]) + int(original_layer["width"]) + 12)
    y1 = min(height, int(original_layer["y"]) + int(original_layer["height"]) + 12)
    rgba = np.asarray(source.convert("RGBA"), dtype=np.uint8)
    red = rgba[:, :, 0].astype(np.int16)
    green = rgba[:, :, 1].astype(np.int16)
    blue = rgba[:, :, 2].astype(np.int16)

    # Reuse the source hand silhouette as a spatial guard, then remove any
    # bow pixels from that region using a warm-skin colour test.
    hand_path = bundle_dir / str(original_layer["src"])
    with Image.open(hand_path) as opened_hand:
        local_hand_alpha = np.asarray(opened_hand.convert("RGBA").getchannel("A"), dtype=np.uint8)
    hx, hy = int(original_layer["x"]), int(original_layer["y"])
    hand_seed = np.zeros((height, width), dtype=np.uint8)
    hand_seed[hy:hy + local_hand_alpha.shape[0], hx:hx + local_hand_alpha.shape[1]] = (
        local_hand_alpha > 12
    ).astype(np.uint8)
    allowed = cv2.dilate(
        hand_seed,
        cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (5, 5)),
        iterations=1,
    ) > 0
    allowed[:y0, :] = False
    allowed[y1:, :] = False
    allowed[:, :x0] = False
    allowed[:, x1:] = False

    # The bow shaft and pale bow hair are intentionally excluded, even where
    # they cross the fingers. A one-pixel dilation retains the hand outline.
    skin = (
        (red >= 135) & (green >= 65) &
        ((red - green) >= 15) & ((green - blue) >= 10) &
        ((red - blue) >= 40) & allowed &
        (rgba[:, :, 3] > 16)
    )
    skin = cv2.morphologyEx(
        skin.astype(np.uint8),
        cv2.MORPH_CLOSE,
        np.ones((3, 3), dtype=np.uint8),
    ) > 0
    hand_mask = cv2.dilate(
        skin.astype(np.uint8),
        np.ones((3, 3), dtype=np.uint8),
        iterations=1,
    ) > 0
    hand_mask &= allowed & (rgba[:, :, 3] > 16)
    hand_area = int(hand_mask.sum())
    if hand_area < 180:
        raise ManualReviewRequired(
            f"Bow-grip skin extraction is too small ({hand_area} pixels); inspect the hand reference."
        )

    geometry = _save_rgba_layer(
        source,
        hand_mask,
        bundle_dir / "bow-grip-hand.png",
        padding=3,
    )
    joints = character.get("joints") or {}
    wrist = joints.get("left_wrist") or {"x": 0.5, "y": 0.5}
    pivot_x = (
        float(wrist["x"]) * width - float(geometry["x"])
    ) / max(1.0, float(geometry["width"]))
    pivot_y = (
        float(wrist["y"]) * height - float(geometry["y"])
    ) / max(1.0, float(geometry["height"]))
    hand_layer = {
        "id": "left_hand",
        "role": "left_hand",
        **geometry,
        "pivot_x": round(min(1.0, max(0.0, pivot_x)), 6),
        "pivot_y": round(min(1.0, max(0.0, pivot_y)), 6),
        "z_index": FINGER_Z.get("left_hand", 40),
    }
    character["layers"] = [
        layer for layer in character.get("layers", [])
        if layer.get("role") != "left_hand"
    ] + [hand_layer]
    return {
        "src": geometry["src"],
        "bbox": [
            int(geometry["x"]),
            int(geometry["y"]),
            int(geometry["x"]) + int(geometry["width"]),
            int(geometry["y"]) + int(geometry["height"]),
        ],
        "skin_pixels": hand_area,
        "method": "warm_skin_mask_with_one_pixel_outline_dilation",
        "excludes_original_bow_pixels": True,
    }


def _build_preserved_composite_base(
    source: Image.Image,
    bundle_dir: Path,
    *,
    bow_canvas_alpha: np.ndarray,
    finger_manifest_path: Path | None,
    character: dict[str, Any],
) -> dict[str, Any]:
    """Build an intact full-body plate with a separate bow and fingering sprites.

    The source illustration remains the authority for the sleeves, both hands,
    trousers and shoes. The bow is erased from the source, then the exact
    source-derived bow-grip hand is layered above the animated bow. This avoids
    low-confidence semantic masks from creating holes in the presenter.
    """
    try:
        import cv2
    except ImportError as exc:
        raise AutoRigError(
            "OpenCV is required to prepare the complete-body review plate."
        ) from exc

    hand_report = _build_bow_grip_hand_overlay(source, bundle_dir, character)
    rgba = np.asarray(source.convert("RGBA"), dtype=np.uint8).copy()
    height, width = rgba.shape[:2]
    bow_mask = np.asarray(bow_canvas_alpha, dtype=np.uint8)
    if bow_mask.shape != (height, width):
        raise AutoRigError("The bow mask must match the complete-body source canvas.")
    bow_pixels = bow_mask > 12
    if int(bow_pixels.sum()) < 40:
        raise ManualReviewRequired("The bow mask is too small to prepare a complete-body plate.")

    # Remove the shaft and its pale bow-hair edge from the source. The
    # skin-only hand overlay is then composited above the animated bow.
    bow_clear = _morph(bow_pixels, 3, "dilate")
    rgb = rgba[:, :, :3]
    # Transparent source pixels can retain the original striped/white matte
    # RGB. Exclude them as inpainting samples so a cleared bow cannot turn into
    # a pale reconstruction streak along the presenter.
    visible_source = rgba[:, :, 3] > 12
    reconstruction_mask = bow_clear | ~visible_source
    repaired_rgb = cv2.inpaint(
        rgb,
        reconstruction_mask.astype(np.uint8) * 255,
        3,
        cv2.INPAINT_TELEA,
    )
    rgba[:, :, :3] = repaired_rgb

    finger_cut = np.zeros((height, width), dtype=bool)
    if finger_manifest_path and finger_manifest_path.is_file():
        manifest = json.loads(finger_manifest_path.read_text(encoding="utf-8"))
        canvas = manifest.get("canvas") or {}
        if int(canvas.get("width", 0)) != width or int(canvas.get("height", 0)) != height:
            raise ManualReviewRequired("Finger manifest canvas does not match the complete-body source.")
        region = Image.new("L", (width, height), 0)
        draw = ImageDraw.Draw(region)
        for name, specification in (manifest.get("fingers") or {}).items():
            polygon = specification.get("polygon") or []
            if len(polygon) < 3:
                raise ManualReviewRequired(f"Finger {name} has no usable cutout polygon.")
            draw.polygon([tuple(point) for point in polygon], fill=255)
        finger_cut = np.asarray(region, dtype=np.uint8) > 0
        finger_cut &= rgba[:, :, 3] > 0
        rgba[finger_cut, 3] = 0

    destination = bundle_dir / "performance-composite-base.png"
    Image.fromarray(rgba, mode="RGBA").save(destination, format="PNG", optimize=True)
    return {
        "src": destination.name,
        "x": 0,
        "y": 0,
        "width": width,
        "height": height,
        "z_index": 10,
        "mode": "intact_full_body_with_bow_and_finger_cutouts",
        "bow_pixels_reconstructed": int(bow_clear.sum()),
        "finger_pixels_separated": int(finger_cut.sum()),
        "bow_grip_hand": hand_report,
        "preserves_original_arms_hands_legs_and_head": True,
    }


def extend_full_body_character(
    source_path: str | Path,
    bundle_dir: str | Path,
    *,
    prop_dir: str | Path,
    instrument_manifest_path: str | Path,
    performance_regions_path: str | Path,
    finger_manifest_path: str | Path | None = None,
    neutral_apose_path: str | Path | None = None,
) -> dict[str, Any]:
    source_path = Path(source_path).resolve(strict=True)
    bundle = Path(bundle_dir).resolve(strict=True)
    prop_root = Path(prop_dir).resolve(strict=True)
    manifest_path = Path(instrument_manifest_path).resolve(strict=True)
    regions_path = Path(performance_regions_path).resolve(strict=True)
    finger_path = Path(finger_manifest_path).resolve() if finger_manifest_path else None
    character_path = bundle / "character.json"
    if not character_path.is_file():
        raise AutoRigError("The base Auto-Rig bundle must contain character.json.")

    preserved_source_path = bundle / "preserved-full-body-source.png"
    source_input = preserved_source_path if preserved_source_path.is_file() else source_path
    with Image.open(source_input) as opened:
        source = opened.convert("RGBA")
    character = json.loads(character_path.read_text(encoding="utf-8"))

    prop_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    prop_canvas = prop_manifest.get("canvas") or {}
    if int(prop_canvas.get("width", 0)) != source.width or int(prop_canvas.get("height", 0)) != source.height:
        raise ManualReviewRequired("Instrument-prop manifest canvas does not match the playing reference.")
    prop_report = {}
    props = {}
    prop_masks: dict[str, np.ndarray] = {}
    for prop_id, specification in (prop_manifest.get("props") or {}).items():
        src_path = prop_root / str(specification["src"])
        if not src_path.is_file():
            raise AutoRigError(f"Missing instrument prop asset: {src_path.name}")
        target_name = f"prop-{prop_id}{src_path.suffix.lower()}"
        target = bundle / target_name
        shutil.copy2(src_path, target)
        props[prop_id] = {
            **{key: value for key, value in specification.items() if key != "hand_backplate_polygon"},
            "id": prop_id,
            "src": target_name,
            "attach_to": str(specification.get("attach_to") or ("left_hand" if prop_id == "bow" else "torso")),
        }
        with Image.open(src_path) as opened:
            prop_alpha = np.asarray(opened.convert("RGBA").getchannel("A"), dtype=np.uint8)
        canvas_alpha = np.zeros((source.height, source.width), dtype=np.uint8)
        x, y = int(specification["x"]), int(specification["y"])
        h, w = prop_alpha.shape
        if x < 0 or y < 0 or x + w > source.width or y + h > source.height:
            raise ManualReviewRequired(f"Prop {prop_id} lies outside the master character canvas.")
        canvas_alpha[y:y + h, x:x + w] = prop_alpha
        prop_masks[prop_id] = canvas_alpha
        prop_report[prop_id] = {
            "src": target_name,
            "bbox": [x, y, x + w, y + h],
            "attach_to": props[prop_id]["attach_to"],
        }

    # Recolour inherited neutral backdrop spill through a narrow distance band.
    # Instrument pixels are protected; alpha and silhouette geometry stay intact.
    source, edge_decontamination = _decontaminate_edge_matte_rgb(
        source,
        protected_masks=tuple(prop_masks.values()),
    )

    # The extracted bow sprite contains its dark wooden stick but not the
    # original source's pale hair strand. Recover that strand and composite it
    # into the same sprite before clearing the source-baked prop from static art.
    bow_hair_restoration, prop_masks["bow"] = _restore_bow_hair_in_prop_asset(
        source,
        bundle,
        props["bow"],
        prop_masks["bow"],
    )
    props["bow"]["src"] = bow_hair_restoration["src"]
    prop_report["bow"]["src"] = bow_hair_restoration["src"]

    # Keep the decontaminated source image available for QA and layer rebuilds.
    clean_source_path = bundle / "preserved-full-body-source.png"
    source.save(clean_source_path, format="PNG", optimize=True)

    # Replace the unreliable SCHP limb masks with reviewed source-pixel regions.
    limb_layers, limb_joints, limb_report, moving_mask = _authored_performance_layers(
        source,
        bundle,
        regions_manifest_path=regions_path,
        prop_masks=prop_masks,
    )
    limb_roles = {
        "left_upper_arm", "left_forearm", "left_hand",
        "right_upper_arm", "right_forearm", "right_hand",
        "left_thigh", "left_calf", "left_foot",
        "right_thigh", "right_calf", "right_foot",
        "finger_index", "finger_middle", "finger_ring", "finger_little",
    }
    character["layers"] = [
        layer for layer in character.get("layers", [])
        if str(layer.get("role") or "") not in limb_roles
    ]
    character["layers"].extend(limb_layers)
    character.setdefault("joints", {}).update(limb_joints)
    right_hand_layer = next(layer for layer in limb_layers if layer["role"] == "right_hand")
    violin_hand_cleanup = _reconstruct_violin_fingerboard_backplate(
        source,
        bundle,
        violin_specification=(prop_manifest.get("props") or {})["violin"],
        hand_layer=right_hand_layer,
        violin_canvas_alpha=prop_masks["violin"],
        dilation_radius=1,
        inpaint_radius=6,
    )
    limb_report["violin_hand_overlap_cleanup"] = violin_hand_cleanup

    # Finger polygons are extracted from the source-aligned right-hand layer.
    finger_layers, finger_joints, finger_areas, finger_quality = _prepare_fingers(
        source, bundle, character, finger_path
    ) if finger_path else ([], {}, {}, {})
    character["layers"].extend(finger_layers)
    character["joints"].update(finger_joints)
    if finger_layers:
        finger_manifest = json.loads(finger_path.read_text(encoding="utf-8"))
        finger_union = np.zeros((source.height, source.width), dtype=bool)
        for specification in (finger_manifest.get("fingers") or {}).values():
            finger_union |= _polygon_mask(
                (source.height, source.width),
                specification.get("polygon") or [],
            )
        moving_mask |= finger_union & (np.asarray(source.getchannel("A")) > 12)

    moving_mask_path = bundle / "full-body-moving-mask.png"
    Image.fromarray(moving_mask.astype(np.uint8) * 255, mode="L").save(
        moving_mask_path, format="PNG", optimize=True
    )

    # Restore a source-faithful underlay across the full torso-mounted violin
    # footprint after all moving hand/finger masks are known. The violin sprite
    # and this underlay share the torso parent/pivot, so alpha pinholes reveal
    # original illustration pixels instead of smudged inpaint.
    torso_backplate_extension = _extend_torso_layer_with_violin_backplate(
        source,
        bundle,
        character,
        prop_masks,
        moving_mask=moving_mask,
    )
    static_layer_prop_cleanup = _remove_embedded_props_from_static_layers(
        bundle,
        character,
        prop_masks,
    )
    static_layer_prop_cleanup["torso_backplate_extension"] = torso_backplate_extension

    head_canvas_alpha = _canvas_alpha_mask_for_layers(
        bundle,
        character.get("layers", []),
        canvas_width=source.width,
        canvas_height=source.height,
        roles=("head", "face"),
    )
    composite_base = _build_segmented_source_base(
        source,
        bundle,
        bow_canvas_alpha=prop_masks["bow"],
        violin_canvas_alpha=prop_masks["violin"],
        moving_mask=moving_mask,
        head_canvas_alpha=head_canvas_alpha,
    )
    character["base_art"] = composite_base
    character["performance_base_mode"] = "segmented_source_body"
    character["props"] = props
    character["performance"] = {
        "schema": "violin-prince-fullbody-performance-v2",
        "instrument_performance": True,
        "fingering_parts": sorted(finger_areas),
        "fingering_segment_roles": sorted(layer["role"] for layer in finger_layers),
        "fingering_joint_count": len(finger_joints),
        "bow_prop_id": "bow",
        "violin_prop_id": "violin",
        "independent_limb_layer_count": len(limb_layers),
        "review_required": True,
        "compositing_mode": "segmented_source_body_with_underpaint",
    }

    # Preserve the provided neutral A-pose as a review source, not as a runtime overlay.
    neutral_report = {"provided": False}
    if neutral_apose_path:
        apose = Path(neutral_apose_path).resolve(strict=True)
        with Image.open(apose) as opened:
            neutral = opened.convert("RGBA")
        neutral_box = neutral.getchannel("A").getbbox()
        if neutral_box is None:
            raise ManualReviewRequired("The neutral A-pose reference is fully transparent.")
        neutral_target = bundle / "neutral-apose-reference.webp"
        neutral.save(neutral_target, "WEBP", quality=92, method=6)
        neutral_report = {
            "provided": True,
            "asset": neutral_target.name,
            "canvas": [neutral.width, neutral.height],
            "visible_bbox": list(neutral_box),
        }

    validated = validate_character_spec(character)
    character_path.write_text(
        json.dumps(validated, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    report = {
        "status": "candidate_source_aligned_performance_rig_ready_for_review",
        "character_id": character["id"],
        "canvas": character["canvas"],
        "base_layer_count": 9,
        "independent_limb_layer_count": len(limb_layers),
        "finger_layer_count": len(finger_layers),
        "finger_segment_count": len(finger_layers),
        "finger_digit_count": len(finger_areas),
        "finger_joint_count": len(finger_joints),
        "joint_additions": sorted(limb_joints.keys() | finger_joints.keys()),
        "limb_report": limb_report,
        "source_edge_color_decontamination": edge_decontamination,
        "bow_hair_restoration": bow_hair_restoration,
        "static_layer_prop_cleanup": static_layer_prop_cleanup,
        "violin_hand_overlap_cleanup": violin_hand_cleanup,
        "finger_pixel_areas": finger_areas,
        "finger_segment_quality": finger_quality,
        "prop_report": prop_report,
        "body_plate_prop_pixels_removed": {"torso": 0, "arms": 0},
        "prop_compositing": "source_aligned_body_base_with_separate_limb_and_prop_layers",
        "composite_base": composite_base,
        "composite_source": source_input.name,
        "segmented_limb_masks_status": "source_aligned_polygon_regions_active_in_preview",
        "full_body_moving_mask": {
            "asset": moving_mask_path.name,
            "pixels": int(moving_mask.sum()),
            "source": "authored_performance_polygons_and_finger_manifest",
            "hand_animation_data_modified": False,
        },
        "neutral_apose_reference": neutral_report,
        "publishing": "disabled",
        "preview_only": True,
        "visual_review_required": True,
        # Do not describe this rig as premium-ready while the source art lacks
        # clean hidden backplates, joint-aligned multi-part hands and deformable
        # anatomy. A passing render is only a render/engineering check.
        "premium_character_quality_gate": {
            "status": "blocked_pending_character_art_reconstruction",
            "underpaint": "approximate_nonsemantic_inpaint",
            "head": "normalized_plate_crossfades_not_continuous_mesh_deformation",
            "hands": "four_source_aligned_three_segment_finger_chains_with_joint_overlap_not_deformable_art",
            "body": "rigid_segment_transforms_without_mesh_deformation",
            "release_blockers": [
                "manually reconstructed hidden neck shoulder clothing and instrument backplates",
                "anatomically aligned head neck and facial feature rig",
                "artist-reconstructed joint-surface skin and deformable bow-grip artwork",
                "continuous deformable body rig and full-frame visual QA",
            ],
        },
    }
    (bundle / "full-body-performance-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="The transparent full-body playing master.")
    parser.add_argument("--bundle", required=True, help="Existing upper-body character bundle.")
    parser.add_argument("--prop-dir", required=True, help="Folder containing the violin and bow assets.")
    parser.add_argument("--instrument-manifest", required=True)
    parser.add_argument("--performance-regions", required=True)
    parser.add_argument("--finger-manifest", default="")
    parser.add_argument("--neutral-apose", default="")
    parser.add_argument("--rigging-sheet", default="")
    parser.add_argument("--expression-sheet", default="")
    parser.add_argument("--head-angle-sheet", default="")
    args = parser.parse_args()
    result = extend_full_body_character(
        args.source, args.bundle,
        prop_dir=args.prop_dir,
        instrument_manifest_path=args.instrument_manifest,
        performance_regions_path=args.performance_regions,
        finger_manifest_path=args.finger_manifest or None,
        neutral_apose_path=args.neutral_apose or None,
    )
    reference_inputs = (args.rigging_sheet, args.expression_sheet, args.head_angle_sheet)
    if any(reference_inputs) and not all(reference_inputs):
        raise AutoRigError("Provide all three reference-sheet paths together.")
    if all(reference_inputs):
        from reference_sheet_rig import build_reference_sheet_rig
        bundle = Path(args.bundle).resolve(strict=True)
        reference_report = build_reference_sheet_rig(
            bundle / "character.json",
            bundle,
            rigging_sheet_path=args.rigging_sheet,
            expression_sheet_path=args.expression_sheet,
            head_angle_sheet_path=args.head_angle_sheet,
        )
        result["reference_sheet_rig"] = reference_report
        character_path = bundle / "character.json"
        restoration_character = json.loads(
            character_path.read_text(encoding="utf-8")
        )
        torso_restoration = _restore_torso_hidden_overlap_from_reference(
            bundle,
            restoration_character,
        )
        result["torso_reference_restoration"] = torso_restoration
        report_path = bundle / "full-body-performance-report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["reference_sheet_rig"] = reference_report
        report["torso_reference_restoration"] = torso_restoration
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print("FULL_BODY_PERFORMANCE_RIG=" + json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
