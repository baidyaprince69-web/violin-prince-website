"""Fail-closed media and text quality gates for Violin Prince Autopilot Phase 2."""
from __future__ import annotations

from array import array
from datetime import datetime, timezone
import json
import math
import re
import subprocess
from pathlib import Path
from typing import Any


class QualityGateError(RuntimeError):
    """Raised when a rendered artifact fails an acceptance check."""

    def __init__(self, report: dict[str, Any]):
        failed = [item["name"] for item in report.get("checks", []) if not item.get("passed")]
        details = [
            f"{item['name']} (observed={item.get('observed')!r})"
            for item in report.get("checks", []) if not item.get("passed")
        ]
        message = "Production quality gate rejected output: " + (
            "; ".join(details) if details else "unknown validation failure"
        )
        super().__init__(message)
        self.report = report
        self.retry_stage = report.get("retry_stage", "none")


def validate_cues(
    cues: Any,
    duration_seconds: float,
    word_count: int | None = None,
    require_word_timing: bool = False,
) -> dict[str, Any]:
    """Validate cue content, ordering, timing bounds and native word-cue coverage."""
    errors: list[str] = []
    if not isinstance(cues, list) or not cues:
        return {"valid": False, "count": 0, "last_end": 0.0, "errors": ["No timed narration cues were supplied."]}

    if require_word_timing and word_count:
        minimum = max(10, int(math.ceil(int(word_count) * 0.60)))
        if len(cues) < minimum:
            errors.append(f"Only {len(cues)} word cues were supplied; at least {minimum} are required.")

    previous_start = -1.0
    previous_end = 0.0
    last_end = 0.0
    for index, cue in enumerate(cues):
        if not isinstance(cue, dict):
            errors.append(f"Cue {index + 1} is not an object.")
            continue
        text = str(cue.get("text") or cue.get("word") or "").strip()
        try:
            start = float(cue.get("start"))
            end = float(cue.get("end"))
        except (TypeError, ValueError):
            errors.append(f"Cue {index + 1} has invalid start/end timestamps.")
            continue
        if not text:
            errors.append(f"Cue {index + 1} has no visible text.")
        if not math.isfinite(start) or not math.isfinite(end):
            errors.append(f"Cue {index + 1} has a non-finite timestamp.")
            continue
        if start < -0.05 or end <= start or end - start < 0.015:
            errors.append(f"Cue {index + 1} has an invalid or zero-length time range.")
        if start + 0.001 < previous_start:
            errors.append(f"Cue {index + 1} is out of chronological order.")
        if start < previous_end - 0.25:
            errors.append(f"Cue {index + 1} overlaps the prior cue by more than 250 ms.")
        if end > float(duration_seconds) + 0.15:
            errors.append(f"Cue {index + 1} extends beyond the video duration.")
        previous_start = max(previous_start, start)
        previous_end = max(previous_end, end)
        last_end = max(last_end, end)

    return {
        "valid": not errors,
        "count": len(cues),
        "last_end": round(last_end, 3),
        "errors": errors[:20],
    }


def validate_text_audit_payload(payload: Any) -> dict[str, Any]:
    """Validate the HTML renderer's real-frame SVG text and narration-order audit."""
    errors: list[str] = []
    if not isinstance(payload, dict):
        return {"valid": False, "frame_count": 0, "errors": ["Text-frame audit is not a JSON object."]}
    frames = payload.get("frames")
    if payload.get("ok") is not True:
        errors.append("Top-level text-frame audit did not pass.")
    if not isinstance(frames, list) or len(frames) < 3:
        errors.append("At least three sampled encoded-frame text audits are required.")
        frames = frames if isinstance(frames, list) else []
    for index, frame in enumerate(frames):
        if not isinstance(frame, dict):
            errors.append(f"Frame audit {index + 1} is invalid.")
            continue
        if frame.get("ok") is not True:
            errors.append(f"Frame audit {index + 1} did not pass.")
        if frame.get("missing_text"):
            errors.append(f"Frame audit {index + 1} has missing text.")
        if frame.get("invalid_text_nodes"):
            errors.append(f"Frame audit {index + 1} has invalid text nodes.")
        if frame.get("out_of_bounds_text"):
            errors.append(f"Frame audit {index + 1} has text outside the canvas.")
        if frame.get("narration_word_order_valid") is False:
            errors.append(f"Frame audit {index + 1} has invalid narration word order.")
        expected = frame.get("expected_text_nodes")
        actual = frame.get("actual_text_nodes")
        if expected is not None and actual is not None and int(expected) != int(actual):
            errors.append(f"Frame audit {index + 1} has a text-node count mismatch.")
        spoken = frame.get("narration_word_count")
        timed = frame.get("timed_word_count")
        if spoken is not None and timed is not None and int(timed) < int(spoken):
            errors.append(f"Frame audit {index + 1} is missing timed narration words.")
    return {"valid": not errors, "frame_count": len(frames), "errors": errors[:20]}


def retry_stage_for_failures(checks: list[dict[str, Any]]) -> str:
    """Choose the smallest safe recovery stage for a failed acceptance gate."""
    categories = {item.get("category") for item in checks if not item.get("passed")}
    if not categories:
        return "none"
    if categories.issubset({"audio"}):
        return "audio_mix"
    if categories.issubset({"video", "text"}):
        return "video_render"
    if categories.issubset({"audio", "video", "text"}):
        return "video_render"
    return "none"


def _fraction(value: str | None) -> float:
    raw = str(value or "").strip()
    if "/" in raw:
        numerator, denominator = raw.split("/", 1)
        return float(numerator) / max(float(denominator), 1e-9)
    return float(raw)


def resolve_frame_rate(
    average_rate: str | None,
    nominal_rate: str | None,
    frame_count: int | str | None = None,
    duration_seconds: float | None = None,
) -> float:
    """Prefer a valid measured rate, then FFprobe's nominal rate, then frame-count ratio."""
    for candidate in (average_rate, nominal_rate):
        try:
            rate = _fraction(candidate)
        except (TypeError, ValueError, ZeroDivisionError, OverflowError):
            continue
        if math.isfinite(rate) and rate > 0:
            return rate
    try:
        count = int(frame_count or 0)
        duration = float(duration_seconds or 0)
        if count > 0 and math.isfinite(duration) and duration > 0:
            return count / duration
    except (TypeError, ValueError, OverflowError):
        pass
    return 0.0


def _event_durations(log: str, event_name: str) -> list[float]:
    """Read duration values emitted by FFmpeg detection filters."""
    pattern = re.escape(event_name) + r":([0-9]+(?:\.[0-9]+)?)"
    return [float(value) for value in re.findall(pattern, log)]


def _run(command: list[str], timeout: int = 240) -> subprocess.CompletedProcess:
    return subprocess.run(command, capture_output=True, text=False, timeout=timeout)


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def run_quality_gate(
    video_path: str | Path,
    *,
    report_path: str | Path | None = None,
    expected_width: int = 720,
    expected_height: int = 1280,
    expected_duration: float = 24.0,
    duration_tolerance: float = 0.5,
    expected_fps: float | None = None,
    frame_rate_tolerance: float = 0.5,
    audio_required: bool = True,
    narration_cues: Any = None,
    word_count: int | None = None,
    require_word_timing: bool = False,
    text_audit_path: str | Path | None = None,
) -> dict[str, Any]:
    """Inspect the encoded artifact, reject defects and persist an auditable result."""
    path = Path(video_path)
    target_report = Path(report_path) if report_path else path.parent / "quality-control-report.json"
    checks: list[dict[str, Any]] = []
    metrics: dict[str, Any] = {}
    warnings: list[str] = []

    def record(name: str, passed: bool, observed: Any, expected: Any, category: str) -> None:
        checks.append({
            "name": name,
            "passed": bool(passed),
            "observed": observed,
            "expected": expected,
            "category": category,
        })

    def finish() -> dict[str, Any]:
        passed = all(item["passed"] for item in checks)
        report = {
            "schema_version": 1,
            "gate": "violin-prince-production-quality-control",
            "checked_at": datetime.now(timezone.utc).isoformat(),
            "status": "passed" if passed else "rejected",
            "passed": passed,
            "video_file": path.name,
            "metrics": metrics,
            "checks": checks,
            "warnings": warnings,
            "failed_checks": [item["name"] for item in checks if not item["passed"]],
            "retry_stage": retry_stage_for_failures(checks),
        }
        _write_report(target_report, report)
        if not passed:
            raise QualityGateError(report)
        return report

    exists = path.is_file()
    record("file_present", exists, exists, True, "file")
    if not exists:
        return finish()

    file_size = path.stat().st_size
    metrics["file_size_bytes"] = file_size
    record("file_size", file_size >= 100_000, file_size, ">= 100000 bytes", "file")

    try:
        probe = _run([
            "ffprobe", "-v", "error", "-count_frames", "-show_entries",
            "format=duration,size:stream=codec_type,codec_name,width,height,sample_rate,channels,duration,avg_frame_rate,r_frame_rate,nb_frames,nb_read_frames,pix_fmt",
            "-of", "json", str(path),
        ])
    except (OSError, subprocess.SubprocessError) as exc:
        record("ffprobe", False, str(exc), "valid readable media", "file")
        return finish()
    if probe.returncode:
        record("ffprobe", False, probe.stderr.decode("utf-8", "replace")[-1000:], "valid readable media", "file")
        return finish()
    try:
        data = json.loads(probe.stdout.decode("utf-8"))
        streams = data.get("streams", [])
        format_duration = float(data.get("format", {}).get("duration", 0))
    except (ValueError, TypeError, json.JSONDecodeError):
        record("ffprobe_json", False, "invalid ffprobe JSON", "valid metadata", "file")
        return finish()

    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    record("video_stream_present", video is not None, bool(video), True, "video")
    if video is None:
        return finish()

    width = int(video.get("width", 0) or 0)
    height = int(video.get("height", 0) or 0)
    video_duration = float(video.get("duration") or format_duration or 0)
    fps = resolve_frame_rate(
        video.get("avg_frame_rate"),
        video.get("r_frame_rate"),
        video.get("nb_read_frames") or video.get("nb_frames"),
        video_duration,
    )
    metrics.update({
        "duration_seconds": round(format_duration, 3),
        "video_duration_seconds": round(video_duration, 3),
        "width": width,
        "height": height,
        "video_codec": video.get("codec_name", ""),
        "pixel_format": video.get("pix_fmt", ""),
        "fps": round(fps, 3),
    })
    record(
        "vertical_dimensions",
        width == expected_width and height == expected_height,
        f"{width}x{height}",
        f"{expected_width}x{expected_height}",
        "video",
    )
    record(
        "video_duration",
        abs(video_duration - expected_duration) <= duration_tolerance,
        round(video_duration, 3),
        f"{expected_duration:.2f}s ± {duration_tolerance:.2f}s",
        "video",
    )
    record("video_codec", video.get("codec_name") == "h264", video.get("codec_name"), "h264", "video")
    record("video_pixel_format", video.get("pix_fmt") in ("yuv420p", "yuvj420p"), video.get("pix_fmt"), "yuv420p-compatible", "video")
    fps_passed = (
        20.0 <= fps <= 30.0
        if expected_fps is None
        else abs(fps - float(expected_fps)) <= frame_rate_tolerance
    )
    fps_expected = (
        "20–30 fps"
        if expected_fps is None
        else f"{float(expected_fps):.2f} fps ± {frame_rate_tolerance:.2f}"
    )
    record("frame_rate", fps_passed, round(fps, 3), fps_expected, "video")

    audio_duration = None
    if audio_required:
        record("audio_stream_present", audio is not None, bool(audio), True, "audio")
        if audio is not None:
            audio_duration = float(audio.get("duration") or format_duration or 0)
            sample_rate = int(audio.get("sample_rate", 0) or 0)
            channels = int(audio.get("channels", 0) or 0)
            metrics.update({
                "audio_duration_seconds": round(audio_duration, 3),
                "audio_codec": audio.get("codec_name", ""),
                "audio_sample_rate": sample_rate,
                "audio_channels": channels,
            })
            record("audio_codec", audio.get("codec_name") == "aac", audio.get("codec_name"), "aac", "audio")
            record("audio_sample_rate", sample_rate >= 22050, sample_rate, ">= 22050 Hz", "audio")
            record("audio_channels", channels in (1, 2), channels, "mono or stereo", "audio")
            sync_error = abs(video_duration - audio_duration)
            metrics["audio_video_duration_delta_seconds"] = round(sync_error, 3)
            record("audio_video_duration_sync", sync_error <= 0.15, round(sync_error, 3), "<= 0.15s", "audio")

    decode_maps = ["-map", "0:v:0"]
    if audio_required and audio is not None:
        decode_maps += ["-map", "0:a:0"]
    decode = _run([
        "ffmpeg", "-hide_banner", "-v", "error", "-xerror", "-i", str(path),
        *decode_maps, "-f", "null", "-",
    ])
    decode_error = decode.stderr.decode("utf-8", "replace")[-1200:]
    record("full_stream_decode", decode.returncode == 0, decode_error[-400:] if decode.returncode else "all selected packets decoded", "no decode errors", "video")

    black = _run([
        "ffmpeg", "-hide_banner", "-i", str(path),
        "-vf", "blackdetect=d=0.75:pix_th=0.05", "-an", "-f", "null", "-",
    ])
    black_log = black.stderr.decode("utf-8", "replace")
    black_durations = _event_durations(black_log, "black_duration")
    longest_black = max(black_durations, default=0.0)
    metrics["longest_black_segment_seconds"] = round(longest_black, 3)
    record("extended_black_frames", black.returncode == 0 and longest_black < 0.75, round(longest_black, 3), "< 0.75s contiguous black", "video")

    freeze = _run([
        "ffmpeg", "-hide_banner", "-i", str(path),
        "-vf", "freezedetect=n=-50dB:d=1.5", "-an", "-f", "null", "-",
    ])
    freeze_log = freeze.stderr.decode("utf-8", "replace")
    freeze_durations = _event_durations(freeze_log, "freeze_duration")
    longest_freeze = max(freeze_durations, default=0.0)
    metrics["longest_freeze_segment_seconds"] = round(longest_freeze, 3)
    record(
        "extended_freeze_frames",
        freeze.returncode == 0 and longest_freeze < 1.5,
        round(longest_freeze, 3),
        "< 1.5s contiguous freeze",
        "video",
    )

    if audio_required and audio is not None:
        loudness = _run([
            "ffmpeg", "-hide_banner", "-nostats", "-i", str(path),
            "-vn", "-af", "loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json",
            "-f", "null", "-",
        ])
        loudness_log = loudness.stderr.decode("utf-8", "replace")
        json_blocks = re.findall(r"\{\s*\"input_i\".*?\}", loudness_log, flags=re.S)
        loudness_data = None
        if loudness.returncode == 0 and json_blocks:
            try:
                loudness_data = json.loads(json_blocks[-1])
            except json.JSONDecodeError:
                loudness_data = None
        if loudness_data:
            try:
                integrated = float(loudness_data["input_i"])
                true_peak = float(loudness_data["input_tp"])
            except (KeyError, TypeError, ValueError):
                integrated, true_peak = float("nan"), float("nan")
            metrics["integrated_loudness_lufs"] = round(integrated, 2) if math.isfinite(integrated) else str(integrated)
            metrics["true_peak_dbtp"] = round(true_peak, 2) if math.isfinite(true_peak) else str(true_peak)
            record("integrated_loudness", math.isfinite(integrated) and -22.0 <= integrated <= -12.0, metrics["integrated_loudness_lufs"], "-22 to -12 LUFS", "audio")
            record("true_peak", math.isfinite(true_peak) and true_peak <= -0.3, metrics["true_peak_dbtp"], "<= -0.3 dBTP", "audio")
        else:
            record("loudness_analysis", False, loudness_log[-900:], "readable EBU loudness metrics", "audio")

        tail = _run([
            "ffmpeg", "-hide_banner", "-v", "error", "-sseof", "-0.8", "-i", str(path),
            "-vn", "-ac", "1", "-ar", "8000", "-f", "s16le", "-",
        ])
        raw = tail.stdout
        tail_rms = 0.0
        if tail.returncode == 0 and len(raw) >= 64:
            samples = array("h")
            samples.frombytes(raw[:len(raw) - (len(raw) % 2)])
            if samples:
                tail_rms = math.sqrt(sum((sample / 32768.0) ** 2 for sample in samples) / len(samples))
        metrics["last_800ms_audio_rms"] = round(tail_rms, 7)
        record("music_or_audio_tail_present", tail.returncode == 0 and tail_rms >= 0.00005, round(tail_rms, 7), "RMS >= 0.00005 in final 800 ms", "audio")

    if narration_cues is not None:
        cue_result = validate_cues(
            narration_cues,
            video_duration,
            word_count=word_count,
            require_word_timing=require_word_timing,
        )
        metrics["narration_cue_count"] = cue_result["count"]
        metrics["narration_last_cue_end_seconds"] = cue_result["last_end"]
        record("narration_timing", cue_result["valid"], cue_result, "non-empty ordered cues within video duration", "narration")

    if text_audit_path is not None:
        audit_file = Path(text_audit_path)
        if not audit_file.is_file():
            audit_result = {"valid": False, "frame_count": 0, "errors": ["Required text-frame audit file is missing."]}
        else:
            try:
                audit_result = validate_text_audit_payload(json.loads(audit_file.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                audit_result = {"valid": False, "frame_count": 0, "errors": ["Text-frame audit is unreadable JSON."]}
        metrics["text_frame_audit"] = audit_result
        record("encoded_frame_text_audit", audit_result["valid"], audit_result, ">= 3 passing encoded-frame audits; no missing or overflowing text", "text")

    return finish()
