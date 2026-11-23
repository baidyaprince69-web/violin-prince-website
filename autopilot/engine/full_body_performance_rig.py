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
    "finger_index": 43,
    "finger_middle": 44,
    "finger_ring": 45,
    "finger_little": 46,
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
) -> tuple[list[dict[str, Any]], dict[str, dict[str, float]], dict[str, int]]:
    if not finger_manifest_path.is_file():
        return [], {}, {}
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

    for index, (name, specification) in enumerate((manifest.get("fingers") or {}).items()):
        role = "finger_" + str(name).strip().casefold()
        polygon = specification.get("polygon") or []
        pivot = specification.get("pivot") or []
        if len(polygon) < 3 or len(pivot) != 2:
            raise ManualReviewRequired(f"Finger {name} needs a polygon and a two-coordinate pivot.")
        region = Image.new("L", (width, height), 0)
        ImageDraw.Draw(region).polygon([tuple(point) for point in polygon], fill=255)
        region_mask = np.asarray(region, dtype=np.uint8) > 0
        # The finger outline must be a subset of the independently extracted
        # skin hand. This excludes violin/bow fragments and jacket/edge pixels
        # that may intersect an authored polygon on the original composite.
        finger_mask = region_mask & (hand_canvas_alpha > 12)
        if int(finger_mask.sum()) < 20:
            raise ManualReviewRequired(
                f"Finger region {name} does not overlap the source-aligned {hand_role} skin mask."
            )
        geometry = _save_rgba_layer(
            source, finger_mask, bundle_dir / f"{role}.png", padding=3
        )
        layers.append({
            "id": role, "role": role, **geometry,
            "pivot_x": 0.5, "pivot_y": 0.5,
            "z_index": FINGER_Z.get(role, 46),
        })
        px, py = float(pivot[0]), float(pivot[1])
        joints[f"right_{name}_base"] = _normalise_joint((px, py), width, height)
        areas[role] = int(finger_mask.sum())

        # Remove the same finger pixels from the stationary palm plate.
        lx0, ly0 = max(0, hx), max(0, hy)
        x0, y0 = max(lx0, int(geometry["x"])), max(ly0, int(geometry["y"]))
        x1 = min(hx + hand_image.width, int(geometry["x"]) + int(geometry["width"]))
        y1 = min(hy + hand_image.height, int(geometry["y"]) + int(geometry["height"]))
        if x1 > x0 and y1 > y0:
            cut = finger_mask[y0:y1, x0:x1]
            local = hand_alpha[y0 - hy:y1 - hy, x0 - hx:x1 - hx]
            local[cut] = 0

    hand_image.putalpha(Image.fromarray(hand_alpha, mode="L"))
    hand_image.save(hand_path, format="PNG", optimize=True)
    return layers, joints, areas


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


def _clip_hand_from_violin_prop(
    bundle_dir: Path,
    *,
    violin_specification: dict[str, Any],
    hand_layer: dict[str, Any],
    dilation_radius: int = 1,
) -> dict[str, int | str]:
    """Remove source-derived fretting-hand pixels from the violin sprite.

    The prop crop can contain the original hand because the supplied violin
    artwork was cut from a composite image. The independently extracted hand
    is rendered above the violin; clipping its exact alpha footprint (plus a
    one-pixel seam) prevents the prop from drawing a second, offset hand.
    """
    if dilation_radius < 0 or dilation_radius > 3:
        raise ValueError("Hand/violin overlap dilation must be between zero and three pixels.")
    try:
        import cv2
    except ImportError as exc:
        raise AutoRigError("OpenCV is required to clean the violin/hand overlap.") from exc

    hand_path = bundle_dir / str(hand_layer["src"])
    violin_path = bundle_dir / f"prop-violin{Path(str(violin_specification['src'])).suffix.lower()}"
    if not hand_path.is_file() or not violin_path.is_file():
        raise AutoRigError("The source-derived hand or violin prop asset is missing.")
    with Image.open(hand_path) as opened:
        hand_alpha = np.asarray(opened.convert("RGBA").getchannel("A"), dtype=np.uint8)
    with Image.open(violin_path) as opened:
        violin_image = opened.convert("RGBA")
    violin_rgba = np.asarray(violin_image, dtype=np.uint8).copy()

    x = int(violin_specification["x"])
    y = int(violin_specification["y"])
    hand_x = int(hand_layer["x"])
    hand_y = int(hand_layer["y"])
    height, width = hand_alpha.shape
    vx0, vy0 = max(x, hand_x), max(y, hand_y)
    vx1 = min(x + violin_image.width, hand_x + width)
    vy1 = min(y + violin_image.height, hand_y + height)
    if vx1 <= vx0 or vy1 <= vy0:
        return {"method": "no_overlap", "pixels_removed": 0, "hand_pixels": int(np.count_nonzero(hand_alpha))}

    global_hand = np.zeros((y + violin_image.height, x + violin_image.width), dtype=np.uint8)
    gx0, gy0 = max(0, hand_x), max(0, hand_y)
    gx1, gy1 = min(global_hand.shape[1], hand_x + width), min(global_hand.shape[0], hand_y + height)
    if gx1 <= gx0 or gy1 <= gy0:
        raise ManualReviewRequired("The fretting-hand overlay lies outside the violin prop coordinate frame.")
    global_hand[gy0:gy1, gx0:gx1] = hand_alpha[
        gy0 - hand_y:gy1 - hand_y,
        gx0 - hand_x:gx1 - hand_x,
    ]
    local_hand = global_hand[y:y + violin_image.height, x:x + violin_image.width] > 12
    if dilation_radius:
        kernel = np.ones((dilation_radius * 2 + 1, dilation_radius * 2 + 1), dtype=np.uint8)
        local_hand = cv2.dilate(local_hand.astype(np.uint8), kernel, iterations=1) > 0

    before = violin_rgba[:, :, 3].copy()
    violin_rgba[local_hand, 3] = 0
    removed = int(np.count_nonzero((before > 12) & (violin_rgba[:, :, 3] <= 12)))
    violin_image = Image.fromarray(violin_rgba, mode="RGBA")
    violin_image.save(violin_path, format="WEBP", quality=98, method=6)
    return {
        "method": "source_hand_alpha_cutout_plus_one_pixel_seam",
        "pixels_removed": removed,
        "hand_pixels": int(np.count_nonzero(hand_alpha)),
        "dilation_radius": int(dilation_radius),
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


def _remove_embedded_props_from_static_layers(
    bundle_dir: Path,
    character: dict[str, Any],
    prop_masks: dict[str, np.ndarray],
) -> dict[str, Any]:
    """Remove source-baked violin/bow pixels from static head and torso plates.

    The original playing reference is a composite: the semantic torso/head
    plates can contain the original violin and bow even though separate,
    independently animated prop sprites are also added. Leaving those pixels
    in the static plates creates a visible second bow/violin in the render.

    Remove only the source-aligned prop alpha (plus a one-pixel seam) from
    static body layers. The cleaned parent plate behind these layers provides
    the reconstructed body underneath, while the separate props are rendered
    at their intended depth. Moving limb/hand layers are handled independently.
    """
    try:
        import cv2
    except ImportError as exc:
        raise AutoRigError("OpenCV is required to remove embedded instrument pixels from static layers.") from exc

    roles_to_clean = {"torso", "head", "face"}
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3))
    report: dict[str, Any] = {
        "method": "source_aligned_prop_alpha_removed_from_static_body_plates",
        "layers": {},
        "total_pixels_removed": 0,
        "automatic_layer_replacement": False,
        "source_alpha_geometry_preserved": True,
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
    # The head/face layers are replaced by the reference-sheet plates at render
    # time. Clear their source pixels from the parent art so expression/angle
    # changes cannot create doubled eyes, hairlines or ghost faces.
    cut = _morph(moving | bow | violin | head, 2, "dilate")
    cut &= rgba[:, :, 3] > 12
    if int(cut.sum()) < 1000:
        raise ManualReviewRequired("The source-aligned limb/prop cutout is unexpectedly small.")
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
        "bow_pixels_reconstructed": int((bow & cut).sum()),
        "violin_pixels_reconstructed": int((violin & cut).sum()),
        "head_pixels_reconstructed": int((head & cut).sum()),
        "head_plate_replacement_enabled": bool(head.any()),
        "head_cutout_method": "source_aligned_autorig_head_and_face_alpha",
        "source_alpha_preserved": True,
        "source_pixels_outside_cut_mask_preserved": True,
        "inpaint": "opencv_telea_radius_5_alpha_aware",
        "transparent_source_pixels_excluded_from_inpaint": int((~visible_source).sum()),
        "transparent_rgb_excluded_from_reconstruction": True,
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
            **specification,
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

    # Remove source-baked violin, bow stick and bow hair from semantic static
    # layers. The separate animated prop sprites are the only render instances.
    static_layer_prop_cleanup = _remove_embedded_props_from_static_layers(
        bundle,
        character,
        prop_masks,
    )

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
    violin_hand_cleanup = _clip_hand_from_violin_prop(
        bundle,
        violin_specification=(prop_manifest.get("props") or {})["violin"],
        hand_layer=right_hand_layer,
        dilation_radius=1,
    )
    limb_report["violin_hand_overlap_cleanup"] = violin_hand_cleanup

    # Finger polygons are extracted from the source-aligned right-hand layer.
    finger_layers, finger_joints, finger_areas = _prepare_fingers(
        source, bundle, character, finger_path
    ) if finger_path else ([], {}, {})
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
        "joint_additions": sorted(limb_joints.keys() | finger_joints.keys()),
        "limb_report": limb_report,
        "source_edge_color_decontamination": edge_decontamination,
        "bow_hair_restoration": bow_hair_restoration,
        "static_layer_prop_cleanup": static_layer_prop_cleanup,
        "violin_hand_overlap_cleanup": violin_hand_cleanup,
        "finger_pixel_areas": finger_areas,
        "prop_report": prop_report,
        "body_plate_prop_pixels_removed": {"torso": 0, "arms": 0},
        "prop_compositing": "source_aligned_body_base_with_separate_limb_and_prop_layers",
        "composite_base": composite_base,
        "composite_source": source_input.name,
        "segmented_limb_masks_status": "source_aligned_polygon_regions_active_in_preview",
        "neutral_apose_reference": neutral_report,
        "publishing": "disabled",
        "preview_only": True,
        "visual_review_required": True,
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
        report_path = bundle / "full-body-performance-report.json"
        report = json.loads(report_path.read_text(encoding="utf-8"))
        report["reference_sheet_rig"] = reference_report
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print("FULL_BODY_PERFORMANCE_RIG=" + json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
