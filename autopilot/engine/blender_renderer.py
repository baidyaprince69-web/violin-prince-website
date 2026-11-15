"""Optional, CPU-only Blender overlays for the Violin Prince render pipeline.

The renderer deliberately creates one transparent 3D still per eligible scene.
Pillow retains typography/diagrams and FFmpeg retains timeline motion and encoding.
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
}


class BlenderRenderError(RuntimeError):
    """Raised when an explicitly enabled Blender render cannot be completed."""


def is_blender_render_enabled(value: str | bool | None = None) -> bool:
    """Read the opt-in switch; Blender stays off unless explicitly enabled."""
    if value is None:
        value = os.environ.get("BLENDER_RENDER_ENABLED", "false")
    return str(value).strip().casefold() in {"1", "true", "yes", "on"}


def _find_blender(executable: str | None = None) -> str | None:
    """Resolve BLENDER_BIN or the standard Blender executable."""
    candidate = str(executable or os.environ.get("BLENDER_BIN") or "blender").strip()
    if not candidate:
        return None
    if os.path.sep in candidate:
        path = Path(candidate).expanduser()
        return str(path.resolve()) if path.is_file() else None
    return shutil.which(candidate)


def scene_type_for(scene: dict[str, Any]) -> str | None:
    """Map only approved visual modes to known procedural Blender scenes."""
    if not isinstance(scene, dict):
        return None
    mode = str(scene.get("visual_mode") or "").strip().casefold()
    return SUPPORTED_SCENE_TYPES.get(mode)


def _stable_seed(scene: dict[str, Any], scene_index: int) -> int:
    seed_payload = {
        "visual_mode": str(scene.get("visual_mode") or ""),
        "caption": str(scene.get("caption") or ""),
        "image_prompt": str(scene.get("image_prompt") or ""),
        "scene_index": int(scene_index),
    }
    digest = hashlib.sha256(
        json.dumps(seed_payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    ).hexdigest()
    return int(digest[:8], 16)


def _blender_version(executable: str) -> str:
    try:
        result = subprocess.run(
            [executable, "--version"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    first_line = (result.stdout or result.stderr or "").strip().splitlines()
    return first_line[0][:120] if first_line else "unknown"


def render_scene_overlay(
    scene: dict[str, Any],
    output_path: str | Path,
    scene_index: int = 0,
    *,
    enabled: bool | None = None,
    blender_executable: str | None = None,
    resolution: tuple[int, int] = (540, 960),
    timeout_seconds: int | None = None,
) -> dict[str, Any] | None:
    """Render a transparent Blender overlay for one supported scene.

    Returns None when the feature is disabled or the scene mode is not supported.
    When enabled for a supported mode, missing Blender or a failed render is fatal:
    the caller must not silently claim that a Blender scene was produced.
    """
    if not is_blender_render_enabled(enabled):
        return None

    scene_type = scene_type_for(scene)
    if not scene_type:
        return None

    executable = _find_blender(blender_executable)
    if not executable:
        raise BlenderRenderError(
            "Blender rendering is enabled, but the Blender executable was not found. "
            "Install Blender or set BLENDER_BIN; the render will not silently fall back."
        )

    width, height = (int(resolution[0]), int(resolution[1]))
    if width < 64 or height < 64 or width > 1920 or height > 1920:
        raise BlenderRenderError("Blender overlay resolution is outside the safe 64–1920 pixel range.")

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    script_path = Path(__file__).with_name("blender_scene.py")
    if not script_path.is_file():
        raise BlenderRenderError("The Blender scene-generation script is missing.")

    safe_timeout = int(
        timeout_seconds
        if timeout_seconds is not None
        else os.environ.get("BLENDER_RENDER_TIMEOUT_SECONDS", "180")
    )
    safe_timeout = max(15, min(safe_timeout, 600))

    with tempfile.TemporaryDirectory(prefix="violin-prince-blender-") as folder:
        config_path = Path(folder) / "scene.json"
        config = {
            "scene_type": scene_type,
            "seed": _stable_seed(scene, scene_index),
            "width": width,
            "height": height,
            "samples": 6,
            "threads": 2,
        }
        config_path.write_text(json.dumps(config), encoding="utf-8")
        command = [
            executable,
            "--background",
            "--factory-startup",
            "--threads",
            "2",
            "--python",
            str(script_path),
            "--",
            "--config",
            str(config_path),
            "--output",
            str(destination.resolve()),
        ]
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=safe_timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise BlenderRenderError(
                f"Blender exceeded the {safe_timeout}-second scene-render limit."
            ) from exc
        except OSError as exc:
            raise BlenderRenderError("Blender could not be started: " + str(exc)[:300]) from exc

        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "No Blender diagnostic was returned.")[-1200:]
            raise BlenderRenderError("Blender scene rendering failed: " + detail)
        if not destination.is_file() or destination.stat().st_size < 1024:
            raise BlenderRenderError("Blender exited without producing a valid overlay PNG.")

    try:
        from PIL import Image

        with Image.open(destination) as overlay:
            overlay.load()
            if overlay.size != (width, height):
                raise BlenderRenderError(
                    f"Blender overlay has size {overlay.size}; expected {(width, height)}."
                )
            if overlay.mode != "RGBA":
                raise BlenderRenderError("Blender overlay must preserve an RGBA transparency channel.")
            if overlay.getchannel("A").getbbox() is None:
                raise BlenderRenderError("Blender overlay is fully transparent.")
    except BlenderRenderError:
        raise
    except Exception as exc:
        raise BlenderRenderError("Blender output could not be validated: " + str(exc)[:300]) from exc

    return {
        "status": "rendered",
        "scene_type": scene_type,
        "visual_mode": str(scene.get("visual_mode") or ""),
        "output_path": str(destination),
        "resolution": [width, height],
        "render_engine": "Cycles CPU",
        "samples": 6,
        "blender_version": _blender_version(executable),
        "animation_scope": "single true-3D RGBA frame; FFmpeg supplies the existing scene motion",
    }


def composite_scene_overlay(
    base_image_path: str | Path,
    overlay_path: str | Path,
    output_path: str | Path,
    size: tuple[int, int] = (720, 1280),
) -> Path:
    """Composite Blender's transparent 3D layer over the existing scene plate."""
    from PIL import Image, ImageOps

    destination = Path(output_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    width, height = int(size[0]), int(size[1])
    with Image.open(base_image_path) as base_source, Image.open(overlay_path) as overlay_source:
        base = ImageOps.fit(
            base_source.convert("RGBA"),
            (width, height),
            method=Image.Resampling.LANCZOS,
            centering=(0.5, 0.46),
        )
        overlay = overlay_source.convert("RGBA")
        if overlay.size != (width, height):
            overlay = overlay.resize((width, height), Image.Resampling.LANCZOS)
        base.alpha_composite(overlay)
        base.convert("RGB").save(destination, format="PNG", optimize=True)
    return destination


def _smoke_test(output_dir: Path, blender_executable: str | None = None) -> dict[str, Any]:
    """Run one small real Blender render and verify its transparent composite."""
    from PIL import Image

    output_dir.mkdir(parents=True, exist_ok=True)
    overlay_path = output_dir / "blender-smoke-overlay.png"
    composite_path = output_dir / "blender-smoke-composite.png"
    base_path = output_dir / "blender-smoke-base.png"
    Image.new("RGB", (720, 1280), (7, 15, 28)).save(base_path)
    report = render_scene_overlay(
        {
            "visual_mode": "macro_3d",
            "caption": "Blender CPU render smoke test",
            "image_prompt": "A violin string vibrating in a cinematic 3D scene",
        },
        overlay_path,
        scene_index=0,
        enabled=True,
        blender_executable=blender_executable,
        resolution=(360, 640),
        timeout_seconds=180,
    )
    if not report:
        raise BlenderRenderError("The Blender smoke test did not render an eligible scene.")
    composite_scene_overlay(base_path, overlay_path, composite_path, size=(720, 1280))
    with Image.open(composite_path) as rendered:
        rendered.load()
        if rendered.size != (720, 1280):
            raise BlenderRenderError("The Blender composite failed its 720×1280 output check.")
    return {
        "status": "passed",
        "blender": report.get("blender_version", "unknown"),
        "scene_type": report["scene_type"],
        "overlay_resolution": report["resolution"],
        "composite_resolution": [720, 1280],
        "composite": str(composite_path),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Optional Blender CPU-rendered 3D overlays.")
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--output-dir", default="work/blender-smoke")
    parser.add_argument("--blender-bin", default=None)
    args = parser.parse_args()
    if not args.smoke_test:
        parser.error("Use --smoke-test to run the Blender integration check.")
    try:
        print(json.dumps(_smoke_test(Path(args.output_dir), args.blender_bin), indent=2))
        return 0
    except Exception as exc:
        print("Blender smoke test failed: " + str(exc)[:1000], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
