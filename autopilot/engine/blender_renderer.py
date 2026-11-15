"""Full-frame animated Blender renderer for Violin Prince Autopilot.

Blender owns the entire visual scene and outputs an opaque MP4 scene clip.
There is no transparent render, image-plate composite, or Blender overlay.
FFmpeg remains responsible only for joining scenes, audio, subtitles and final QA.
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


def _run(command: list[str], timeout: int, label: str) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(
            command, capture_output=True, text=True, timeout=timeout, check=False
        )
    except subprocess.TimeoutExpired as exc:
        raise BlenderRenderError(f"{label} exceeded its {timeout}-second timeout.") from exc
    except OSError as exc:
        raise BlenderRenderError(f"{label} could not start: {str(exc)[:300]}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "No diagnostic returned.")[-1800:]
        raise BlenderRenderError(f"{label} failed: {detail}")
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
    resolution: tuple[int, int] = (720, 1280),
    fps: int = 25,
    timeout_seconds: int | None = None,
) -> dict[str, Any] | None:
    """Render one complete opaque animated 3D scene as an MP4 clip."""
    if not is_blender_render_enabled(enabled):
        return None

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
    if model_asset_required:
        if not model_asset_path or not Path(model_asset_path).is_file():
            raise BlenderRenderError(
                "This story scene requires its verified downloaded 3D model. "
                "The asset resolver must finish successfully; no reference-image or placeholder fallback is allowed."
            )
        if Path(model_asset_path).suffix.casefold() not in {".gltf", ".glb"}:
            raise BlenderRenderError("The selected story asset must be a .gltf or .glb file.")

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
    safe_timeout = max(30, min(safe_timeout, 900))

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    script_path = Path(__file__).with_name("blender_scene.py")
    if not script_path.is_file():
        raise BlenderRenderError("The full-scene Blender production script is missing.")

    with tempfile.TemporaryDirectory(prefix="violin-prince-blender-") as folder:
        config_path = Path(folder) / "scene.json"
        config = {
            "scene_type": scene_type,
            "seed": _stable_seed(scene, scene_index),
            "width": width,
            "height": height,
            "fps": fps,
            "duration_seconds": duration,
            "threads": 2,
            "samples": max(8, min(int(os.environ.get("BLENDER_RENDER_SAMPLES", "16")), 32)),
            "model_asset_path": model_asset_path,
            "model_asset_kind": str(scene.get("model_asset_kind") or "generic"),
            "model_asset_required": model_asset_required,
        }
        config_path.write_text(json.dumps(config), encoding="utf-8")
        blender_process = _run(
            [
                executable, "--background", "--factory-startup",
                "--threads", "2", "--python", str(script_path),
                "--", "--config", str(config_path),
                "--output", str(destination.resolve()),
            ],
            timeout=safe_timeout,
            label=f"Blender full-scene render ({scene_type})",
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
        diagnostic = (
            (blender_process.stderr or "")[-1200:]
            + "\\n"
            + (blender_process.stdout or "")[-1200:]
        )
        nearby = [path.name for path in destination.parent.iterdir() if path.is_file()]
        raise BlenderRenderError(
            "Blender exited without producing the requested MP4 scene. "
            "Output directory files=" + repr(nearby) + "; Blender diagnostics=" + diagnostic
        )
    media = _probe_video(destination, (width, height), duration)
    version_result = subprocess.run(
        [executable, "--version"], capture_output=True, text=True, timeout=20, check=False
    )
    version_lines = (version_result.stdout or version_result.stderr or "").splitlines()
    return {
        "status": "rendered",
        "scene_type": scene_type,
        "visual_mode": str(scene.get("visual_mode") or ""),
        "output_path": str(destination),
        "renderer": "Blender Eevee CPU",
        "blender_version": version_lines[0][:120] if version_lines else "unknown",
        "rendered_as": "full-frame opaque 3D animation",
        "no_image_plate": True,
        "no_transparent_overlay": True,
        "camera_animation": True,
        "object_animation": True,
        "model_asset": Path(model_asset_path).name if model_asset_path else None,
        "asset_provenance_path": str(Path(model_asset_path).parent.parent / "asset-provenance.json")
        if model_asset_path and (Path(model_asset_path).parent.parent / "asset-provenance.json").is_file()
        else None,
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
