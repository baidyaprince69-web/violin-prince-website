"""Optional full-track Motion + HyperFrames renderer for Autopilot."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

SUPPORTED_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}
DEFAULT_MAX_TRACK_SECONDS = 600.0
RENDER_FILENAME = "violin-prince-motion-full-track.mp4"


class MotionHyperFramesError(RuntimeError):
    """Raised when the optional renderer cannot complete safely."""


def is_motion_hyperframes_render_enabled(value: str | None = None) -> bool:
    raw = os.environ.get("MOTION_HYPERFRAMES_RENDER_ENABLED", "false") if value is None else value
    return str(raw).strip().lower() in {"1", "true", "yes", "on"}


def select_renderer(motion_enabled: bool, blender_enabled: bool) -> str:
    if motion_enabled and blender_enabled:
        raise MotionHyperFramesError(
            "MOTION_HYPERFRAMES_RENDER_ENABLED and BLENDER_RENDER_ENABLED cannot both be true. "
            "Choose the full-track 2D/2.5D route or the existing Blender 3D route."
        )
    if motion_enabled:
        return "motion_hyperframes"
    return "blender" if blender_enabled else "standard"


def _clean_text(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split()).strip()[:limit]


def build_content_context(plan: dict[str, Any] | None) -> dict[str, Any]:
    """Pass already-approved Autopilot editorial text into the motion composition."""
    plan = plan if isinstance(plan, dict) else {}
    scenes = plan.get("scenes") if isinstance(plan.get("scenes"), list) else []
    captions = [
        _clean_text(scene.get("caption"), 72)
        for scene in scenes[:3]
        if isinstance(scene, dict)
    ]
    return {
        "title": _clean_text(plan.get("title"), 60),
        "topic": _clean_text(plan.get("topic"), 64),
        "hook": _clean_text(plan.get("hook"), 110),
        "captions": captions,
    }


def _run_step(label: str, args: list[str], project_root: Path, timeout_seconds: int) -> str:
    env = os.environ.copy()
    env["HYPERFRAMES_NO_TELEMETRY"] = "1"
    try:
        result = subprocess.run(
            args, cwd=str(project_root), env=env, capture_output=True,
            text=True, timeout=timeout_seconds, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MotionHyperFramesError(
            f"{label} exceeded its {timeout_seconds}-second safety timeout."
        ) from exc
    if result.returncode:
        details = (result.stderr or result.stdout or "No command output")[-1800:]
        raise MotionHyperFramesError(
            f"{label} failed with exit code {result.returncode}: {details}"
        )
    return result.stdout or ""


def _probe_mp4(path: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries",
                "stream=codec_type,codec_name,width,height,r_frame_rate,duration:format=duration",
                "-of", "json", str(path),
            ],
            capture_output=True, text=True, timeout=60, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise MotionHyperFramesError("ffprobe could not inspect the rendered MP4.") from exc
    if result.returncode:
        raise MotionHyperFramesError("ffprobe rejected the rendered MP4: " + (result.stderr or "")[-900:])
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise MotionHyperFramesError("ffprobe returned malformed MP4 metadata.") from exc

    streams = payload.get("streams") if isinstance(payload.get("streams"), list) else []
    video = next((item for item in streams if item.get("codec_type") == "video"), None)
    audio = next((item for item in streams if item.get("codec_type") == "audio"), None)
    if not video or not audio:
        raise MotionHyperFramesError("The full-track MP4 must contain both video and audio streams.")
    try:
        duration = float(payload.get("format", {}).get("duration"))
        video_duration = float(video.get("duration") or duration)
        numerator, denominator = str(video.get("r_frame_rate") or "0/1").split("/", 1)
        fps = float(numerator) / float(denominator)
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise MotionHyperFramesError("The rendered MP4 has invalid duration or frame-rate metadata.") from exc

    if video.get("codec_name") != "h264":
        raise MotionHyperFramesError("The full-track renderer must produce H.264 video.")
    if int(video.get("width") or 0) != 1080 or int(video.get("height") or 0) != 1920:
        raise MotionHyperFramesError("The full-track renderer must produce 1080x1920 vertical video.")
    if abs(fps - 30.0) > 0.01:
        raise MotionHyperFramesError(f"Expected 30 fps, received {fps:g} fps.")
    return {
        "duration_seconds": duration,
        "video_duration_seconds": video_duration,
        "width": int(video["width"]),
        "height": int(video["height"]),
        "fps": fps,
        "video_codec": str(video.get("codec_name") or ""),
        "audio_codec": str(audio.get("codec_name") or ""),
        "audio_included": True,
    }


def render_full_track(
    audio_bytes: bytes,
    audio_filename: str,
    output_path: str | Path,
    work_dir: str | Path,
    plan: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render the complete approved audio asset with Motion + HyperFrames."""
    if not isinstance(audio_bytes, (bytes, bytearray)) or len(audio_bytes) < 4096:
        raise MotionHyperFramesError("The selected full-track audio asset is missing or unexpectedly small.")

    suffix = Path(str(audio_filename or "")).suffix.lower() or ".wav"
    if suffix not in SUPPORTED_AUDIO_SUFFIXES:
        raise MotionHyperFramesError(
            "Motion + HyperFrames supports MP3, WAV, M4A, AAC, FLAC and OGG audio assets."
        )

    repo_root = Path(__file__).resolve().parents[2]
    project_root = repo_root / "prototypes" / "hyperframes-motion"
    if not (project_root / "package.json").is_file():
        raise MotionHyperFramesError("The Motion + HyperFrames project is missing from this branch.")
    if not (project_root / "node_modules" / ".bin" / "hyperframes").exists():
        raise MotionHyperFramesError("Motion + HyperFrames dependencies are not installed.")
    for binary in ("node", "npm", "ffmpeg", "ffprobe"):
        if shutil.which(binary) is None:
            raise MotionHyperFramesError(f"Required rendering executable is not installed: {binary}")

    workspace = Path(work_dir).resolve()
    workspace.mkdir(parents=True, exist_ok=True)
    audio_path = workspace / ("source-audio" + suffix)
    context_path = workspace / "content-context.json"
    audio_path.write_bytes(bytes(audio_bytes))
    context_path.write_text(
        json.dumps(build_content_context(plan), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    output_dir = project_root / "output"
    assets_dir = project_root / "assets"
    output_dir.mkdir(parents=True, exist_ok=True)
    assets_dir.mkdir(parents=True, exist_ok=True)
    expected_mp4 = output_dir / RENDER_FILENAME
    if expected_mp4.exists():
        expected_mp4.unlink()

    timeout_seconds = int(os.environ.get("MOTION_HYPERFRAMES_COMMAND_TIMEOUT_SECONDS", "3600"))
    steps = [
        ("Prepare the full-track composition", [
            "npm", "run", "prepare:composition", "--", "--audio", str(audio_path),
            "--content-json", str(context_path),
        ]),
        ("Prepare the Motion browser module", ["npm", "run", "prepare:motion"]),
        ("Lint the HyperFrames composition", ["npm", "run", "lint"]),
        ("Validate the HyperFrames composition", ["npm", "run", "check"]),
    ]

    try:
        for label, args in steps:
            _run_step(label, args, project_root, timeout_seconds)

        manifest_path = output_dir / "audio-manifest.json"
        if not manifest_path.is_file():
            raise MotionHyperFramesError("The composition did not write its audio-duration manifest.")
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            expected_duration = float(manifest["source_duration_seconds"])
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise MotionHyperFramesError("The composition audio-duration manifest is invalid.") from exc

        maximum_duration = float(os.environ.get(
            "MOTION_HYPERFRAMES_MAX_TRACK_SECONDS", str(DEFAULT_MAX_TRACK_SECONDS)
        ))
        if expected_duration < 1 or expected_duration > maximum_duration:
            raise MotionHyperFramesError(
                f"Full-track duration {expected_duration:.2f}s is outside the initial "
                f"Autopilot limit of 1–{maximum_duration:.0f}s."
            )

        _run_step("Verify deterministic full-track seeking", ["npm", "run", "verify:seeking"],
                  project_root, timeout_seconds)
        _run_step("Render the complete audio track", ["npm", "run", "render"],
                  project_root, timeout_seconds)
        contact_sheet = output_dir / "contact-sheet.jpg"
        _run_step("Create the contact sheet", [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-i", str(expected_mp4), "-vf", "fps=1/6,scale=270:480,tile=3x2",
            "-frames:v", "1", str(contact_sheet),
        ], project_root, timeout_seconds)
        _run_step("Verify the full-track MP4", ["npm", "run", "verify"],
                  project_root, timeout_seconds)

        if not expected_mp4.is_file() or expected_mp4.stat().st_size < 4096:
            raise MotionHyperFramesError("HyperFrames completed without creating a valid MP4.")
        media = _probe_mp4(expected_mp4)
        if abs(media["duration_seconds"] - expected_duration) > 0.25:
            raise MotionHyperFramesError("Rendered MP4 duration does not match the selected audio track.")
        if abs(media["video_duration_seconds"] - expected_duration) > 0.25:
            raise MotionHyperFramesError("Rendered video stream does not cover the selected audio track.")

        destination = Path(output_path).resolve()
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(expected_mp4, destination)
        if contact_sheet.is_file():
            shutil.copy2(contact_sheet, destination.parent / "motion-contact-sheet.jpg")
        seeking_report = output_dir / "seeking-check" / "seeking-report.json"
        if seeking_report.is_file():
            shutil.copy2(seeking_report, destination.parent / "motion-seeking-report.json")

        return {
            **media,
            "renderer": "motion_hyperframes",
            "full_track": True,
            "source_duration_seconds": expected_duration,
            "visual_cycle_seconds": min(10.0, expected_duration),
            "visual_cycle_repeats": expected_duration > 10.0,
            "content_context_used": True,
        }
    finally:
        audio_path.unlink(missing_ok=True)
        context_path.unlink(missing_ok=True)
        for asset in assets_dir.glob("music-bed.*"):
            asset.unlink(missing_ok=True)
        (project_root / "index.html").unlink(missing_ok=True)
        if output_dir.exists():
            shutil.rmtree(output_dir, ignore_errors=True)
        if assets_dir.exists() and not any(assets_dir.iterdir()):
            assets_dir.rmdir()
        shutil.rmtree(workspace, ignore_errors=True)
