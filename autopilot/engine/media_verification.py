"""Deterministic media checks for source assets, timelines, captions, and final MP4s."""
from __future__ import annotations

import hashlib
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_image_asset(
    path: str | Path,
    *,
    minimum_width: int = 512,
    minimum_height: int = 512,
    expected_size: tuple[int, int] | None = None,
) -> dict[str, Any]:
    target = Path(path)
    errors: list[str] = []
    warnings: list[str] = []
    if not target.is_file():
        return {"status": "failed", "path": str(target), "errors": ["file_missing"], "warnings": []}
    try:
        with Image.open(target) as opened:
            opened.verify()
        with Image.open(target) as opened:
            image = opened.convert("RGBA")
            width, height = image.size
            alpha = np.asarray(image.getchannel("A"), dtype=np.uint8)
            rgb = np.asarray(image.convert("RGB").resize((64, 64)), dtype=np.uint8)
            alpha_ratio = float(np.count_nonzero(alpha)) / float(alpha.size)
            variance = float(np.var(rgb.astype(np.float32)))
            bbox = image.getchannel("A").getbbox()
            image_format = str(opened.format or target.suffix.lstrip(".")).upper()
        if width < minimum_width or height < minimum_height:
            errors.append("dimensions_below_minimum")
        if expected_size and (width, height) != tuple(expected_size):
            errors.append("dimensions_do_not_match_character_spec")
        if bbox is None or alpha_ratio <= 0:
            errors.append("image_has_no_visible_pixels")
        if variance < 2.0:
            warnings.append("image_has_very_low_visual_variance")
        if alpha_ratio < 0.01:
            warnings.append("image_is_more_than_99_percent_transparent")
        if image_format not in {"PNG", "JPEG", "WEBP"}:
            warnings.append("unusual_image_format")
        return {
            "status": "failed" if errors else "passed",
            "path": str(target),
            "sha256": _sha256(target),
            "width": width,
            "height": height,
            "format": image_format,
            "alpha_coverage": round(alpha_ratio, 6),
            "visual_variance": round(variance, 4),
            "errors": errors,
            "warnings": warnings,
        }
    except Exception as exc:
        return {"status": "failed", "path": str(target), "errors": [f"image_decode_failed:{type(exc).__name__}"], "warnings": []}


def verify_scene_assets(
    scenes: list[dict[str, Any]],
    image_paths: list[str | Path],
    *,
    total_seconds: float,
    narration_info: dict[str, Any] | None = None,
    expected_narration_script: str | None = None,
) -> dict[str, Any]:
    errors: list[str] = []
    warnings: list[str] = []
    if len(scenes) != len(image_paths) or not scenes:
        errors.append("scene_asset_count_mismatch")
    identifiers = [str(scene.get("id") or "") for scene in scenes]
    if any(not value for value in identifiers) or len(identifiers) != len(set(identifiers)):
        errors.append("scene_ids_missing_or_duplicate")
    assets = [verify_image_asset(path) for path in image_paths]
    if any(asset["status"] != "passed" for asset in assets):
        errors.append("one_or_more_scene_images_failed_asset_validation")
    digests = [asset.get("sha256") for asset in assets if asset.get("sha256")]
    duplicate_digests = sorted({value for value in digests if digests.count(value) > 1})
    if duplicate_digests:
        warnings.append("duplicate_scene_image_content")
    cues = (narration_info or {}).get("word_cues") or (narration_info or {}).get("subtitle_cues") or []
    scene_sentence_map: dict[int, str] = {}
    for scene in scenes:
        values = scene.get("narration_sentence_indexes") or []
        for sentence_index in values:
            if isinstance(sentence_index, bool) or not isinstance(sentence_index, int):
                errors.append("invalid_scene_narration_sentence_mapping")
                continue
            if sentence_index in scene_sentence_map:
                errors.append("narration_sentence_assigned_to_multiple_scenes")
            scene_sentence_map[sentence_index] = str(scene.get("id") or "")
    if cues:
        previous_start = -1.0
        cue_words = []
        for index, cue in enumerate(cues):
            try:
                start, end = float(cue["start"]), float(cue["end"])
                if start < 0 or end <= start or end > float(total_seconds) + 0.25:
                    errors.append(f"invalid_narration_cue_{index}")
                if start < previous_start:
                    errors.append("narration_cues_not_monotonic")
                previous_start = start
                text_value = str(cue.get("text") or "")
                cue_words.extend(re.findall(r"[\w’'-]+", text_value.casefold()))
                sentence_index = cue.get("sentence_index")
                if sentence_index is not None:
                    if isinstance(sentence_index, bool) or not isinstance(sentence_index, int):
                        errors.append(f"invalid_narration_sentence_index_{index}")
                    elif sentence_index not in scene_sentence_map:
                        errors.append(f"unmapped_narration_sentence_{sentence_index}")
            except (KeyError, TypeError, ValueError):
                errors.append(f"invalid_narration_cue_{index}")
        if expected_narration_script:
            expected_words = re.findall(
                r"[\w’'-]+", str(expected_narration_script).casefold()
            )
            if cue_words != expected_words:
                errors.append("word_cues_do_not_match_approved_narration_script")
    elif narration_info is not None:
        warnings.append("no_timestamped_narration_cues_for_independent_check")
    return {
        "status": "failed" if errors else ("warning" if warnings else "passed"),
        "scene_count": len(scenes),
        "asset_count": len(assets),
        "assets": assets,
        "duplicate_sha256": duplicate_digests,
        "narration_cue_count": len(cues) if isinstance(cues, list) else 0,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
    }


def verify_audio_samples(samples: np.ndarray, sample_rate: int) -> dict[str, Any]:
    audio = np.asarray(samples, dtype=np.float32)
    if audio.ndim == 1:
        audio = audio[:, None]
    errors: list[str] = []
    warnings: list[str] = []
    if audio.size == 0 or sample_rate <= 0:
        return {"status": "failed", "errors": ["audio_empty_or_invalid_sample_rate"], "warnings": []}
    if not np.isfinite(audio).all():
        errors.append("audio_contains_non_finite_samples")
    peak = float(np.max(np.abs(audio))) if audio.size else 0.0
    rms = float(np.sqrt(np.mean(np.square(audio)))) if audio.size else 0.0
    clipping_ratio = float(np.mean(np.abs(audio) >= 0.999))
    if peak < 1e-5 or rms < 1e-5:
        errors.append("audio_is_silent")
    if clipping_ratio > 0.001:
        warnings.append("audio_has_clipping_samples")
    # Approximate true peak by 4x linear interpolation, clearly labelled as such.
    if audio.shape[0] > 1:
        oversampled = np.vstack([
            audio[:-1],
            audio[:-1] * 0.75 + audio[1:] * 0.25,
            audio[:-1] * 0.50 + audio[1:] * 0.50,
            audio[:-1] * 0.25 + audio[1:] * 0.75,
        ])
        true_peak = float(np.max(np.abs(oversampled)))
    else:
        true_peak = peak
    if true_peak > 1.05:
        warnings.append("estimated_true_peak_exceeds_0_dbfs")
    return {
        "status": "failed" if errors else ("warning" if warnings else "passed"),
        "sample_rate": int(sample_rate),
        "channels": int(audio.shape[1]),
        "duration_seconds": round(audio.shape[0] / float(sample_rate), 4),
        "sample_peak": round(peak, 6),
        "estimated_true_peak_4x": round(true_peak, 6),
        "rms": round(rms, 6),
        "rms_dbfs": round(20 * math.log10(max(rms, 1e-12)), 2),
        "clipping_ratio": round(clipping_ratio, 8),
        "errors": errors,
        "warnings": warnings,
    }


def verify_final_video(
    path: str | Path,
    *,
    expected_width: int = 720,
    expected_height: int = 1280,
    expected_fps: float = 25.0,
    minimum_duration: float = 20.0,
    maximum_duration: float = 25.0,
) -> dict[str, Any]:
    target = Path(path)
    errors: list[str] = []
    warnings: list[str] = []
    if not target.is_file() or target.stat().st_size < 4096:
        return {"status": "failed", "errors": ["final_video_missing_or_too_small"], "warnings": []}
    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries",
         "format=duration:stream=codec_type,width,height,codec_name,sample_rate,r_frame_rate",
         "-of", "json", str(target)],
        capture_output=True, text=True, timeout=90,
    )
    if probe.returncode:
        return {"status": "failed", "errors": ["ffprobe_failed"], "warnings": [], "stderr": probe.stderr[-500:]}
    try:
        data = json.loads(probe.stdout)
        duration = float(data.get("format", {}).get("duration", 0))
        streams = data.get("streams", [])
        video = next(item for item in streams if item.get("codec_type") == "video")
        audio = next(item for item in streams if item.get("codec_type") == "audio")
    except (ValueError, TypeError, StopIteration, KeyError):
        return {"status": "failed", "errors": ["video_or_audio_stream_missing"], "warnings": []}
    if (int(video.get("width", 0)), int(video.get("height", 0))) != (expected_width, expected_height):
        errors.append("unexpected_video_dimensions")
    if not minimum_duration <= duration <= maximum_duration:
        errors.append("duration_outside_production_window")
    if str(video.get("codec_name") or "") != "h264":
        errors.append("video_codec_is_not_h264")
    try:
        numerator, denominator = str(video.get("r_frame_rate", "0/1")).split("/", 1)
        fps = float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    if abs(fps - float(expected_fps)) > 0.5:
        errors.append("unexpected_frame_rate")
    if int(audio.get("sample_rate", 0)) < 22050:
        errors.append("audio_sample_rate_below_minimum")

    decoded_audio = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(target), "-vn", "-ac", "2", "-ar", "22050", "-f", "f32le", "pipe:1"],
        capture_output=True, timeout=120,
    )
    audio_report = {}
    if decoded_audio.returncode or not decoded_audio.stdout:
        errors.append("final_audio_decode_failed")
    else:
        samples = np.frombuffer(decoded_audio.stdout, dtype="<f4").copy()
        audio_report = verify_audio_samples(samples.reshape(-1, 2), 22050)
        if audio_report.get("status") == "failed":
            errors.extend(audio_report.get("errors", []))
        warnings.extend(audio_report.get("warnings", []))

    # Black/frozen intervals are diagnostic only: deliberately held title cards
    # and illustrated scenes can be static by design, so these never fail a render.
    diagnostics = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(target), "-vf",
         "blackdetect=d=0.5:pix_th=0.02,freezedetect=n=-50dB:d=1.0",
         "-an", "-f", "null", "-"],
        capture_output=True, text=True, timeout=150,
    )
    black_events = diagnostics.stderr.count("black_start:")
    freeze_events = diagnostics.stderr.count("freeze_start:")
    if black_events:
        warnings.append("black_frame_intervals_detected")
    if freeze_events:
        warnings.append("frozen_frame_intervals_detected")
    return {
        "status": "failed" if errors else ("warning" if warnings else "passed"),
        "duration_seconds": round(duration, 3),
        "width": int(video.get("width", 0)),
        "height": int(video.get("height", 0)),
        "fps": round(fps, 3),
        "video_codec": str(video.get("codec_name") or ""),
        "audio_sample_rate": int(audio.get("sample_rate", 0)),
        "file_size_bytes": target.stat().st_size,
        "audio": audio_report,
        "black_interval_count": black_events,
        "freeze_interval_count": freeze_events,
        "errors": sorted(set(errors)),
        "warnings": sorted(set(warnings)),
    }
