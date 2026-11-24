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


def _nearest_parent_child_pixels(
    parent_mask: np.ndarray,
    child_mask: np.ndarray,
    *,
    offset_x: int,
    offset_y: int,
) -> tuple[float | None, list[int] | None, list[int] | None]:
    """Return exact nearest pixel coordinates for two local boolean masks."""
    parent_points = np.argwhere(np.asarray(parent_mask, dtype=bool))
    child_points = np.argwhere(np.asarray(child_mask, dtype=bool))
    if not len(parent_points) or not len(child_points):
        return None, None, None

    # The joint crops are small. Chunking keeps the exact pairwise distance
    # calculation bounded without adding a SciPy dependency to the rig tools.
    child_points_f = child_points.astype(np.float32)
    best_distance_sq = float("inf")
    best_parent: np.ndarray | None = None
    best_child: np.ndarray | None = None
    for start in range(0, len(parent_points), 256):
        parent_chunk = parent_points[start:start + 256].astype(np.float32)
        delta = parent_chunk[:, None, :] - child_points_f[None, :, :]
        distances_sq = np.einsum("ijk,ijk->ij", delta, delta)
        flat_index = int(np.argmin(distances_sq))
        row_index, child_index = np.unravel_index(flat_index, distances_sq.shape)
        distance_sq = float(distances_sq[row_index, child_index])
        if distance_sq < best_distance_sq:
            best_distance_sq = distance_sq
            best_parent = parent_points[start + row_index]
            best_child = child_points[child_index]

    assert best_parent is not None and best_child is not None
    parent_xy = [int(offset_x + best_parent[1]), int(offset_y + best_parent[0])]
    child_xy = [int(offset_x + best_child[1]), int(offset_y + best_child[0])]
    return round(float(np.sqrt(best_distance_sq)), 3), parent_xy, child_xy


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
            "candidate_source_polygon outlines only the exact shared parent/child alpha pixels; it is overlap evidence, not a complete joint surface.",
            "Magenta contours in the contact sheet indicate shared-pixel evidence only; they are never production art.",
            "Yellow points and lines identify the nearest separate parent/child source pixels where no shared pixels exist.",
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
    label_height = 58
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

        source_visible = source_pixels[:, :, 3] > 12
        shared_source = parent_mask & child_mask & source_visible
        shared_local = shared_source[y0:y1, x0:x1].astype(np.uint8)
        component_count, component_labels, component_stats, component_centroids = (
            cv2.connectedComponentsWithStats(shared_local, connectivity=8)
        )
        candidate_source_polygon: list[list[float]] = []
        candidate_source_pixels = 0
        candidate_status = "manual_seam_trace_required_no_shared_parent_child_pixels"
        if component_count > 1:
            candidate_labels = range(1, component_count)
            selected_label = max(
                candidate_labels,
                key=lambda label: int(component_stats[label, cv2.CC_STAT_AREA]),
            )
            selected = (component_labels == selected_label).astype(np.uint8)
            candidate_source_pixels = int(selected.sum())
            contours, _ = cv2.findContours(
                selected, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
            )
            if contours:
                contour = max(contours, key=cv2.contourArea)
                polygon = cv2.approxPolyDP(contour, 0.75, True).reshape(-1, 2)
                candidate_source_polygon = [
                    [round(float(point[0]) + x0, 3), round(float(point[1]) + y0, 3)]
                    for point in polygon
                ]
                if len(candidate_source_polygon) >= 3:
                    candidate_status = "shared_source_pixel_polygon_candidate_pending_artist_review"
                else:
                    candidate_source_polygon = []

        anchor_measure_radius_px = min(24, crop_radius)
        ax0, ay0 = max(0, cx - anchor_measure_radius_px), max(0, cy - anchor_measure_radius_px)
        ax1, ay1 = min(canvas_width, cx + anchor_measure_radius_px), min(canvas_height, cy + anchor_measure_radius_px)
        local_parent = parent_mask[ay0:ay1, ax0:ax1]
        local_child = child_mask[ay0:ay1, ax0:ax1]
        parent_pixels_near_anchor = int(local_parent.sum())
        child_pixels_near_anchor = int(local_child.sum())
        local_parent_child_gap_px, closest_parent_source_pixel, closest_child_source_pixel = (
            _nearest_parent_child_pixels(
                local_parent, local_child, offset_x=ax0, offset_y=ay0
            )
        )
        manual_trace_reason = None
        if not candidate_source_polygon:
            if not parent_pixels_near_anchor:
                manual_trace_reason = "parent_source_pixels_absent_near_anchor"
            elif not child_pixels_near_anchor:
                manual_trace_reason = "child_source_pixels_absent_near_anchor"
            else:
                manual_trace_reason = "source_layers_separated_near_anchor"
        if candidate_source_polygon:
            candidate_status = "source_alpha_overlap_evidence_only_not_full_joint_surface"
        crop = source.crop((x0, y0, x1, y1))
        matte = Image.new("RGBA", crop.size, (25, 31, 42, 255))
        matte.alpha_composite(crop)
        magnified = matte.resize(
            (crop.width * scale, crop.height * scale),
            Image.Resampling.NEAREST,
        )
        overlay = ImageDraw.Draw(magnified, "RGBA")

        if candidate_source_polygon:
            proposal_points = [
                (
                    int(round((point[0] - x0) * scale)),
                    int(round((point[1] - y0) * scale)),
                )
                for point in candidate_source_polygon
            ]
            if len(proposal_points) >= 3:
                overlay.line(
                    proposal_points + [proposal_points[0]],
                    fill=(255, 55, 225, 255),
                    width=3,
                )

        if (
            not candidate_source_polygon
            and closest_parent_source_pixel
            and closest_child_source_pixel
        ):
            parent_point = (
                int(round((closest_parent_source_pixel[0] - x0) * scale)),
                int(round((closest_parent_source_pixel[1] - y0) * scale)),
            )
            child_point = (
                int(round((closest_child_source_pixel[0] - x0) * scale)),
                int(round((closest_child_source_pixel[1] - y0) * scale)),
            )
            overlay.line(
                [parent_point, child_point],
                fill=(255, 220, 80, 255),
                width=2,
            )
            for point in (parent_point, child_point):
                overlay.ellipse(
                    (point[0] - 5, point[1] - 5, point[0] + 5, point[1] + 5),
                    fill=(255, 220, 80, 255),
                )

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
        status_label = (
            f"shared pixels: {candidate_source_pixels} | magenta = overlap evidence only"
            if candidate_source_polygon
            else (
                f"0 shared | edge gap: {local_parent_child_gap_px}px | manual trace"
                if local_parent_child_gap_px is not None
                else f"0 shared | {manual_trace_reason.replace('_', ' ')}"
            )
        )
        draw.text(
            (px + 10, py + 41),
            status_label,
            fill=(255, 145, 225) if candidate_source_polygon else (255, 205, 125),
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
            "candidate_source_polygon": candidate_source_polygon,
            "candidate_source_pixels": candidate_source_pixels,
            "candidate_status": candidate_status,
            "candidate_parent_child_gap_px": local_parent_child_gap_px,
            "anchor_measure_radius_px": anchor_measure_radius_px,
            "parent_pixels_near_anchor": parent_pixels_near_anchor,
            "child_pixels_near_anchor": child_pixels_near_anchor,
            "manual_trace_reason": manual_trace_reason,
            "closest_parent_source_pixel": closest_parent_source_pixel,
            "closest_child_source_pixel": closest_child_source_pixel,
            "candidate_geometry_kind": "shared_alpha_overlap_evidence_only_not_full_joint_surface",
            "candidate_is_production_art": False,
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
            "shared_source_pixels": candidate_source_pixels,
            "candidate_status": candidate_status,
            "candidate_source_polygon": candidate_source_polygon,
            "candidate_parent_child_gap_px": local_parent_child_gap_px,
            "anchor_measure_radius_px": anchor_measure_radius_px,
            "parent_pixels_near_anchor": parent_pixels_near_anchor,
            "child_pixels_near_anchor": child_pixels_near_anchor,
            "manual_trace_reason": manual_trace_reason,
            "closest_parent_source_pixel": closest_parent_source_pixel,
            "closest_child_source_pixel": closest_child_source_pixel,
            "candidate_geometry_kind": "shared_alpha_overlap_evidence_only_not_full_joint_surface",
            "candidate_is_production_art": False,
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
        "candidate_joint_polygons": sum(bool(row["candidate_source_polygon"]) for row in review_rows),
        "manual_seam_trace_required": sum(not bool(row["candidate_source_polygon"]) for row in review_rows),
        "candidate_geometry_source": "exact_parent_child_source_alpha_intersection_only",
        "candidate_geometry_kind": "shared_alpha_overlap_evidence_only_not_full_joint_surface",
        "candidate_polygons_artist_approved": 0,
        "rig_layers_modified": 0,
        "original_source_pixels_modified": 0,
        "upper_body_and_hand_assets_touched": False,
        "joints": review_rows,
        "limitation": (
            "Magenta outlines show exact shared parent/child source-alpha overlap only, not complete joint surfaces. "
            "They are draft tracing evidence, not approved artwork, and are never copied into artist_source_polygon automatically. "
            "Yellow markers show nearest separate parent/child source pixels where a manual seam trace is required. "
            "The rig must continue deferring joint surfaces until reviewed artist_source_polygon masks are supplied."
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
        "candidate_joint_polygons": report["candidate_joint_polygons"],
        "manual_seam_trace_required": report["manual_seam_trace_required"],
        "candidate_polygons_artist_approved": report["candidate_polygons_artist_approved"],
        "contact_sheet": report["contact_sheet"],
        "template": report["template"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
