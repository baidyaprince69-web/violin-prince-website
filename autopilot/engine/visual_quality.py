"""Deterministic visual-consistency checks for Violin Prince scene assets.

This gate validates the rendered artwork package before Motion/HyperFrames.
It does not claim to judge artistic taste or inspect animation that has not
been rendered. Typography remains a separate overlay, never baked into plates.
"""
from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from PIL import Image

from local_vector_illustrator import (
    HEIGHT,
    INSTRUMENT_SPEC,
    MODES,
    RENDERER_VERSION,
    VISUAL_STYLE_BIBLE,
    WIDTH,
)

QUALITY_GATE_VERSION = "violin-prince-visual-quality-v1"
TARGET_ASPECT_RATIO = 9 / 16
MAX_ASPECT_ERROR = 0.02
MIN_WIDTH = 720
MIN_HEIGHT = 1280


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_visual_quality_report(
    scenes: list[dict[str, Any]],
    image_paths: list[str | Path],
    *,
    story_profile: str = "",
) -> dict[str, Any]:
    """Validate portrait framing, readable asset files, scene variety and uniqueness.

    The function is intentionally deterministic and network-free. It checks
    objective delivery requirements and reports the approved style contract;
    it does not claim that automated checks replace a human visual review.
    """
    errors: list[str] = []
    checks: list[dict[str, Any]] = []
    scene_records: list[dict[str, Any]] = []

    def record(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})
        if not passed:
            errors.append(f"{name}: {detail}")

    scene_list = scenes if isinstance(scenes, list) else []
    paths = [Path(item) for item in image_paths]
    record(
        "scene_count",
        2 <= len(scene_list) <= 4 and len(paths) == len(scene_list),
        f"received {len(scene_list)} scene(s) and {len(paths)} image asset(s); expected 2-4 matched pairs",
    )

    seen_hashes: dict[str, str] = {}
    visual_modes: list[str] = []
    for index, (scene, path) in enumerate(zip(scene_list, paths), start=1):
        if not isinstance(scene, dict):
            record(f"scene_{index}_contract", False, "scene entry is not an object")
            continue

        scene_id = str(scene.get("id") or f"scene-{index}")
        mode = str(scene.get("visual_mode") or "").strip().casefold()
        visual_modes.append(mode)
        record(
            f"scene_{index}_mode",
            mode in MODES,
            f"{scene_id} uses {mode or '[missing]'}",
        )
        record(
            f"scene_{index}_asset_exists",
            path.is_file(),
            f"{scene_id}: {path.name}",
        )
        if not path.is_file():
            continue

        try:
            with Image.open(path) as image:
                image.verify()
            with Image.open(path) as image:
                width, height = image.size
                image_format = str(image.format or "").upper()
                aspect_ratio = width / max(1, height)
        except Exception as exc:
            record(f"scene_{index}_image_readable", False, f"{scene_id}: {type(exc).__name__}")
            continue

        readable = image_format in {"JPEG", "PNG", "WEBP"}
        record(
            f"scene_{index}_image_readable",
            readable,
            f"{scene_id}: {image_format or '[unknown format]'}",
        )

        dimensions_ok = width >= MIN_WIDTH and height >= MIN_HEIGHT
        record(
            f"scene_{index}_portrait_dimensions",
            dimensions_ok,
            f"{scene_id}: {width}x{height}; minimum {MIN_WIDTH}x{MIN_HEIGHT}",
        )

        aspect_error = abs(aspect_ratio - TARGET_ASPECT_RATIO) / TARGET_ASPECT_RATIO
        framing_ok = aspect_error <= MAX_ASPECT_ERROR
        record(
            f"scene_{index}_portrait_framing",
            framing_ok,
            f"{scene_id}: ratio {aspect_ratio:.5f}; relative error {aspect_error:.2%}",
        )

        digest = _sha256(path)
        previous = seen_hashes.get(digest)
        unique = previous is None
        record(
            f"scene_{index}_unique_artwork",
            unique,
            f"{scene_id}: " + ("unique image content" if unique else f"duplicates {previous}"),
        )
        if previous is None:
            seen_hashes[digest] = scene_id

        caption = " ".join(str(scene.get("caption") or "").split())
        caption_safe = bool(caption) and "\ufffd" not in caption and "\x00" not in caption
        record(
            f"scene_{index}_caption",
            caption_safe,
            f"{scene_id}: separate overlay caption is {'present' if caption_safe else 'missing or malformed'}",
        )

        scene_records.append({
            "scene_id": scene_id,
            "visual_mode": mode,
            "caption": caption,
            "asset": path.name,
            "sha256": digest,
            "width": width,
            "height": height,
            "format": image_format,
            "file_size_bytes": path.stat().st_size,
            "aspect_ratio": round(aspect_ratio, 6),
        })

    distinct_modes = sorted(set(mode for mode in visual_modes if mode))
    record(
        "scene_variety",
        len(distinct_modes) >= 2,
        "distinct visual modes: " + (", ".join(distinct_modes) or "[none]"),
    )
    final_mode = visual_modes[-1] if visual_modes else ""
    record(
        "performance_payoff",
        final_mode == "cover_performance",
        f"final scene mode is {final_mode or '[missing]'}; expected cover_performance",
    )

    return {
        "schema_version": 1,
        "gate": QUALITY_GATE_VERSION,
        "status": "passed" if not errors else "failed",
        "passed": not errors,
        "story_profile": str(story_profile or ""),
        "renderer": RENDERER_VERSION,
        "canvas": {"width": WIDTH, "height": HEIGHT, "target_ratio": "9:16"},
        "visual_style_bible": dict(VISUAL_STYLE_BIBLE),
        "instrument_specification": dict(INSTRUMENT_SPEC),
        "typography_policy": "captions and labels are rendered as separate overlays, not baked into illustration assets",
        "metrics": {
            "scene_count": len(scene_list),
            "distinct_visual_modes": distinct_modes,
            "unique_artwork_count": len(seen_hashes),
            "checks_passed": sum(1 for item in checks if item["passed"]),
            "checks_total": len(checks),
        },
        "scenes": scene_records,
        "checks": checks,
        "errors": errors,
        "human_review_required": True,
        "human_review_note": "Automated checks verify asset integrity and consistency contracts, not artistic quality or factual correctness.",
    }
