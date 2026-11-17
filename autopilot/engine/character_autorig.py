#!/usr/bin/env python3
"""Model-assisted separation of one illustrated character into candidate rig layers.

SCHP semantic masks provide coarse body parts, face, hair and arm-side cues.
A small hidden-overlap mask is repaired locally; larger gaps use optional LaMa
inpainting and otherwise stop for review. Outputs are candidates, not approved art.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

PASCAL_MODEL = ("pirocheto/schp-pascal-7", "onnx/schp-pascal-7-int8-static.onnx")
ATR_MODEL = ("pirocheto/schp-atr-18", "onnx/schp-atr-18-int8-static.onnx")

EXPRESSION_FILES = {
    "neutral": "face-neutral.jpg",
    "blink": "face-blink.jpg",
    "speaking": "face-speaking.jpg",
    "smile": "face-smile.jpg",
    "shocked": "face-shocked.jpg",
    "sad": "face-sad.jpg",
}
POSE_FILES = {
    "resting_hands": "pose-resting-hands.jpg",
    "one_arm_raised": "pose-one-arm-raised.jpg",
    "explaining_two_hands": "pose-explaining-two-hands.jpg",
    "open_palms": "pose-open-palms.jpg",
    "point_left": "pose-point-left.jpg",
    "point_right": "pose-point-right.jpg",
}
ROLE_Z = {
    "torso": 10,
    "left_upper_arm": 20, "right_upper_arm": 21,
    "left_forearm": 30, "right_forearm": 31,
    "left_hand": 40, "right_hand": 41,
    "head": 50, "face": 60,
}
JOINT_FOR_ROLE = {
    "head": "neck",
    "left_upper_arm": "left_shoulder",
    "left_forearm": "left_elbow",
    "left_hand": "left_wrist",
    "right_upper_arm": "right_shoulder",
    "right_forearm": "right_elbow",
    "right_hand": "right_wrist",
}


class AutoRigError(RuntimeError):
    """Raised when automatic character preparation cannot continue safely."""


class ManualReviewRequired(AutoRigError):
    """Raised when model output or hidden-area repair needs human intervention."""


class SCHPOnnxParser:
    """CPU ONNX wrapper using the model card's Hugging Face image processor."""

    def __init__(self, model_id: str, filename: str, *, cache_dir: str | Path | None = None):
        try:
            import onnxruntime as ort
            from huggingface_hub import hf_hub_download
            from transformers import AutoImageProcessor
        except ImportError as exc:
            raise AutoRigError(
                "Character parsing dependencies are missing. Install "
                "autopilot/engine/requirements-character.txt."
            ) from exc

        try:
            self.processor = AutoImageProcessor.from_pretrained(
                model_id, trust_remote_code=True
            )
            model_path = hf_hub_download(
                repo_id=model_id,
                filename=filename,
                cache_dir=str(cache_dir) if cache_dir else None,
            )
            options = ort.SessionOptions()
            options.intra_op_num_threads = 4
            options.inter_op_num_threads = 1
            options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
            self.session = ort.InferenceSession(
                model_path, sess_options=options, providers=["CPUExecutionProvider"]
            )
        except Exception as exc:
            raise AutoRigError(f"Could not load SCHP model {model_id}: {exc}") from exc

        inputs = self.session.get_inputs()
        outputs = self.session.get_outputs()
        if not inputs or not outputs:
            raise AutoRigError(f"SCHP model {model_id} has no input or output tensors.")
        self.input_name = inputs[0].name
        self.output_name = next(
            (item.name for item in outputs if item.name == "logits"),
            outputs[0].name,
        )
        self.model_id = model_id

    def parse(self, image: Image.Image) -> tuple[np.ndarray, np.ndarray]:
        try:
            prepared = self.processor(images=image.convert("RGB"), return_tensors="np")
            pixels = np.asarray(prepared["pixel_values"], dtype=np.float32)
            logits = self.session.run(
                [self.output_name], {self.input_name: pixels}
            )[0]
        except Exception as exc:
            raise AutoRigError(f"SCHP inference failed for {self.model_id}: {exc}") from exc

        logits = np.asarray(logits, dtype=np.float32)
        if logits.ndim != 4 or logits.shape[0] != 1:
            raise AutoRigError(f"Unexpected SCHP logits shape from {self.model_id}: {logits.shape}")
        shifted = logits[0] - np.max(logits[0], axis=0, keepdims=True)
        probabilities = np.exp(shifted)
        probabilities /= np.maximum(probabilities.sum(axis=0, keepdims=True), 1e-9)
        labels_small = np.argmax(probabilities, axis=0).astype(np.uint8)
        confidence_small = np.max(probabilities, axis=0).astype(np.float32)

        labels = np.asarray(
            Image.fromarray(labels_small, mode="L").resize(image.size, Image.Resampling.NEAREST),
            dtype=np.uint8,
        )
        confidence = np.asarray(
            Image.fromarray(
                np.clip(confidence_small * 255, 0, 255).astype(np.uint8), mode="L"
            ).resize(image.size, Image.Resampling.BILINEAR),
            dtype=np.float32,
        ) / 255.0
        return labels, confidence


def _download_parsers(cache_dir: str | Path | None = None):
    return (
        SCHPOnnxParser(*PASCAL_MODEL, cache_dir=cache_dir),
        SCHPOnnxParser(*ATR_MODEL, cache_dir=cache_dir),
    )


def _mask(labels: np.ndarray, label_id: int) -> np.ndarray:
    return np.asarray(labels == label_id, dtype=bool)


def _morph(mask: np.ndarray, radius: int, operation: str) -> np.ndarray:
    if radius <= 0:
        return np.asarray(mask, dtype=bool)
    image = Image.fromarray(np.asarray(mask, dtype=np.uint8) * 255, mode="L")
    kernel = radius * 2 + 1
    if operation == "dilate":
        image = image.filter(ImageFilter.MaxFilter(kernel))
    else:
        image = image.filter(ImageFilter.MinFilter(kernel))
    return np.asarray(image, dtype=np.uint8) > 0


def _clean_segmentation_specks(mask: np.ndarray, size: int = 9) -> np.ndarray:
    """Remove isolated parser specks before calculating head/face geometry."""
    if size < 3 or size % 2 == 0:
        raise ValueError("Segmentation cleanup size must be an odd integer >= 3.")
    image = Image.fromarray(np.asarray(mask, dtype=np.uint8) * 255, mode="L")
    # Opening removes small detached blobs that otherwise stretch a layer crop
    # across the canvas, while preserving the large connected illustrated region.
    image = image.filter(ImageFilter.MinFilter(size)).filter(ImageFilter.MaxFilter(size))
    return np.asarray(image, dtype=np.uint8) > 0


def _remove_edge_connected_near_white(
    image: Image.Image,
    masks: dict[str, np.ndarray],
    *,
    minimum_brightness: int = 235,
    maximum_spread: int = 30,
) -> tuple[dict[str, np.ndarray], float]:
    """Remove the white studio backdrop from each segmentation mask.

    Only near-white pixels connected to the outer image border are removed.
    White details enclosed by the character line art (eyes, highlights, palms)
    remain in the foreground. This is particularly important for head/face
    crops, where a few background pixels otherwise become a visible white tile.
    """
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    minimum = rgb.min(axis=2).astype(np.int16)
    spread = rgb.max(axis=2).astype(np.int16) - minimum
    candidate = (minimum >= int(minimum_brightness)) & (spread <= int(maximum_spread))

    # Close small JPEG gaps in the light backdrop before tracing the component
    # that touches the source border.
    candidate_image = Image.fromarray(candidate.astype(np.uint8) * 255, mode="L")
    candidate_image = candidate_image.filter(ImageFilter.MaxFilter(7))
    candidate_image = candidate_image.filter(ImageFilter.MinFilter(7))

    height, width = candidate.shape
    padded = Image.new("L", (width + 2, height + 2), 255)
    padded.paste(candidate_image, (1, 1))
    ImageDraw.floodfill(padded, (0, 0), 128, thresh=0)
    background = np.asarray(padded, dtype=np.uint8)[1:-1, 1:-1] == 128

    # Remove the antialiased fringe next to the connected backdrop.
    background_image = Image.fromarray(background.astype(np.uint8) * 255, mode="L")
    background_image = background_image.filter(ImageFilter.MaxFilter(3))
    background = np.asarray(background_image, dtype=np.uint8) > 0
    foreground = ~background
    cleaned = {
        name: np.asarray(mask, dtype=bool) & foreground
        for name, mask in masks.items()
    }
    for name, mask in cleaned.items():
        if not mask.any():
            raise ManualReviewRequired(
                f"Background cleanup removed the entire {name} mask; manual review is required."
            )
    return cleaned, round(float(background.mean()), 6)


def _bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        raise AutoRigError("A required character region has an empty segmentation mask.")
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _face_region_from_head(head_mask: np.ndarray) -> np.ndarray:
    """Create a smooth oval face plate inside the parsed head silhouette."""
    x0, y0, x1, y1 = _bbox(head_mask)
    width, height = x1 - x0, y1 - y0
    fx0, fx1 = x0 + round(width * 0.10), x0 + round(width * 0.90)
    fy0, fy1 = y0 + round(height * 0.34), y0 + round(height * 0.87)

    # Draw at 4x resolution so the alpha edge is smooth rather than a hard
    # polygon. The ellipse keeps the face plate away from hair and neck pixels.
    scale = 4
    face = Image.new(
        "L",
        (head_mask.shape[1] * scale, head_mask.shape[0] * scale),
        0,
    )
    draw = ImageDraw.Draw(face)
    draw.ellipse(
        (fx0 * scale, fy0 * scale, (fx1 - 1) * scale, (fy1 - 1) * scale),
        fill=255,
    )
    face = face.resize(
        (head_mask.shape[1], head_mask.shape[0]),
        Image.Resampling.LANCZOS,
    )
    region = np.asarray(face, dtype=np.uint8) > 127
    region &= np.asarray(head_mask, dtype=bool)
    if int(region.sum()) < 100:
        raise ManualReviewRequired("Could not derive a stable face region inside the head mask.")
    return region


def _centroid(mask: np.ndarray) -> tuple[float, float]:
    ys, xs = np.where(mask)
    if len(xs) == 0:
        raise AutoRigError("Cannot locate a joint on an empty mask.")
    return float(xs.mean()), float(ys.mean())


def _screen_side_masks(
    detail_labels: np.ndarray, coarse_arms: np.ndarray, torso: np.ndarray
) -> tuple[dict[str, np.ndarray], str]:
    """Map arms to screen sides, using Pascal coarse masks if ATR misses a side."""
    candidates = []
    for label_id in (14, 15):
        candidate = _mask(detail_labels, label_id)
        if int(candidate.sum()) >= 40:
            candidates.append((float(np.where(candidate)[1].mean()), candidate))
    if len(candidates) == 2:
        candidates.sort(key=lambda item: item[0])
        return {"left": candidates[0][1], "right": candidates[1][1]}, "atr_arm_labels"

    # Cartoon illustrations often do not map cleanly to both ATR left/right labels.
    # Fall back to the independent Pascal arm mask, split around the torso midpoint.
    # Continue only when both resulting screen-side regions have enough pixels;
    # otherwise fail closed for manual review.
    tx0, _, tx1, _ = _bbox(torso)
    center = (tx0 + tx1) / 2
    width = coarse_arms.shape[1]
    xgrid = np.broadcast_to(np.arange(width)[None, :], coarse_arms.shape)
    left = coarse_arms & (xgrid < center)
    right = coarse_arms & (xgrid >= center)
    if int(left.sum()) < 40 or int(right.sum()) < 40:
        raise ManualReviewRequired(
            "The parsers could not distinguish two arms. Use a clearer front-facing master image."
        )
    return {"left": left, "right": right}, "pascal_coarse_screen_split"


def _split_arm(
    side_mask: np.ndarray,
    upper_all: np.ndarray,
    lower_all: np.ndarray,
    side: str,
    *,
    hand_fraction: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    near_side = _morph(side_mask, 4, "dilate")
    upper = upper_all & near_side
    lower = lower_all & near_side
    if int(upper.sum()) < 30:
        raise ManualReviewRequired(f"Could not isolate the {side} upper arm.")
    if int(lower.sum()) < 45:
        # A coarse fallback is allowed only when the ATR side mask remains clear.
        lower = side_mask & ~_morph(upper, 3, "dilate")
    if int(lower.sum()) < 45:
        raise ManualReviewRequired(f"Could not isolate the {side} forearm and hand.")

    ux, uy = _centroid(upper)
    ys, xs = np.where(lower)
    dx = xs.astype(np.float32) - ux
    dy = ys.astype(np.float32) - uy
    far = int(np.argmax(dx * dx + dy * dy))
    axis = np.asarray([dx[far], dy[far]], dtype=np.float32)
    norm = float(np.linalg.norm(axis))
    if norm < 5:
        raise ManualReviewRequired(f"The {side} arm direction is too ambiguous to rig.")
    axis /= norm
    projection = dx * axis[0] + dy * axis[1]
    low, high = float(np.percentile(projection, 2)), float(np.percentile(projection, 98))
    if high - low < 8:
        raise ManualReviewRequired(f"The {side} hand/forearm split is too short.")
    cut = low + float(hand_fraction) * (high - low)
    hand = np.zeros_like(side_mask)
    hand[ys[projection >= cut], xs[projection >= cut]] = True
    forearm = lower & ~hand
    if int(hand.sum()) < 20 or int(forearm.sum()) < 20:
        raise ManualReviewRequired(
            f"The {side} hand/forearm split is unreliable. Review the hand split or source artwork."
        )
    return upper, forearm, hand


def _dilate3(mask: np.ndarray) -> np.ndarray:
    """Fast 8-connected one-pixel binary dilation for local mask growth."""
    padded = np.pad(np.asarray(mask, dtype=bool), 1, constant_values=False)
    height, width = mask.shape
    grown = np.zeros((height, width), dtype=bool)
    for dy in range(3):
        for dx in range(3):
            grown |= padded[dy:dy + height, dx:dx + width]
    return grown


def _recover_hand_fingers_from_skin(
    image: Image.Image,
    hand: np.ndarray,
    upper: np.ndarray,
    *,
    distal_floor_fraction: float = 0.52,
) -> tuple[np.ndarray, int]:
    """Recover illustrated finger regions omitted by coarse human-parsing labels.

    SCHP's coarse lower-arm class often captures a cartoon palm but excludes
    thin, outlined fingers. Within a tightly bounded distal-hand window, warm
    skin-colour pixels connected to the model's hand seed are grown into the
    hand layer. This is a conservative supplement, not a standalone detector.
    """
    if image.size != (hand.shape[1], hand.shape[0]) or hand.shape != upper.shape:
        raise AutoRigError("Hand recovery masks must match the master image canvas.")

    ux, uy = _centroid(upper)
    hy, hx = np.where(hand)
    if len(hx) < 20:
        raise ManualReviewRequired("The semantic hand seed is too small for skin-assisted recovery.")
    dx = hx.astype(np.float32) - ux
    dy = hy.astype(np.float32) - uy
    seed_far = int(np.argmax(dx * dx + dy * dy))
    axis = np.asarray([dx[seed_far], dy[seed_far]], dtype=np.float32)
    norm = float(np.linalg.norm(axis))
    if norm < 5:
        raise ManualReviewRequired("The hand direction is too ambiguous for finger recovery.")
    axis /= norm

    # Use the complete forearm+hand silhouette to estimate the hand's distal
    # interval, while keeping the search window close to the semantic hand.
    ey, ex = np.where(hand | _morph(upper, 2, "dilate"))
    if len(ex) < 40:
        return hand, 0
    all_dx = ex.astype(np.float32) - ux
    all_dy = ey.astype(np.float32) - uy
    projections = all_dx * axis[0] + all_dy * axis[1]
    low, high = float(np.percentile(projections, 2)), float(np.percentile(projections, 98))
    if high - low < 12:
        return hand, 0

    x0, y0, x1, y1 = _bbox(hand)
    pad = max(36, min(180, int(max(x1 - x0, y1 - y0) * 0.45)))
    rx0, ry0 = max(0, x0 - pad), max(0, y0 - pad)
    rx1, ry1 = min(image.width, x1 + pad), min(image.height, y1 + pad)
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)[ry0:ry1, rx0:rx1]
    red, green, blue = (rgb[..., index].astype(np.int16) for index in range(3))

    # Broad warm-skin chroma limits tolerate shaded illustrated fingers while
    # excluding the neutral near-white backdrop and most dark jacket pixels.
    skin = (
        (red >= 88) & (red <= 250) &
        (green >= 42) &
        (red - green >= 22) &
        (green - blue >= 8) &
        (red - blue >= 38)
    )
    yy, xx = np.mgrid[ry0:ry1, rx0:rx1]
    projected = (xx - ux) * axis[0] + (yy - uy) * axis[1]
    distal_floor = low + float(distal_floor_fraction) * (high - low)
    allowed = skin & (projected >= distal_floor)

    # Close only tiny antialiasing gaps between a palm seed and its fingers.
    allowed = _morph(allowed, 2, "dilate")
    allowed = _morph(allowed, 2, "erode")
    seed = hand[ry0:ry1, rx0:rx1].copy()
    grown = seed.copy()
    # Morphological reconstruction keeps only skin components connected to
    # the semantic hand. The bounded window makes this deterministic and cheap.
    for _ in range(max(24, min(320, int(high - low) + 8))):
        next_grown = grown | (allowed & _dilate3(grown))
        if np.array_equal(next_grown, grown):
            break
        grown = next_grown

    # Expand by one pixel to retain the dark outline around the recovered
    # fingers. Border flood-fill later removes any near-white background fringe.
    recovered = _morph(grown, 1, "dilate")
    result = hand.copy()
    result[ry0:ry1, rx0:rx1] |= recovered
    added = int(np.count_nonzero(result & ~hand))
    return result, added


def _joint_disk(
    shape: tuple[int, int],
    point: tuple[float, float],
    *,
    radius: int,
) -> np.ndarray:
    """A bounded circular overlap zone centred on an authored joint anchor."""
    if radius < 1:
        raise ValueError("Joint patch radius must be at least one pixel.")
    height, width = shape
    yy, xx = np.ogrid[:height, :width]
    px, py = point
    return (xx - float(px)) ** 2 + (yy - float(py)) ** 2 <= int(radius) ** 2


def _dark_garment_underlap(
    image: Image.Image,
    child: np.ndarray,
    parent: np.ndarray,
    allowed: np.ndarray,
    *,
    radius: int,
    maximum_channel_value: int = 145,
) -> np.ndarray:
    """Select dark sleeve pixels for a parent layer to hide beneath a child.

    Skin pixels must never be copied into the stationary parent layer: doing
    so would leave a duplicate palm when the hand rotates around the wrist.
    """
    if radius < 1:
        raise ValueError("Joint underlap radius must be at least one pixel.")
    if image.size != (child.shape[1], child.shape[0]) or child.shape != parent.shape or child.shape != allowed.shape:
        raise AutoRigError("Joint underlap inputs must match the master image canvas.")
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    dark_garment = rgb.max(axis=2) <= int(maximum_channel_value)
    return (
        _morph(child, radius, "dilate")
        & np.asarray(allowed, dtype=bool)
        & ~np.asarray(parent, dtype=bool)
        & dark_garment
    )


def _joint_between(first: np.ndarray, second: np.ndarray) -> tuple[float, float]:
    seam = _morph(first, 4, "dilate") & _morph(second, 4, "dilate")
    if seam.any():
        return _centroid(seam)
    ax, ay = _centroid(first)
    bx, by = _centroid(second)
    return (ax + bx) / 2, (ay + by) / 2


def _local_inpaint(image: np.ndarray, hole: np.ndarray, *, max_steps: int = 64) -> np.ndarray:
    """Fill only small overlap masks by propagating neighbouring RGB values."""
    result = image.copy()
    unknown = np.asarray(hole, dtype=bool).copy()
    known = ~unknown
    height, width = unknown.shape
    offsets = [
        (-1, -1), (-1, 0), (-1, 1), (0, -1),
        (0, 1), (1, -1), (1, 0), (1, 1),
    ]
    for _ in range(max_steps):
        if not unknown.any():
            break
        padded_known = np.pad(known, 1, constant_values=False)
        padded_rgb = np.pad(result, ((1, 1), (1, 1), (0, 0)), mode="edge")
        total = np.zeros((height, width, 3), dtype=np.float32)
        count = np.zeros((height, width), dtype=np.float32)
        for dy, dx in offsets:
            y0, x0 = 1 + dy, 1 + dx
            neighbour_known = padded_known[y0:y0 + height, x0:x0 + width]
            neighbour_rgb = padded_rgb[y0:y0 + height, x0:x0 + width]
            total += neighbour_rgb * neighbour_known[:, :, None]
            count += neighbour_known
        fill = unknown & (count > 0)
        if not fill.any():
            break
        result[fill] = np.clip(total[fill] / count[fill, None], 0, 255).astype(np.uint8)
        known[fill] = True
        unknown[fill] = False
    if unknown.any():
        raise ManualReviewRequired("Local hidden-area reconstruction did not converge.")
    return result


def _repair_hidden_area(
    image: Image.Image,
    hole: np.ndarray,
    *,
    max_local_ratio: float,
) -> tuple[Image.Image, str, float]:
    rgb = np.asarray(image.convert("RGB"), dtype=np.uint8)
    hole = np.asarray(hole, dtype=bool)
    ratio = float(hole.sum()) / max(1, hole.size)
    if not hole.any():
        return Image.fromarray(rgb), "not_required", 0.0
    if ratio <= max_local_ratio:
        return Image.fromarray(_local_inpaint(rgb, hole)), "local_neighbour_propagation", ratio
    try:
        from simple_lama_inpainting import SimpleLama
    except ImportError as exc:
        raise ManualReviewRequired(
            f"Hidden pixels cover {ratio:.1%} of the master image. Install "
            "autopilot/engine/requirements-character-lama.txt for LaMa reconstruction, "
            "or provide a clean torso plate."
        ) from exc
    try:
        lama = SimpleLama()
        repaired = lama(
            Image.fromarray(rgb, mode="RGB"),
            Image.fromarray(hole.astype(np.uint8) * 255, mode="L"),
        )
    except Exception as exc:
        raise ManualReviewRequired(f"LaMa hidden-area reconstruction failed: {exc}") from exc
    return repaired.convert("RGB"), "lama_inpainting", ratio


def _save_layer(
    image: Image.Image, mask: np.ndarray, destination: Path, *, padding: int = 8
) -> dict[str, Any]:
    x0, y0, x1, y1 = _bbox(mask)
    x0, y0 = max(0, x0 - padding), max(0, y0 - padding)
    x1, y1 = min(image.width, x1 + padding), min(image.height, y1 + padding)
    crop = image.convert("RGB").crop((x0, y0, x1, y1)).convert("RGBA")
    alpha = Image.fromarray(mask[y0:y1, x0:x1].astype(np.uint8) * 255, mode="L")
    crop.putalpha(alpha)
    destination.parent.mkdir(parents=True, exist_ok=True)
    crop.save(destination, format="PNG", optimize=True)
    return {
        "src": destination.name,
        "x": x0, "y": y0,
        "width": x1 - x0, "height": y1 - y0,
        "pixel_area": int(mask.sum()),
    }


def _save_mask_preview(image: Image.Image, masks: dict[str, np.ndarray], path: Path) -> None:
    palette = {
        "torso": (30, 180, 190), "head": (250, 190, 50), "face": (255, 90, 120),
        "left_upper_arm": (70, 160, 250), "right_upper_arm": (90, 150, 245),
        "left_forearm": (80, 210, 140), "right_forearm": (90, 205, 135),
        "left_hand": (180, 110, 245), "right_hand": (195, 105, 235),
    }
    colour = np.zeros((image.height, image.width, 3), dtype=np.uint8)
    for name, region in masks.items():
        colour[np.asarray(region, dtype=bool)] = palette[name]
    overlay = Image.fromarray(colour, mode="RGB")
    Image.blend(image.convert("RGB"), overlay, 0.42).save(path)


def _normalise_joint(point: tuple[float, float], width: int, height: int) -> dict[str, float]:
    return {
        "x": round(min(1.0, max(0.0, point[0] / max(1, width - 1))), 6),
        "y": round(min(1.0, max(0.0, point[1] / max(1, height - 1))), 6),
    }


def separate_from_parsing(
    image: Image.Image,
    body_labels: np.ndarray,
    body_confidence: np.ndarray,
    detail_labels: np.ndarray,
    detail_confidence: np.ndarray,
    *,
    hand_fraction: float = 0.72,
    max_local_inpaint_ratio: float = 0.025,
):
    """Convert Pascal and ATR pixel labels into nine overlapping rig masks."""
    expected = (image.height, image.width)
    if any(array.shape != expected for array in (
        body_labels, body_confidence, detail_labels, detail_confidence
    )):
        raise AutoRigError("Parser maps must match the master image dimensions.")

    torso = _mask(body_labels, 2)
    head_coarse = _mask(body_labels, 1)
    upper_all = _mask(body_labels, 3)
    lower_all = _mask(body_labels, 4)
    # ATR face-class masks can include hair/neck on cartoon illustrations.
    # Use the independent Pascal head silhouette and a bounded facial region
    # inside that silhouette instead of trusting the ATR face class.
    hair = _clean_segmentation_specks(_mask(detail_labels, 2), size=9)
    head = _clean_segmentation_specks(head_coarse | hair, size=9)
    face = _face_region_from_head(head)
    if int(torso.sum()) < 100 or int(head.sum()) < 100 or int(face.sum()) < 40:
        raise ManualReviewRequired(
            "The parsers could not identify a reliable head, face and torso. "
            "Use a clearer, front-facing master illustration."
        )

    coarse_arms = upper_all | lower_all
    sides, arm_side_source = _screen_side_masks(detail_labels, coarse_arms, torso)
    masks: dict[str, np.ndarray] = {"torso": torso, "head": head, "face": face}
    hand_recovery_pixels: dict[str, int] = {}
    joint_reference_masks: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    joint_centers: dict[str, dict[str, tuple[float, float]]] = {}
    joint_overlap_pixels: dict[str, int] = {}
    for side in ("left", "right"):
        upper, forearm, hand = _split_arm(
            sides[side], upper_all, lower_all, side, hand_fraction=hand_fraction
        )
        hand, recovered_pixels = _recover_hand_fingers_from_skin(image, hand, upper)
        hand_recovery_pixels[side] = recovered_pixels
        forearm &= ~hand

        # Preserve the unexpanded boundaries for stable joint anchors. The
        # rendered layers receive hidden underlaps: upper arm sits behind the
        # forearm at the elbow, and forearm sits behind the hand at the wrist.
        # This prevents dark composition background from showing through when
        # child segments rotate independently.
        joint_reference_masks[f"{side}_elbow"] = (upper.copy(), forearm.copy())
        joint_reference_masks[f"{side}_wrist"] = (forearm.copy(), hand.copy())
        elbow_point = _joint_between(upper, forearm)
        wrist_point = _joint_between(forearm, hand)
        joint_centers[side] = {"elbow": elbow_point, "wrist": wrist_point}
        elbow_zone = _joint_disk(upper.shape, elbow_point, radius=24)
        wrist_zone = _joint_disk(hand.shape, wrist_point, radius=20)
        elbow_underlap = (
            _dark_garment_underlap(
                image, forearm, upper, sides[side], radius=8
            )
            & elbow_zone
        )
        # Wrist underlap is confined to a small patch around the pivot. This
        # bridges the rotating joint but cannot leave a second stationary palm.
        wrist_underlap = (
            _morph(hand, 8, "dilate")
            & sides[side]
            & ~forearm
            & wrist_zone
        )
        upper = upper | elbow_underlap
        forearm = forearm | wrist_underlap
        joint_overlap_pixels[f"{side}_elbow"] = int(elbow_underlap.sum())
        joint_overlap_pixels[f"{side}_wrist"] = int(wrist_underlap.sum())

        masks[f"{side}_upper_arm"] = upper
        masks[f"{side}_forearm"] = forearm
        masks[f"{side}_hand"] = hand

    masks, removed_background_ratio = _remove_edge_connected_near_white(image, masks)
    torso = masks["torso"]
    head = masks["head"]
    face = masks["face"]

    arm_union = np.zeros_like(torso)
    for name, region in masks.items():
        if name.endswith(("upper_arm", "forearm", "hand")):
            arm_union |= region

    # Only reconstruct arm pixels that cover the torso. Never erase the whole arm
    # from the source or extrapolate beyond this bounded overlap region.
    x0, y0, x1, y1 = _bbox(torso)
    zone = np.zeros_like(torso)
    zone[max(0, y0 - 4):min(image.height, y1 + 4),
         max(0, x0 - 4):min(image.width, x1 + 4)] = True
    hidden = arm_union & _morph(torso, 8, "dilate") & zone
    repaired, repair_method, hidden_ratio = _repair_hidden_area(
        image, hidden, max_local_ratio=max_local_inpaint_ratio
    )
    masks["torso"] = torso | hidden

    joints = {
        "neck": _normalise_joint(_joint_between(head, masks["torso"]), image.width, image.height)
    }
    for side in ("left", "right"):
        joints[f"{side}_shoulder"] = _normalise_joint(
            _joint_between(masks["torso"], masks[f"{side}_upper_arm"]), image.width, image.height
        )
        elbow_reference = joint_reference_masks[f"{side}_elbow"]
        wrist_reference = joint_reference_masks[f"{side}_wrist"]
        joints[f"{side}_elbow"] = _normalise_joint(
            _joint_between(*elbow_reference), image.width, image.height
        )
        joints[f"{side}_wrist"] = _normalise_joint(
            _joint_between(*wrist_reference), image.width, image.height
        )

    body_pixels = torso | head_coarse | upper_all | lower_all
    side_confidence = body_confidence if arm_side_source == "pascal_coarse_screen_split" else detail_confidence
    confidence = {
        "body_mean": round(float(body_confidence[body_pixels].mean()), 4),
        "face_mean": round(float(detail_confidence[face].mean()), 4),
        "left_arm_mean": round(float(side_confidence[sides["left"]].mean()), 4),
        "right_arm_mean": round(float(side_confidence[sides["right"]].mean()), 4),
    }
    if min(confidence.values()) < 0.20:
        raise ManualReviewRequired(
            "One or more required regions had very low model confidence: "
            + json.dumps(confidence)
        )

    report = {
        "source_width": image.width,
        "source_height": image.height,
        "model_pair": {
            "body_parts": "pirocheto/schp-pascal-7",
            "face_hair_and_arm_sides": "pirocheto/schp-atr-18",
        },
        "side_convention": "left and right refer to the viewer's screen sides",
        "arm_side_source": arm_side_source,
        "hand_split": "distal lower-arm split with connected warm-skin finger recovery; not a dedicated hand detector",
        "hand_split_fraction": float(hand_fraction),
        "hand_finger_recovery": {
            "method": "bounded_skin_colour_component_growth",
            "pixels_added": hand_recovery_pixels,
            "visual_review_required": True,
        },
        "joint_underlap": {
            "method": "child-overlap-covered-by-parent-layer",
            "elbow_radius_px": 24,
            "wrist_radius_px": 20,
            "wrist_patch": "localized_around_joint_anchor_only",
            "elbow_pixel_filter": "dark_sleeve_or_cuff_only",
            "elbow_maximum_source_channel_value": 145,
            "overlap_pixels": joint_overlap_pixels,
            "joint_anchors_use_unexpanded_masks": True,
            "visual_review_required": True,
        },
        "hidden_area_reconstruction": {
            "method": repair_method,
            "pixels_reconstructed": int(hidden.sum()),
            "fraction_of_source": round(hidden_ratio, 6),
        },
        "mean_confidence": confidence,
        "edge_connected_background_removal": {
            "method": "near_white_border_flood_fill",
            "background_fraction": removed_background_ratio,
            "preserves_enclosed_white_details": True,
        },
        "needs_visual_review": True,
        "review_reasons": [
            "SCHP was trained on real-person parsing datasets; illustration styles can reduce accuracy.",
            "Hand masks combine a distal lower-arm split with bounded skin-colour finger recovery; there is no dedicated semantic hand class.",
            "Review layer edges, hand/finger completeness, joint seams and reconstructed torso pixels.",
        ] + ([
            "ATR did not resolve both arm-side labels; side masks were derived from the coarse Pascal arm segmentation."
        ] if arm_side_source != "atr_arm_labels" else []),
    }
    return masks, repaired, report, joints


def _face_plate(
    path: Path,
    target_size: tuple[int, int],
    destination: Path,
    *,
    alpha_mask: np.ndarray,
) -> None:
    """Fit an authored expression to the exact master-face alpha silhouette.

    The supplied expressions share the same portrait framing as the master
    reference. A centre crop from forehead to chin is resized to the master
    face-layer geometry, then clipped to the same smooth alpha mask. This
    avoids rectangular backgrounds and changing face boundaries between poses.
    """
    with Image.open(path) as opened:
        image = opened.convert("RGB")
    width, height = image.size
    x0, x1 = int(width * 0.39), int(width * 0.61)
    y0, y1 = int(height * 0.33), int(height * 0.72)
    if x1 <= x0 or y1 <= y0:
        raise ManualReviewRequired(f"Invalid facial crop geometry for {path.name}.")
    crop = image.crop((x0, y0, x1, y1)).resize(
        target_size,
        Image.Resampling.LANCZOS,
    ).convert("RGBA")
    alpha = np.asarray(alpha_mask, dtype=bool)
    if alpha.shape != (target_size[1], target_size[0]):
        raise AutoRigError("Expression alpha mask must match the master face layer dimensions.")
    crop.putalpha(Image.fromarray(alpha.astype(np.uint8) * 255, mode="L"))
    destination.parent.mkdir(parents=True, exist_ok=True)
    crop.save(destination, format="PNG", optimize=True)


def _save_pose_plate(source_path: Path, destination: Path) -> None:
    """Remove the edge-connected near-white studio backdrop from a pose reference."""
    with Image.open(source_path) as opened:
        image = opened.convert("RGB")
    rgb = np.asarray(image, dtype=np.uint8)
    height, width = rgb.shape[:2]
    minimum = rgb.min(axis=2).astype(np.int16)
    spread = rgb.max(axis=2).astype(np.int16) - minimum

    # Start with light, near-neutral pixels. JPEG noise can turn parts of a
    # plain white backdrop into grey flecks, so close small holes in this mask
    # before finding the component that touches the image border.
    candidate = (minimum >= 198) & (spread <= 76)
    candidate_image = Image.fromarray(candidate.astype(np.uint8) * 255, mode="L")
    candidate_image = candidate_image.filter(ImageFilter.MaxFilter(13))
    candidate_image = candidate_image.filter(ImageFilter.MinFilter(13))

    # A one-pixel white frame connects every background region that touches
    # any side of the source image. Flood only that connected component; white
    # details enclosed by the illustrated character remain opaque.
    padded = Image.new("L", (width + 2, height + 2), 255)
    padded.paste(candidate_image, (1, 1))
    ImageDraw.floodfill(padded, (0, 0), 128, thresh=0)
    background = np.asarray(padded, dtype=np.uint8)[1:-1, 1:-1] == 128

    # Expand the backdrop mask by one pixel to remove the bright JPEG fringe
    # around outlines while preserving the line art itself.
    background_image = Image.fromarray(background.astype(np.uint8) * 255, mode="L")
    background_image = background_image.filter(ImageFilter.MaxFilter(3))
    alpha = 255 - np.asarray(background_image, dtype=np.uint8)

    plate = Image.fromarray(np.dstack((rgb, alpha)), mode="RGBA")
    foreground_box = plate.getchannel("A").getbbox()
    if foreground_box is None:
        raise ManualReviewRequired(
            f"Pose reference {source_path.name} became fully transparent after backdrop removal."
        )
    # Remove empty studio margins so the pose fills a useful portion of a
    # portrait Shorts frame. Retain enough padding to protect fingers and hair.
    x0, y0, x1, y1 = foreground_box
    padding = 28
    crop_box = (
        max(0, x0 - padding),
        max(0, y0 - padding),
        min(width, x1 + padding),
        min(height, y1 + padding),
    )
    plate = plate.crop(crop_box)
    destination.parent.mkdir(parents=True, exist_ok=True)
    plate.save(destination, format="PNG", optimize=True)


def create_character_bundle(
    source_path: str | Path,
    reference_dir: str | Path,
    output_dir: str | Path,
    *,
    character_id: str = "violin-prince",
    cache_dir: str | Path | None = None,
    hand_fraction: float = 0.72,
    max_local_inpaint_ratio: float = 0.025,
) -> dict[str, Any]:
    source_path = Path(source_path).resolve(strict=True)
    reference_dir = Path(reference_dir).resolve(strict=True)
    output_dir = Path(output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    if not source_path.is_file() or not reference_dir.is_dir():
        raise AutoRigError("The master image or character reference directory is missing.")

    with Image.open(source_path) as opened:
        image = opened.convert("RGB")
    body_parser, detail_parser = _download_parsers(cache_dir)
    body_labels, body_conf = body_parser.parse(image)
    detail_labels, detail_conf = detail_parser.parse(image)
    masks, repaired_torso, report, joints = separate_from_parsing(
        image, body_labels, body_conf, detail_labels, detail_conf,
        hand_fraction=hand_fraction,
        max_local_inpaint_ratio=max_local_inpaint_ratio,
    )

    layers = []
    ordered_roles = (
        "torso", "left_upper_arm", "right_upper_arm",
        "left_forearm", "right_forearm", "left_hand", "right_hand", "head", "face",
    )
    for role in ordered_roles:
        layer_source = repaired_torso if role == "torso" else image
        geometry = _save_layer(layer_source, masks[role], output_dir / f"{role}.png")
        joint_name = JOINT_FOR_ROLE.get(role)
        pivot_x = pivot_y = 0.5
        if joint_name:
            joint = joints[joint_name]
            px, py = joint["x"] * (image.width - 1), joint["y"] * (image.height - 1)
            pivot_x = min(1.0, max(0.0, (px - geometry["x"]) / geometry["width"]))
            pivot_y = min(1.0, max(0.0, (py - geometry["y"]) / geometry["height"]))
        layers.append({
            "id": role, "role": role, **geometry,
            "pivot_x": round(pivot_x, 6), "pivot_y": round(pivot_y, 6),
            "z_index": ROLE_Z[role],
        })

    face_layer = next(item for item in layers if item["role"] == "face")
    expression_paths = {
        name: reference_dir / filename
        for name, filename in EXPRESSION_FILES.items()
        if (reference_dir / filename).is_file()
    }
    if "neutral" not in expression_paths:
        raise AutoRigError("face-neutral.jpg is required in the reference directory.")
    expressions = {}
    face_x, face_y = int(face_layer["x"]), int(face_layer["y"])
    face_width, face_height = int(face_layer["width"]), int(face_layer["height"])
    face_alpha = masks["face"][
        face_y:face_y + face_height,
        face_x:face_x + face_width,
    ]
    for name, path in expression_paths.items():
        plate_name = f"expression-{name}.png"
        destination = output_dir / plate_name
        if name == "neutral":
            # The neutral plate must be pixel-identical to the extracted
            # master face. Re-cropping another portrait introduces drift.
            shutil.copy2(output_dir / "face.png", destination)
        else:
            _face_plate(
                path,
                (face_width, face_height),
                destination,
                alpha_mask=face_alpha,
            )
        expressions[name] = {"src": plate_name}

    reference_poses = {
        name: filename for name, filename in POSE_FILES.items()
        if (reference_dir / filename).is_file()
    }
    pose_assets = {}
    for name, filename in reference_poses.items():
        plate_name = f"pose-{name}.png"
        _save_pose_plate(reference_dir / filename, output_dir / plate_name)
        pose_assets[name] = {"src": plate_name}
    character = {
        "id": character_id,
        "name": "Violin Prince presenter",
        "canvas": {"width": image.width, "height": image.height},
        "layers": layers,
        "joints": joints,
        "expressions": expressions,
        "poses": {},
        "gestures": {},
        "scene_actions": {},
        "reference_poses": reference_poses,
        "pose_assets": pose_assets,
    }
    (output_dir / "character.json").write_text(
        json.dumps(character, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    _save_mask_preview(image, masks, output_dir / "separation-preview.png")
    report.update({
        "character_id": character_id,
        "status": "candidate_ready_for_visual_review",
        "layer_count": len(layers),
        "expression_count": len(expressions),
        "pose_reference_count": len(reference_poses),
        "pose_asset_count": len(pose_assets),
        "joint_count": len(joints),
    })
    (output_dir / "separation-report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"character": character, "report": report, "output_dir": str(output_dir)}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Separate one master character image into transparent 2D rig layers."
    )
    parser.add_argument("--source", required=True, help="Master character image.")
    parser.add_argument("--reference-dir", required=True, help="Expression and pose reference folder.")
    parser.add_argument("--output", required=True, help="Candidate rig bundle output directory.")
    parser.add_argument("--id", default="violin-prince")
    parser.add_argument("--cache-dir", default=None)
    parser.add_argument("--hand-fraction", type=float, default=0.72)
    parser.add_argument("--max-local-inpaint-ratio", type=float, default=0.025)
    args = parser.parse_args()
    try:
        result = create_character_bundle(
            args.source, args.reference_dir, args.output,
            character_id=args.id, cache_dir=args.cache_dir,
            hand_fraction=args.hand_fraction,
            max_local_inpaint_ratio=args.max_local_inpaint_ratio,
        )
    except Exception as exc:
        print("CHARACTER_AUTO_RIG_FAILED=" + str(exc)[:1500], file=sys.stderr)
        return 1
    report = result["report"]
    print("CHARACTER_AUTO_RIG_RESULT=" + json.dumps({
        "status": report["status"],
        "bundle": result["output_dir"],
        "layers": report["layer_count"],
        "expressions": report["expression_count"],
        "joints": report["joint_count"],
        "review_required": report["needs_visual_review"],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
