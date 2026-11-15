#!/usr/bin/env python3
"""Render one real creator recording through the Autopilot Motion bridge.

This validation intentionally bypasses storage upload and all publishers. It
retrieves the recording through Autopilot's existing private asset API, rejects
generated fallback audio, and writes only the finished MP4 and QA reports.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

ENGINE_DIR = Path(__file__).resolve().parent
REPO_ROOT = ENGINE_DIR.parents[1]
sys.path.insert(0, str(ENGINE_DIR))

import run as engine  # noqa: E402
from motion_hyperframes_renderer import render_full_track  # noqa: E402

OUTPUT_DIR = REPO_ROOT / "work" / "output"
VIDEO_PATH = OUTPUT_DIR / "violin-prince-full-track.mp4"
REPORT_PATH = OUTPUT_DIR / "real-track-validation-report.json"
SUPPORTED_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


def _probe_source(path: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "stream=codec_type,codec_name,sample_rate,channels,duration:format=duration,format_name",
            "-of", "json", str(path),
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    if result.returncode:
        raise RuntimeError("ffprobe could not read the creator recording: " + (result.stderr or "")[-500:])
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError("ffprobe returned invalid source-audio metadata.") from exc

    streams = payload.get("streams") or []
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if not audio:
        raise RuntimeError("The selected creator asset contains no audio stream.")
    try:
        duration = float(audio.get("duration") or payload.get("format", {}).get("duration"))
    except (TypeError, ValueError) as exc:
        raise RuntimeError("The selected creator recording has no readable duration.") from exc
    if duration < 24:
        raise RuntimeError(f"The creator recording is {duration:.2f}s; minimum supported duration is 24s.")
    if duration > 600:
        raise RuntimeError(f"The creator recording is {duration:.2f}s; the initial render limit is 600s.")

    return {
        "source_duration_seconds": round(duration, 3),
        "source_format": str(payload.get("format", {}).get("format_name") or ""),
        "source_codec": str(audio.get("codec_name") or ""),
        "sample_rate": int(audio.get("sample_rate") or 0),
        "channels": int(audio.get("channels") or 0),
    }


def _safe_message(exc: Exception) -> str:
    message = str(exc)
    private_url = os.environ.get("AUTOPILOT_API_URL", "").strip()
    if private_url:
        message = message.replace(private_url, "<private-autopilot-api>")
    return message[:1200]


def main() -> int:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    if os.environ.get("PUBLISH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}:
        raise RuntimeError("Validation is blocked because PUBLISH_ENABLED must remain false.")
    if os.environ.get("YOUTUBE_PUBLISH_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}:
        raise RuntimeError("Validation is blocked because YOUTUBE_PUBLISH_ENABLED must remain false.")
    if not os.environ.get("AUTOPILOT_API_URL", "").strip() or not os.environ.get("AUTOPILOT_JOB_TOKEN", "").strip():
        raise RuntimeError("The private Autopilot asset API credentials are not configured in GitHub Actions secrets.")

    asset, audio_bytes = engine.get_audio(prefer_creator_assets=True, allow_fallback=False)
    source = str(asset.get("audio_source") or "")
    if source not in {"uploaded_recording", "creator_recorded_violin"}:
        raise RuntimeError(
            "No real creator violin recording was returned by Autopilot. "
            "Generated or fallback audio is deliberately not accepted."
        )
    if not audio_bytes or len(audio_bytes) < 4096:
        raise RuntimeError("The private creator recording is missing or unexpectedly small.")

    filename = Path(str(asset.get("filename") or "")).name
    suffix = Path(filename).suffix.lower()
    if not filename or suffix not in SUPPORTED_SUFFIXES:
        raise RuntimeError(
            "The selected creator asset has no supported audio filename. "
            "Use MP3, WAV, M4A, AAC, FLAC or OGG."
        )

    with tempfile.TemporaryDirectory(prefix="violin-prince-real-audio-") as temporary:
        source_path = Path(temporary) / filename
        source_path.write_bytes(audio_bytes)
        source_info = _probe_source(source_path)

    display_name = Path(filename).stem.replace("_", " ").replace("-", " ")
    display_name = re.sub(r"\s+", " ", display_name).strip()[:55] or "Original violin recording"
    plan = {
        "title": "Violin Prince | " + display_name,
        "topic": "Full-track violin performance",
        "hook": "A complete Violin Prince violin recording, carried through one continuous visual composition.",
        "scenes": [
            {"caption": "The melody begins"},
            {"caption": "The performance develops"},
            {"caption": "The full recording reaches its close"},
        ],
    }

    render_report = render_full_track(
        audio_bytes=audio_bytes,
        audio_filename=filename,
        output_path=VIDEO_PATH,
        work_dir=REPO_ROOT / "work" / "real-track-render-work",
        plan=plan,
    )
    if not VIDEO_PATH.is_file() or VIDEO_PATH.stat().st_size < 4096:
        raise RuntimeError("The renderer returned without producing the expected full-track MP4.")

    result = {
        "status": "passed",
        "validation": "real_creator_audio_to_motion_hyperframes",
        "source_audio": {
            "filename": filename,
            "origin": source,
            **source_info,
        },
        "render": render_report,
        "output": {
            "filename": VIDEO_PATH.name,
            "size_bytes": VIDEO_PATH.stat().st_size,
            "publishing": "disabled",
            "storage_upload": "not_called",
            "publisher": "not_called",
        },
    }
    REPORT_PATH.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        failure = {
            "status": "failed",
            "validation": "real_creator_audio_to_motion_hyperframes",
            "error_type": type(exc).__name__,
            "error": _safe_message(exc),
            "publishing": "disabled",
            "storage_upload": "not_called",
            "publisher": "not_called",
        }
        REPORT_PATH.write_text(json.dumps(failure, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print("REAL_TRACK_VALIDATION_FAILED=" + json.dumps(failure, ensure_ascii=False), file=sys.stderr, flush=True)
        raise SystemExit(1)
