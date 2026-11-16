"""Blender renderer for Violin Prince's 3D hero + optional Frame By Plane scenes.

Daily production uses native Frame By Plane image layers for 2.5D backgrounds
behind the licensed 3D instrument model. Blender outputs opaque MP4 scene clips;
FFmpeg joins scenes, audio, subtitles and performs final QA.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

from benchmark_telemetry import capture_host_diagnostics

SUPPORTED_SCENE_TYPES = {
    "macro_3d": "string_vibration",
    "mechanism_3d": "bridge_cutaway",
    "waveform": "wave_field",
    "melody_map": "melody_path",
    "comparison": "comparison",
    "cover_performance": "violin_performance",
}


class BlenderRenderError(RuntimeError):
    """Raised when an explicitly enabled Blender render cannot be completed."""


def is_blender_render_enabled(value: str | bool | None = None) -> bool:
    if value is None:
        value = os.environ.get("BLENDER_RENDER_ENABLED", "false")
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def blender_render_worker_count(scene_count: int) -> int:
    """Return the bounded number of concurrent independent Blender scene jobs."""
    try:
        requested = int(os.environ.get("BLENDER_RENDER_WORKERS", "3"))
    except (TypeError, ValueError):
        requested = 1
    return max(1, min(max(1, int(scene_count)), max(1, requested), 3))


def blender_threads_per_worker() -> int:
    """Keep each Blender process lightweight when scenes are rendered concurrently."""
    try:
        requested = int(os.environ.get("BLENDER_THREADS_PER_WORKER", "1"))
    except (TypeError, ValueError):
        requested = 1
    return max(1, min(requested, 4))


def _bounded_env_int(name: str, default: int, minimum: int, maximum: int) -> int:
    try:
        value = int(os.environ.get(name, str(default)))
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def blender_render_resolution() -> tuple[int, int]:
    """Return the bounded internal resolution used before final FFmpeg upscaling."""
    width = _bounded_env_int("BLENDER_RENDER_WIDTH", 360, 160, 1920)
    height = _bounded_env_int("BLENDER_RENDER_HEIGHT", 640, 284, 1920)
    return (width - width % 2, height - height % 2)


def blender_render_fps() -> int:
    """Internal Blender frame rate; the final 720x1280 master is conformed to 25 fps."""
    return _bounded_env_int("BLENDER_RENDER_FPS", 16, 12, 30)


def blender_render_samples() -> int:
    """Eevee temporal samples per frame for predictable CPU render cost."""
    return _bounded_env_int("BLENDER_RENDER_SAMPLES", 2, 1, 32)


def blender_model_face_limit() -> int:
    """Maximum imported violin mesh face count used by the CPU scene renderer."""
    return _bounded_env_int("BLENDER_MODEL_FACE_LIMIT", 30000, 10000, 500000)


def model_decimation_ratio(face_count: int, face_limit: int) -> float:
    """Return a safe collapse ratio that brings a mesh within its face budget."""
    try:
        faces = max(0, int(face_count))
        limit = max(1, int(face_limit))
    except (TypeError, ValueError):
        raise ValueError("Model face count and face limit must be integers.")
    if faces <= limit:
        return 1.0
    return max(0.01, min(1.0, limit / float(faces)))


def _find_blender(executable: str | None = None) -> str | None:
    candidate = str(executable or os.environ.get("BLENDER_BIN") or "blender").strip()
    if not candidate:
        return None
    if os.path.sep in candidate:
        path = Path(candidate).expanduser()
        return str(path.resolve()) if path.is_file() else None
    return shutil.which(candidate)


def scene_type_for(scene: dict[str, Any]) -> str | None:
    if not isinstance(scene, dict):
        return None
    return SUPPORTED_SCENE_TYPES.get(str(scene.get("visual_mode") or "").strip().casefold())


def _stable_seed(scene: dict[str, Any], scene_index: int) -> int:
    value = {
        "visual_mode": str(scene.get("visual_mode") or ""),
        "caption": str(scene.get("caption") or ""),
        "image_prompt": str(scene.get("image_prompt") or ""),
        "scene_index": int(scene_index),
    }
    digest = hashlib.sha256(
        json.dumps(value, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return int(digest[:8], 16)


def _diagnostic_text(value: Any) -> str:
    """Decode subprocess output consistently; TimeoutExpired may expose bytes."""
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def _write_process_diagnostics(
    path: str | Path,
    command: list[str],
    *,
    stdout: Any = "",
    stderr: Any = "",
    returncode: int | None = None,
    error: str = "",
) -> Path:
    """Persist complete child-process output so CI summaries cannot hide tracebacks."""
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    sections = [
        "Violin Prince Blender process diagnostics",
        "returncode: " + (str(returncode) if returncode is not None else "unavailable"),
        "command: " + json.dumps([str(item) for item in command], ensure_ascii=False),
    ]
    if error:
        sections.extend(["", "PROCESS ERROR", error])
    sections.extend(["", "===== STDOUT =====", _diagnostic_text(stdout),
                     "", "===== STDERR =====", _diagnostic_text(stderr)])
    destination.write_text("\n".join(sections) + "\n", encoding="utf-8")
    return destination


def _run(
    command: list[str],
    timeout: int,
    label: str,
    *,
    diagnostics_path: str | Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    try:
        run_options = {
            "capture_output": True,
            "text": True,
            "timeout": timeout,
            "check": False,
        }
        if env is not None:
            run_options["env"] = env
        result = subprocess.run(command, **run_options)
    except subprocess.TimeoutExpired as exc:
        if diagnostics_path is not None:
            saved = _write_process_diagnostics(
                diagnostics_path, command, stdout=exc.stdout, stderr=exc.stderr,
                error=f"{label} exceeded its {timeout}-second timeout.",
            )
            suffix = f" Full diagnostics: {saved}"
        else:
            suffix = ""
        raise BlenderRenderError(
            f"{label} exceeded its {timeout}-second timeout.{suffix}"
        ) from exc
    except OSError as exc:
        if diagnostics_path is not None:
            saved = _write_process_diagnostics(
                diagnostics_path, command, error=f"{label} could not start: {exc}",
            )
            suffix = f" Full diagnostics: {saved}"
        else:
            suffix = ""
        raise BlenderRenderError(
            f"{label} could not start: {str(exc)[:300]}.{suffix}"
        ) from exc
    if result.returncode:
        if diagnostics_path is not None:
            saved = _write_process_diagnostics(
                diagnostics_path, command, stdout=result.stdout, stderr=result.stderr,
                returncode=result.returncode,
            )
            suffix = f" Full diagnostics: {saved}"
        else:
            suffix = ""
        stdout_tail = _diagnostic_text(result.stdout)[-1800:]
        stderr_tail = _diagnostic_text(result.stderr)[-1800:]
        detail = "\n".join(part for part in (
            "STDERR:\n" + stderr_tail if stderr_tail else "",
            "STDOUT:\n" + stdout_tail if stdout_tail else "",
        ) if part) or "No diagnostic returned."
        raise BlenderRenderError(
            f"{label} failed with exit code {result.returncode}: {detail}.{suffix}"
        )
    return result


def _probe_video(path: Path, expected_size: tuple[int, int], expected_seconds: float) -> dict[str, Any]:
    result = _run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,width,height,codec_name,r_frame_rate",
            "-of", "json", str(path),
        ],
        timeout=30,
        label="ffprobe validation",
    )
    try:
        payload = json.loads(result.stdout)
        video = next(
            item for item in payload.get("streams", [])
            if item.get("codec_type") == "video"
        )
        duration = float(payload.get("format", {}).get("duration", 0))
    except (ValueError, TypeError, StopIteration, json.JSONDecodeError) as exc:
        raise BlenderRenderError("Blender output did not contain a valid video stream.") from exc

    width, height = int(video.get("width", 0)), int(video.get("height", 0))
    if (width, height) != expected_size:
        raise BlenderRenderError(
            f"Blender scene is {width}×{height}; expected {expected_size[0]}×{expected_size[1]}."
        )
    if duration < expected_seconds - 0.30:
        raise BlenderRenderError(
            f"Blender scene is only {duration:.2f}s; expected about {expected_seconds:.2f}s."
        )
    if str(video.get("codec_name") or "") not in {"h264", "hevc", "mpeg4"}:
        raise BlenderRenderError("Blender output is not a supported encoded video.")
    return {
        "duration_seconds": round(duration, 3),
        "width": width,
        "height": height,
        "codec": video.get("codec_name"),
        "frame_rate": video.get("r_frame_rate"),
    }


def render_scene_video(
    scene: dict[str, Any],
    output_path: str | Path,
    scene_index: int = 0,
    duration_seconds: float = 8.0,
    *,
    enabled: bool | None = None,
    blender_executable: str | None = None,
    resolution: tuple[int, int] = (400, 712),
    fps: int = 16,
    timeout_seconds: int | None = None,
    benchmark_overrides: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """Render one complete opaque animated 3D scene as an MP4 clip.

    The benchmark-only arguments are accepted only when
    BLENDER_BENCHMARK_DIAGNOSTICS=1. They cannot silently alter normal
    production rendering.
    """
    if not is_blender_render_enabled(enabled):
        return None

    benchmark_enabled = os.environ.get("BLENDER_BENCHMARK_DIAGNOSTICS", "").strip() == "1"
    diagnostics_enabled = benchmark_enabled or os.environ.get(
        "BLENDER_RENDER_DIAGNOSTICS", ""
    ).strip().casefold() in {"1", "true", "yes", "on"}
    overrides = dict(benchmark_overrides or {})
    allowed_overrides = {
        "disable_dof",
        "disable_frame_by_plane",
        "disable_model",
        "disable_shadows",
        "samples",
    }
    unknown_overrides = sorted(set(overrides) - allowed_overrides)
    if unknown_overrides:
        raise BlenderRenderError(
            "Unsupported benchmark-only scene overrides: " + ", ".join(unknown_overrides)
        )
    if overrides and not benchmark_enabled:
        raise BlenderRenderError(
            "Diagnostic scene overrides are blocked unless BLENDER_BENCHMARK_DIAGNOSTICS=1."
        )

    scene_type = scene_type_for(scene)
    if not scene_type:
        raise BlenderRenderError(
            "Blender is enabled but the scene visual_mode has no Blender scene template: "
            + str(scene.get("visual_mode") if isinstance(scene, dict) else "invalid scene")
        )

    model_asset_path = str(
        (scene.get("model_asset_path") if isinstance(scene, dict) else "")
        or os.environ.get("BLENDER_VIOLIN_MODEL_PATH")
        or ""
    ).strip()
    model_asset_required = bool(
        scene.get("model_asset_required") if isinstance(scene, dict) else False
    ) or scene_type == "violin_performance"
    if overrides.get("disable_model"):
        if scene_type == "violin_performance":
            raise BlenderRenderError(
                "The model ablation is not supported for the cover-performance scene."
            )
        model_asset_path = ""
        model_asset_required = False
    if model_asset_required:
        if not model_asset_path or not Path(model_asset_path).is_file():
            raise BlenderRenderError(
                "This story scene requires its verified downloaded 3D model. "
                "The asset resolver must finish successfully; no reference-image or placeholder fallback is allowed."
            )
        if Path(model_asset_path).suffix.casefold() not in {".gltf", ".glb"}:
            raise BlenderRenderError("The selected story asset must be a .gltf or .glb file.")

    frame_by_plane_required = bool(
        scene.get("frame_by_plane_required") if isinstance(scene, dict) else False
    )
    frame_by_plane_manifest = str(
        (scene.get("frame_by_plane_manifest") if isinstance(scene, dict) else "") or ""
    ).strip()
    if overrides.get("disable_frame_by_plane"):
        frame_by_plane_required = False
        frame_by_plane_manifest = ""
    if frame_by_plane_required and not frame_by_plane_manifest:
        raise BlenderRenderError("This daily scene requires a Frame By Plane background manifest.")
    if frame_by_plane_manifest and not Path(frame_by_plane_manifest).is_file():
        raise BlenderRenderError("The required Frame By Plane background manifest does not exist.")

    executable = _find_blender(blender_executable)
    if not executable:
        raise BlenderRenderError(
            "Blender rendering is enabled, but Blender was not found. "
            "Install Blender or set BLENDER_BIN; no image/overlay fallback is permitted."
        )

    width, height = int(resolution[0]), int(resolution[1])
    if width < 160 or height < 284 or width > 1920 or height > 1920:
        raise BlenderRenderError("Blender video resolution is outside the safe 160–1920 pixel range.")
    fps = max(12, min(int(fps), 30))
    duration = max(1.0, min(float(duration_seconds), 24.0))
    safe_timeout = int(
        timeout_seconds
        if timeout_seconds is not None
        else os.environ.get("BLENDER_RENDER_TIMEOUT_SECONDS", "480")
    )
    # Production remains capped at its configured 900-second process timeout.
    # A larger value is only passed explicitly by the manual, sample-limited benchmark.
    safe_timeout = max(30, min(safe_timeout, 3600 if benchmark_enabled else 900))

    benchmark_max_frames = 0
    if benchmark_enabled:
        try:
            benchmark_max_frames = int(os.environ.get("BENCH_MAX_FRAMES", "3"))
        except (TypeError, ValueError) as exc:
            raise BlenderRenderError("BENCH_MAX_FRAMES must be an integer from 1 to 8.") from exc
        if not 1 <= benchmark_max_frames <= 8:
            raise BlenderRenderError("BENCH_MAX_FRAMES must be between 1 and 8.")
    elif os.environ.get("BENCH_MAX_FRAMES"):
        raise BlenderRenderError(
            "BENCH_MAX_FRAMES is reserved for the manual diagnostic workflow."
        )

    samples = blender_render_samples()
    if "samples" in overrides:
        try:
            samples = max(1, min(int(overrides["samples"]), 32))
        except (TypeError, ValueError) as exc:
            raise BlenderRenderError("Benchmark sample override must be an integer.") from exc

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    diagnostics_dir = destination.parent / "blender-diagnostics"
    diagnostics_path = diagnostics_dir / f"{destination.stem}.log"
    timings_path = diagnostics_dir / f"{destination.stem}.timings.json"
    preflight_report_path = diagnostics_dir / f"{destination.stem}-preflight-abort-report.json"
    if diagnostics_enabled:
        host_diagnostics_path = Path(
            os.environ.get("BLENDER_HOST_DIAGNOSTICS_PATH")
            or diagnostics_dir / "host-diagnostics.json"
        )
        capture_host_diagnostics(host_diagnostics_path)

    script_path = Path(__file__).with_name("blender_scene.py")
    if not script_path.is_file():
        raise BlenderRenderError("The full-scene Blender production script is missing.")

    threads_per_worker = blender_threads_per_worker()
    with tempfile.TemporaryDirectory(prefix="violin-prince-blender-") as folder:
        config_path = Path(folder) / "scene.json"
        config = {
            "scene_type": scene_type,
            "seed": _stable_seed(scene, scene_index),
            "width": width,
            "height": height,
            "fps": fps,
            "duration_seconds": duration,
            "threads": threads_per_worker,
            "samples": samples,
            "model_face_limit": blender_model_face_limit(),
            "model_asset_path": model_asset_path,
            "model_asset_kind": str(scene.get("model_asset_kind") or "generic"),
            "model_asset_required": model_asset_required,
            "frame_by_plane_manifest": frame_by_plane_manifest,
            "frame_by_plane_required": frame_by_plane_required,
            "diagnostics_enabled": diagnostics_enabled,
            "diagnostics_path": str(timings_path.resolve()),
            "preflight_report_path": str(preflight_report_path.resolve()),
            "preflight_enabled": (
                not benchmark_enabled
                and os.environ.get("BLENDER_RENDER_PREFLIGHT_ENABLED", "")
                .strip().casefold() in {"1", "true", "yes", "on"}
            ),
            "preflight_timeout_seconds": safe_timeout,
            "preflight_reserve_seconds": _bounded_env_int(
                "BLENDER_RENDER_PREFLIGHT_RESERVE_SECONDS", 30, 0, 300
            ),
            "preflight_first_frame_multiplier": 1.25,
            "benchmark_max_frames": benchmark_max_frames,
            "benchmark_overrides": overrides,
        }
        config_path.write_text(json.dumps(config), encoding="utf-8")
        blender_command = [
            executable, "--background",
            # Keep the dedicated BLENDER_USER_CONFIG preferences loaded so
            # the installed official Frame By Plane extension remains enabled.
            "--threads", str(threads_per_worker), "--python", str(script_path),
            "--", "--config", str(config_path),
            "--output", str(destination.resolve()),
        ]

        process_env = None
        if benchmark_enabled:
            process_env = os.environ.copy()
            egl_mode = process_env.get("BENCH_EGL_MODE", "surfaceless").strip().casefold()
            if egl_mode == "surfaceless":
                process_env["EGL_PLATFORM"] = "surfaceless"
            elif egl_mode == "unset":
                process_env.pop("EGL_PLATFORM", None)
            elif egl_mode == "xvfb":
                process_env.pop("EGL_PLATFORM", None)
                xvfb_run = shutil.which("xvfb-run")
                if not xvfb_run:
                    raise BlenderRenderError(
                        "EGL mode xvfb was selected but xvfb-run is not installed."
                    )
                blender_command = [xvfb_run, "-a", *blender_command]
            else:
                raise BlenderRenderError(
                    "BENCH_EGL_MODE must be one of: surfaceless, unset, xvfb."
                )

        if process_env is None:
            blender_process = _run(
                blender_command,
                timeout=safe_timeout,
                label=f"Blender full-scene render ({scene_type})",
                diagnostics_path=diagnostics_path,
            )
        else:
            blender_process = _run(
                blender_command,
                timeout=safe_timeout,
                label=f"Blender full-scene render ({scene_type})",
                diagnostics_path=diagnostics_path,
                env=process_env,
            )

    # Preserve successful stdout/stderr too: EGL/Mesa warnings and runtime renderer
    # diagnostics often occur on otherwise successful renders.
    _write_process_diagnostics(
        diagnostics_path,
        blender_command,
        stdout=blender_process.stdout,
        stderr=blender_process.stderr,
        returncode=blender_process.returncode,
    )

    # Blender appends its selected media extension to the output basename.
    # Accept that canonical file and rename it to the adapter's requested path.
    if not destination.is_file():
        candidates = sorted(
            path for path in destination.parent.glob(destination.stem + "*.mp4")
            if path.is_file() and path.stat().st_size >= 4096
        )
        if len(candidates) == 1:
            candidates[0].replace(destination)
    if not destination.is_file() or destination.stat().st_size < 4096:
        if not diagnostics_path.is_file():
            _write_process_diagnostics(
                diagnostics_path,
                blender_command,
                stdout=blender_process.stdout,
                stderr=blender_process.stderr,
                returncode=blender_process.returncode,
                error="Blender exited successfully but did not create the requested MP4.",
            )
        nearby = [path.name for path in destination.parent.iterdir()]
        raise BlenderRenderError(
            "Blender exited with code "
            + str(blender_process.returncode)
            + " but did not produce the requested MP4 scene. "
            + "Output directory entries=" + repr(nearby)
            + "; full Blender diagnostics saved to " + str(diagnostics_path)
        )
    expected_seconds = (
        benchmark_max_frames / float(fps)
        if benchmark_max_frames
        else duration
    )
    media = _probe_video(destination, (width, height), expected_seconds)
    frame_by_plane_report = None
    for line in (blender_process.stdout or "").splitlines():
        if line.startswith("FRAME_BY_PLANE_REPORT="):
            try:
                frame_by_plane_report = json.loads(line.split("=", 1)[1])
            except json.JSONDecodeError as exc:
                raise BlenderRenderError("Blender returned an invalid Frame By Plane report.") from exc
    if frame_by_plane_required and not isinstance(frame_by_plane_report, dict):
        raise BlenderRenderError(
            "Blender rendered the scene but did not confirm that Frame By Plane built its required image layers."
        )
    version_result = subprocess.run(
        [executable, "--version"], capture_output=True, text=True, timeout=20, check=False
    )
    version_lines = (version_result.stdout or version_result.stderr or "").splitlines()
    timing_report = None
    if timings_path.is_file():
        try:
            timing_report = json.loads(timings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            timing_report = {"status": "unreadable", "path": str(timings_path)}
    return {
        "status": "rendered",
        "scene_type": scene_type,
        "visual_mode": str(scene.get("visual_mode") or ""),
        "output_path": str(destination),
        "renderer": "Blender Eevee CPU + Frame By Plane 2.5D background planes" if frame_by_plane_report else "Blender Eevee CPU",
        "blender_version": version_lines[0][:120] if version_lines else "unknown",
        "rendered_as": "Frame By Plane 2.5D image layers behind a full 3D hero scene" if frame_by_plane_report else "full-frame opaque 3D animation",
        "frame_by_plane": frame_by_plane_report,
        "no_image_plate": not bool(frame_by_plane_report),
        "no_transparent_overlay": True,
        "camera_animation": True,
        "object_animation": True,
        "model_asset": Path(model_asset_path).name if model_asset_path else None,
        "asset_provenance_path": str(Path(model_asset_path).parent.parent / "asset-provenance.json")
        if model_asset_path and (Path(model_asset_path).parent.parent / "asset-provenance.json").is_file()
        else None,
        "diagnostics_path": str(diagnostics_path),
        "timings_path": str(timings_path),
        "timings": timing_report,
        "benchmark_overrides": overrides,
        **media,
    }

def _poster(video_path: Path, output_path: Path, timestamp: float) -> None:
    # Stay inside the actual clip duration. A seek at 1.5s into a 1.5s video
    # lands on EOF and returns no packet, even though Blender rendered the MP4.
    safe_timestamp = max(0.05, float(timestamp))
    _run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-ss", f"{safe_timestamp:.3f}", "-i", str(video_path),
            "-frames:v", "1", "-f", "image2", str(output_path),
        ],
        timeout=30,
        label="Blender scene PNG poster extraction",
    )
    if not output_path.is_file() or output_path.stat().st_size < 1024:
        raise BlenderRenderError("Could not extract a verification frame from the Blender scene.")


def _contact_sheet(posters: list[Path], destination: Path) -> None:
    from PIL import Image, ImageDraw

    cell_w, cell_h, gap, header = 360, 640, 20, 58
    canvas = Image.new(
        "RGB", (gap + len(posters) * (cell_w + gap), header + cell_h + gap),
        (8, 15, 26),
    )
    draw = ImageDraw.Draw(canvas)
    for index, path in enumerate(posters):
        with Image.open(path) as frame:
            frame = frame.convert("RGB").resize((cell_w, cell_h), Image.Resampling.LANCZOS)
            x = gap + index * (cell_w + gap)
            canvas.paste(frame, (x, header))
            draw.text((x + 8, 18), f"BLENDER 3D SCENE {index + 1}", fill=(239, 202, 139))
    destination.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(destination, quality=92)


def _production_preview(output_dir: Path, blender_executable: str | None = None,
                        resolution: tuple[int, int] = (360, 640), fps: int = 24) -> dict[str, Any]:
    """Render one animated 3D violin scene with cinematic camera movement."""
    output_dir.mkdir(parents=True, exist_ok=True)
    samples = [
        {
            "visual_mode": "cover_performance",
            "caption": "Full 3D violin: animated bow performance",
            "image_prompt": "A solid, complete amber violin with carved body, fingerboard, pegs, strings, f-holes and an animated bow in a dramatic midnight studio.",
        },
    ]
    clips: list[Path] = []
    posters: list[Path] = []
    scene_reports: list[dict[str, Any]] = []
    for index, scene in enumerate(samples):
        clip = output_dir / f"blender-scene-{index + 1}.mp4"
        report = render_scene_video(
            scene, clip, scene_index=index, duration_seconds=3.0,
            enabled=True, blender_executable=blender_executable,
            resolution=resolution, fps=fps, timeout_seconds=600,
        )
        if not report:
            raise BlenderRenderError("Blender preview unexpectedly skipped a scene.")
        poster = output_dir / f"blender-scene-{index + 1}-poster.png"
        _poster(clip, poster, report["duration_seconds"] / 2.0)
        clips.append(clip)
        posters.append(poster)
        scene_reports.append(report)

    concat_list = output_dir / "concat-list.txt"
    concat_list.write_text(
        "".join("file '" + str(path.resolve()).replace("'", "'\\''") + "'\n" for path in clips),
        encoding="utf-8",
    )
    preview = output_dir / "blender-full-3d-production-preview.mp4"
    _run(
        [
            "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
            "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "22",
            "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(preview),
        ],
        timeout=120,
        label="Blender scene preview assembly",
    )
    contact = output_dir / "blender-production-contact-sheet.jpg"
    _contact_sheet(posters, contact)
    report_path = output_dir / "blender-production-report.json"
    report_path.write_text(
        json.dumps(
            {
                "status": "passed",
                "production_mode": "full-frame animated 3D",
                "renderer": "Blender Eevee CPU",
                "scene_count": len(scene_reports),
                "resolution": list(resolution),
                "fps": fps,
                "total_preview_seconds": round(sum(item["duration_seconds"] for item in scene_reports), 2),
                "no_image_plate": True,
                "no_transparent_overlay": True,
                "scenes": scene_reports,
                "preview": preview.name,
                "contact_sheet": contact.name,
            },
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    if not preview.is_file() or preview.stat().st_size < 4096:
        raise BlenderRenderError("Blender preview assembly did not produce a valid MP4.")
    return {
        "status": "passed",
        "preview": str(preview),
        "contact_sheet": str(contact),
        "report": str(report_path),
        "scenes": scene_reports,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Render actual full-frame Violin Prince 3D scenes with Blender.")
    parser.add_argument("--production-preview", action="store_true")
    parser.add_argument("--output-dir", default="work/blender-production-preview")
    parser.add_argument("--blender-bin", default=None)
    parser.add_argument("--resolution", default="360x640")
    parser.add_argument("--fps", type=int, default=24)
    args = parser.parse_args()
    if not args.production_preview:
        parser.error("Use --production-preview to render a complete animated 3D preview.")
    try:
        width_text, height_text = args.resolution.lower().split("x", 1)
        resolution = (int(width_text), int(height_text))
        result = _production_preview(
            Path(args.output_dir), args.blender_bin, resolution, args.fps
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print("Blender full-scene production failed: " + str(exc)[:1200], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
