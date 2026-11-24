"""Generate dense, non-destructive temporal QA evidence for a rendered performance.

This checks sample coverage, frame integrity, and visible frame-to-frame variation.
It does not certify anatomy, joint alignment, occlusion, or character-art quality.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path
from statistics import median
from typing import Any, Sequence

from PIL import Image, ImageChops, ImageDraw, ImageStat


def analyse_sampled_frames(images: Sequence[Image.Image], fps: float) -> dict[str, Any]:
    """Return integrity and temporal-variation metrics for sampled RGB frames."""
    if fps <= 0:
        raise ValueError("Sampling FPS must be positive.")
    if len(images) < 2:
        raise ValueError("Pose-range QA requires at least two sampled frames.")

    sizes = {image.size for image in images}
    if len(sizes) != 1:
        raise ValueError(f"Sampled frame dimensions differ: {sorted(sizes)}")

    metrics: list[dict[str, Any]] = []
    digests: list[str] = []
    adjacent_differences: list[float] = []

    previous: Image.Image | None = None
    for index, image in enumerate(images):
        rgb = image.convert("RGB")
        luminance = rgb.convert("L")
        luminance_stats = ImageStat.Stat(luminance)
        mean_luminance = float(luminance_stats.mean[0])
        luminance_stddev = float(luminance_stats.stddev[0])
        if mean_luminance < 4.0 or luminance_stddev < 2.0:
            raise ValueError(
                f"Sample {index} appears blank or near-uniform "
                f"(mean_luminance={mean_luminance:.2f}, "
                f"stddev={luminance_stddev:.2f})."
            )

        digest = hashlib.sha256(rgb.tobytes()).hexdigest()
        digests.append(digest)
        metrics.append({
            "frame_index": index,
            "time_seconds": round(index / fps, 3),
            "mean_luminance": round(mean_luminance, 3),
            "luminance_stddev": round(luminance_stddev, 3),
            "sha256": digest,
        })

        if previous is not None:
            difference = ImageChops.difference(previous, rgb)
            channel_means = ImageStat.Stat(difference).mean
            adjacent_differences.append(
                float(sum(channel_means) / len(channel_means))
            )
        previous = rgb

    unique_frame_count = len(set(digests))
    if unique_frame_count < 2:
        raise ValueError(
            "All sampled frames are identical; no temporal variation was detected."
        )

    median_adjacent_difference = median(adjacent_differences)
    opening_interval_difference = adjacent_differences[0]
    opening_transition_threshold = max(5.0, median_adjacent_difference * 2.0)
    opening_interval_review = (
        opening_interval_difference > opening_transition_threshold
    )
    review_flags: list[str] = []
    if opening_interval_review:
        review_flags.append(
            "The opening 0.25-second interval changes substantially more than "
            "the typical adjacent interval; visually confirm whether performer "
            "visibility is intentionally delayed."
        )

    return {
        "status": "passed",
        "verification_scope": (
            "dense_temporal_sample_coverage_nonblank_frame_integrity_"
            "and_frame_to_frame_variation"
        ),
        "sample_count": len(images),
        "sample_interval_seconds": round(1.0 / fps, 4),
        "sample_fps": fps,
        "frame_width": next(iter(sizes))[0],
        "frame_height": next(iter(sizes))[1],
        "unique_frame_count": unique_frame_count,
        "nonblank_frame_count": len(metrics),
        "mean_adjacent_frame_difference": round(
            sum(adjacent_differences) / len(adjacent_differences), 4
        ),
        "median_adjacent_frame_difference": round(median_adjacent_difference, 4),
        "opening_interval_mean_difference": round(opening_interval_difference, 4),
        "opening_transition_threshold": round(opening_transition_threshold, 4),
        "opening_interval_review": "flagged" if opening_interval_review else "clear",
        "review_flags": review_flags,
        "frames": metrics,
        "limitations": [
            "This report does not assess anatomical joint alignment.",
            "This report does not prove that no limb, prop, or character detail is occluded.",
            "Artist review of the dense contact sheet and rendered video remains required.",
        ],
    }


def create_contact_sheet(
    images: Sequence[Image.Image],
    output_path: Path,
    *,
    fps: float,
    columns: int = 5,
    thumb_width: int = 180,
    thumb_height: int = 320,
) -> None:
    """Build a labelled contact sheet from the sampled performance frames."""
    if columns < 1 or thumb_width < 1 or thumb_height < 1:
        raise ValueError("Contact-sheet dimensions must be positive.")

    cell_height = thumb_height + 30
    rows = (len(images) + columns - 1) // columns
    title_height = 34
    canvas = Image.new(
        "RGB",
        (columns * thumb_width, title_height + rows * cell_height),
        (12, 18, 28),
    )
    draw = ImageDraw.Draw(canvas)
    draw.text(
        (10, 10),
        f"FULL-BODY POSE RANGE  |  {fps:g} FPS  |  {len(images)} SAMPLES",
        fill=(240, 230, 210),
    )

    for index, frame in enumerate(images):
        thumb = frame.convert("RGB")
        thumb.thumbnail((thumb_width, thumb_height), Image.Resampling.LANCZOS)
        column = index % columns
        row = index // columns
        x = column * thumb_width + (thumb_width - thumb.width) // 2
        y = title_height + row * cell_height + 24
        canvas.paste(thumb, (x, y))
        draw.text(
            (column * thumb_width + 7, title_height + row * cell_height + 5),
            f"{index / fps:05.2f}s",
            fill=(240, 230, 210),
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output_path, format="JPEG", quality=93, optimize=True)


def generate_pose_range_qa(
    video_path: Path,
    output_dir: Path,
    *,
    duration: float = 8.0,
    fps: float = 4.0,
    columns: int = 5,
) -> dict[str, Any]:
    """Sample a rendered MP4 at fixed intervals and save QA evidence."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("ffmpeg is required to sample the rendered preview.")
    if not video_path.is_file():
        raise FileNotFoundError(f"Preview video not found: {video_path}")
    if duration <= 0 or fps <= 0:
        raise ValueError("Duration and sampling FPS must be positive.")

    expected_count_float = duration * fps
    expected_count = round(expected_count_float)
    if abs(expected_count_float - expected_count) > 1e-6 or expected_count < 2:
        raise ValueError("Duration multiplied by FPS must produce at least two whole samples.")

    frames_dir = output_dir / "frames"
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old_frame in frames_dir.glob("frame-*.png"):
        old_frame.unlink()

    pattern = frames_dir / "frame-%03d.png"
    command = [
        ffmpeg,
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-i", str(video_path),
        "-vf", f"fps={fps}:start_time=0:round=near",
        "-frames:v", str(expected_count),
        str(pattern),
    ]
    completed = subprocess.run(
        command, check=False, capture_output=True, text=True
    )
    if completed.returncode != 0:
        raise RuntimeError(
            "ffmpeg frame sampling failed: "
            + (completed.stderr.strip() or f"exit code {completed.returncode}")
        )

    frame_paths = sorted(frames_dir.glob("frame-*.png"))
    if len(frame_paths) != expected_count:
        raise RuntimeError(
            f"Expected {expected_count} sampled frames, found {len(frame_paths)}."
        )

    images = [Image.open(path).convert("RGB") for path in frame_paths]
    report = analyse_sampled_frames(images, fps)
    report.update({
        "video": str(video_path),
        "duration_seconds": duration,
        "expected_sample_count": expected_count,
        "contact_sheet": "full-body-pose-range-contact-sheet.jpg",
    })

    create_contact_sheet(
        images,
        output_dir / "full-body-pose-range-contact-sheet.jpg",
        fps=fps,
        columns=columns,
    )
    (output_dir / "pose-range-visual-qa.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    for image in images:
        image.close()
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--video", required=True, type=Path)
    parser.add_argument("--out-dir", required=True, type=Path)
    parser.add_argument("--duration", type=float, default=8.0)
    parser.add_argument("--fps", type=float, default=4.0)
    parser.add_argument("--columns", type=int, default=5)
    args = parser.parse_args()

    report = generate_pose_range_qa(
        args.video,
        args.out_dir,
        duration=args.duration,
        fps=args.fps,
        columns=args.columns,
    )
    print(json.dumps({
        "status": report["status"],
        "sample_count": report["sample_count"],
        "unique_frame_count": report["unique_frame_count"],
        "contact_sheet": report["contact_sheet"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
