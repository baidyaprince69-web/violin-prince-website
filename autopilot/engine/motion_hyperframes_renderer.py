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


def build_content_context(
    plan: dict[str, Any] | None,
    narration_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Pass approved explainer scenes and Kokoro's native word timings to Motion."""
    plan = plan if isinstance(plan, dict) else {}
    narration_info = narration_info if isinstance(narration_info, dict) else {}
    raw_scenes = plan.get("scenes") if isinstance(plan.get("scenes"), list) else []
    scenes = []
    for scene in raw_scenes[:3]:
        if not isinstance(scene, dict):
            continue
        raw_graphic = scene.get("graphic_data")
        graphic = {}
        if isinstance(raw_graphic, dict):
            graphic_items = []
            for item in raw_graphic.get("items", [])[:4]:
                if isinstance(item, str):
                    graphic_items.append({
                        "label": _clean_text(item, 38),
                        "display": "",
                        "value": None,
                    })
                elif isinstance(item, dict):
                    graphic_items.append({
                        "label": _clean_text(item.get("label"), 38),
                        "display": _clean_text(item.get("display"), 22),
                        "value": item.get("value") if isinstance(item.get("value"), (int, float)) else None,
                    })
            graphic = {
                "type": _clean_text(raw_graphic.get("type"), 24),
                "items": graphic_items,
            }
        scenes.append({
            "caption": _clean_text(scene.get("caption"), 72),
            "visual_mode": _clean_text(scene.get("visual_mode"), 32),
            "graphic_label": _clean_text(scene.get("graphic_label"), 42),
            "graphic_detail": _clean_text(scene.get("graphic_detail"), 110),
            "graphic_data": graphic,
        })
    word_cues = []
    for cue in narration_info.get("word_cues", [])[:200]:
        if not isinstance(cue, dict):
            continue
        try:
            start, end = float(cue.get("start")), float(cue.get("end"))
        except (TypeError, ValueError):
            continue
        word = _clean_text(cue.get("text"), 32)
        if word and start >= 0 and end > start:
            word_cues.append({
                "text": word,
                "start": round(start, 4),
                "end": round(end, 4),
                "sentence_index": int(cue.get("sentence_index", 0) or 0),
            })
    return {
        "title": _clean_text(plan.get("title"), 60),
        "topic": _clean_text(plan.get("topic"), 90),
        "hook": _clean_text(plan.get("hook"), 110),
        "narration_script": _clean_text(plan.get("narration_script"), 1800),
        "captions": [scene["caption"] for scene in scenes],
        "scenes": scenes,
        "narration_words": word_cues,
        "narration_voice": _clean_text(narration_info.get("voice"), 32),
        "narration_engine": _clean_text(narration_info.get("engine"), 32),
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
        details = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
        details = details[-12000:] if details else "No command output"
        raise MotionHyperFramesError(
            f"{label} failed with exit code {result.returncode}:\n{details}"
        )
    return result.stdout or ""


def _run_composition_check(
    project_root: Path,
    timeout_seconds: int,
    report_path: Path,
) -> dict[str, Any]:
    """Run the full HyperFrames browser gate and persist its machine-readable report."""
    env = os.environ.copy()
    env["HYPERFRAMES_NO_TELEMETRY"] = "1"
    try:
        result = subprocess.run(
            ["npm", "run", "check", "--", "--json"],
            cwd=str(project_root),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise MotionHyperFramesError(
            f"HyperFrames browser validation exceeded its {timeout_seconds}-second safety timeout."
        ) from exc

    combined = ((result.stdout or "") + "\n" + (result.stderr or "")).strip()
    report: dict[str, Any] | None = None
    start = combined.find("{")
    if start >= 0:
        try:
            report, _ = json.JSONDecoder().raw_decode(combined[start:])
        except json.JSONDecodeError:
            report = None

    report_path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(report, dict):
        report_path.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        ok = report.get("ok") is True
        browser_skipped = report.get("browserSkipped") is True
        sections = ("lint", "runtime", "layout", "motion", "contrast", "craft", "audio", "hdr")
        findings = {
            name: report.get(name)
            for name in sections
            if report.get(name) not in (None, [], {})
        }
        if result.returncode or not ok or browser_skipped:
            details = json.dumps(
                {
                    "ok": report.get("ok"),
                    "browserSkipped": browser_skipped,
                    "findings": findings,
                },
                ensure_ascii=False,
                indent=2,
            )
            raise MotionHyperFramesError(
                "HyperFrames browser validation did not pass. "
                f"Full report saved to {report_path}.\n{details[-12000:]}"
            )
        return report

    fallback = combined[-12000:] if combined else "HyperFrames returned no JSON report or command output."
    report_path.write_text(fallback + "\n", encoding="utf-8")
    if result.returncode:
        raise MotionHyperFramesError(
            "HyperFrames browser validation failed and did not return valid JSON. "
            f"Diagnostics saved to {report_path}.\n{fallback}"
        )
    raise MotionHyperFramesError(
        "HyperFrames browser validation returned success without a valid JSON report. "
        f"Diagnostics saved to {report_path}."
    )


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
    narration_bytes: bytes | None = None,
    narration_info: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render a Kokoro-narrated explainer, with optional quiet violin underneath."""
    if not isinstance(audio_bytes, (bytes, bytearray)) or len(audio_bytes) < 4096:
        raise MotionHyperFramesError("The selected optional violin background bed is missing or unexpectedly small.")
    if not isinstance(narration_bytes, (bytes, bytearray)) or len(narration_bytes) < 4096:
        raise MotionHyperFramesError("Kokoro narration audio is required; instrumental-only Motion output is blocked.")
    narration_info = narration_info if isinstance(narration_info, dict) else {}
    word_cues = narration_info.get("word_cues")
    if (
        narration_info.get("engine") != "Kokoro-82M"
        or narration_info.get("voice") != "af_heart"
        or narration_info.get("word_sync_status") != "passed"
        or not isinstance(word_cues, list)
        or not word_cues
    ):
        raise MotionHyperFramesError("A passed Kokoro-82M af_heart narration record with native word timings is required.")
    suffix = Path(str(audio_filename or "")).suffix.lower() or ".wav"
    if suffix not in SUPPORTED_AUDIO_SUFFIXES:
        raise MotionHyperFramesError(
            "Motion + HyperFrames supports MP3, WAV, M4A, AAC, FLAC and OGG background audio assets."
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
    music_path = workspace / ("violin-background" + suffix)
    narration_path = workspace / "kokoro-narration.wav"
    audio_path = workspace / "narration-first-explainer-mix.wav"
    context_path = workspace / "content-context.json"
    music_path.write_bytes(bytes(audio_bytes))
    narration_path.write_bytes(bytes(narration_bytes))
    music_enabled = str(os.environ.get("MOTION_HYPERFRAMES_MUSIC_BED_ENABLED", "true")).strip().lower() in {"1", "true", "yes", "on"}
    if music_enabled:
        mix_filter = (
            "[0:a]aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo,volume=1.0[voice];"
            "[1:a]aresample=48000,aformat=sample_rates=48000:channel_layouts=stereo,volume=0.10[music];"
            "[music][voice]sidechaincompress=threshold=0.025:ratio=10:attack=40:release=450[ducked];"
            "[voice][ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0,"
            "alimiter=limit=0.95[mix]"
        )
        _run_step(
            "Mix Kokoro as the primary voice with a quiet ducked violin bed",
            [
                "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
                "-i", str(narration_path), "-i", str(music_path),
                "-filter_complex", mix_filter,
                "-map", "[mix]", "-ar", "48000", "-ac", "2",
                "-c:a", "pcm_s16le", str(audio_path),
            ],
            workspace, int(os.environ.get("MOTION_HYPERFRAMES_COMMAND_TIMEOUT_SECONDS", "3600")),
        )
    else:
        shutil.copy2(narration_path, audio_path)
    context_path.write_text(
        json.dumps(build_content_context(plan, narration_info), ensure_ascii=False, indent=2) + "\n",
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
        ("Ensure the pinned HyperFrames browser", ["npx", "hyperframes", "browser", "ensure"]),
        ("Lint the HyperFrames composition", ["npm", "run", "lint"]),
    ]

    try:
        for label, args in steps:
            _run_step(label, args, project_root, timeout_seconds)

        destination_parent = Path(output_path).resolve().parent
        check_report_path = destination_parent / "motion-hyperframes-check.json"
        check_report = _run_composition_check(
            project_root,
            timeout_seconds,
            check_report_path,
        )

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

        narration_duration = float(narration_info.get("duration_seconds") or 0)
        if narration_duration <= 0 or abs(media["duration_seconds"] - narration_duration) > 0.30:
            raise MotionHyperFramesError(
                "Rendered explainer duration does not match the Kokoro narration duration."
            )
        return {
            **media,
            "renderer": "motion_hyperframes",
            "production_type": "narrated_explainer",
            "primary_audio_source": "Kokoro-82M",
            "narration_voice": "af_heart",
            "narration_duration_seconds": narration_duration,
            "narration_word_timing_count": len(word_cues),
            "narration_word_sync_status": "passed",
            "music_bed_enabled": music_enabled,
            "music_bed_gain": 0.10 if music_enabled else 0.0,
            "full_track": True,
            "source_duration_seconds": expected_duration,
            "visual_sequence_duration_seconds": expected_duration,
            "visual_sequence_repeats": False,
            "content_context_used": True,
            "hyperframes_check_ok": check_report.get("ok") is True,
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
