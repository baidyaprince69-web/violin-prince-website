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
        source_alpha = np.asarray(source.getchannel("A"), dtype=np.uint8)
        finger_mask = region_mask & (source_alpha > 0)
        if int(finger_mask.sum()) < 20:
            raise ManualReviewRequired(f"Finger region {name} does not overlap visible character pixels.")
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
            cut = region_mask[y0:y1, x0:x1]
            local = hand_alpha[y0 - hy:y1 - hy, x0 - hx:x1 - hx]
            local[cut] = 0

    hand_image.putalpha(Image.fromarray(hand_alpha, mode="L"))
    hand_image.save(hand_path, format="PNG", optimize=True)
    return layers, joints, areas


def _build_preserved_composite_base(
    source: Image.Image,
    bundle_dir: Path,
    *,
    bow_canvas_alpha: np.ndarray,
    character: dict[str, Any],
    finger_manifest_path: Path | None,
) -> dict[str, Any]:
    """Build an intact full-body safety plate while modular limb masks are reworked.

    The source illustration remains the authority for the sleeves, both hands,
    trousers and shoes. Only the bow shaft and authored finger polygons are
    separated; this prevents low-confidence semantic masks from creating holes
    in the visible presenter.
    """
    try:
        import cv2
    except ImportError as exc:
        raise AutoRigError(
            "OpenCV is required to prepare the complete-body review plate."
        ) from exc

    rgba = np.asarray(source.convert("RGBA"), dtype=np.uint8).copy()
    height, width = rgba.shape[:2]
    bow_mask = np.asarray(bow_canvas_alpha, dtype=np.uint8)
    if bow_mask.shape != (height, width):
        raise AutoRigError("The bow mask must match the complete-body source canvas.")
    bow_pixels = bow_mask > 12
    if int(bow_pixels.sum()) < 40:
        raise ManualReviewRequired("The bow mask is too small to prepare a complete-body plate.")

    # Preserve the source bow-grip hand above the independently animated bow.
    # The hand layer is an exact crop of the supplied performance illustration.
    hand_layer = next(
        (layer for layer in character.get("layers", []) if layer.get("role") == "left_hand"),
        None,
    )
    hand_protect = np.zeros((height, width), dtype=bool)
    if hand_layer:
        hand_path = bundle_dir / str(hand_layer["src"])
        with Image.open(hand_path) as opened:
            hand_alpha = np.asarray(opened.convert("RGBA").getchannel("A"), dtype=np.uint8)
        hx, hy = int(hand_layer["x"]), int(hand_layer["y"])
        h, w = hand_alpha.shape
        hand_protect[hy:hy + h, hx:hx + w] = hand_alpha > 12
    bow_clear = bow_pixels & ~hand_protect
    # A one-pixel edge expansion prevents a dark source outline from remaining
    # behind the moving bow. The authored grip hand is kept intact.
    bow_clear = _morph(bow_clear, 1, "dilate") & ~hand_protect
    rgb = rgba[:, :, :3]
    repaired_rgb = cv2.inpaint(
        rgb,
        bow_clear.astype(np.uint8) * 255,
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
        "preserves_original_arms_hands_legs_and_head": True,
    }


def extend_full_body_character(
    source_path: str | Path,
    bundle_dir: str | Path,
    *,
    prop_dir: str | Path,
    instrument_manifest_path: str | Path,
    finger_manifest_path: str | Path | None = None,
    neutral_apose_path: str | Path | None = None,
) -> dict[str, Any]:
    source_path = Path(source_path).resolve(strict=True)
    bundle = Path(bundle_dir).resolve(strict=True)
    prop_root = Path(prop_dir).resolve(strict=True)
    manifest_path = Path(instrument_manifest_path).resolve(strict=True)
    finger_path = Path(finger_manifest_path).resolve() if finger_manifest_path else None
    character_path = bundle / "character.json"
    if not character_path.is_file():
        raise AutoRigError("The base Auto-Rig bundle must contain character.json.")

    with Image.open(source_path) as opened:
        source = opened.convert("RGBA")
    rgba = np.asarray(source, dtype=np.uint8)
    alpha = rgba[:, :, 3]
    # Feed a clean white-composited copy to the real-person parser; keep alpha for final cutouts.
    parse_plate = Image.new("RGBA", source.size, (255, 255, 255, 255))
    parse_plate.alpha_composite(source)
    parser = SCHPOnnxParser(*PASCAL_MODEL, revision=PASCAL_REVISION)
    labels, confidence = parser.parse(parse_plate.convert("RGB"))
    _ = confidence

    character = json.loads(character_path.read_text(encoding="utf-8"))
    leg_layers, leg_joints, leg_report = _leg_layers(source, labels, character, bundle)
    character["layers"].extend(leg_layers)
    character["joints"].update(leg_joints)

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

    # Keep every body plate intact. Instrument sprites are independent overlay
    # layers with explicit z-order: violin above torso/upper arms but below
    # forearms/hands; bow above forearms but below the bow-grip hand. Erasing
    # the prop alpha from body plates creates transparent gaps wherever the
    # prop's antialiased or semi-transparent edges do not fully cover them.
    removable_roles = (
        "torso", "left_upper_arm", "right_upper_arm",
        "left_forearm", "right_forearm",
    )
    removed_by_role = {role: 0 for role in removable_roles}

    finger_layers, finger_joints, finger_areas = _prepare_fingers(
        source, bundle, character, finger_path
    ) if finger_path else ([], {}, {})
    character["layers"].extend(finger_layers)
    character["joints"].update(finger_joints)
    character["props"] = props
    character["performance"] = {
        "schema": "violin-prince-fullbody-performance-v1",
        "instrument_performance": True,
        "fingering_parts": sorted(finger_areas),
        "bow_prop_id": "bow",
        "violin_prop_id": "violin",
        "review_required": True,
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
        "status": "candidate_full_body_performance_rig_ready_for_review",
        "character_id": character["id"],
        "canvas": character["canvas"],
        "base_layer_count": 9,
        "full_body_layer_count": len(leg_layers),
        "finger_layer_count": len(finger_layers),
        "joint_additions": sorted(leg_joints.keys() | finger_joints.keys()),
        "leg_report": leg_report,
        "finger_pixel_areas": finger_areas,
        "prop_report": prop_report,
        "body_plate_prop_pixels_removed": removed_by_role,
        "prop_compositing": "independent_overlay_layers_preserve_body_plates",
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
