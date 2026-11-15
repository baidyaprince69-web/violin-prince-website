#!/usr/bin/env python3
"""Run one small, offline Blender 5.2.4 + Frame By Plane integration render.

This is a renderer/extension smoke test only. It deliberately does not invoke
research, narration, asset discovery, Cloudflare, publishing, or the daily plan.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image

ENGINE_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE_DIR))

from frame_by_plane_backgrounds import create_frame_by_plane_backgrounds


def run_checked(command: list[str], *, timeout: int, label: str) -> subprocess.CompletedProcess:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"{label} could not complete: {exc}") from exc
    if result.returncode:
        detail = (result.stderr or result.stdout or "No diagnostic returned.")[-6000:]
        raise RuntimeError(f"{label} failed with exit code {result.returncode}:\n{detail}")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", default="work/blender-fbp-smoke")
    args = parser.parse_args()

    blender = str(os.environ.get("BLENDER_BIN") or shutil.which("blender") or "").strip()
    if not blender:
        raise RuntimeError("Blender was not found on PATH; install the pinned Blender + Frame By Plane action first.")

    output_dir = Path(args.output_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    background_root = output_dir / "backgrounds"
    scene_plan = {
        "title": "Violin Prince Frame By Plane integration smoke",
        "scenes": [
            {
                "caption": "A signal moves through a physical studio",
                "graphic_label": "SIGNAL TEST",
                "image_prompt": "dark cinematic audio studio with signal displays and acoustic panels",
                "visual_mode": "waveform",
            },
            {
                "caption": "Three depth layers create parallax",
                "graphic_label": "DEPTH TEST",
                "image_prompt": "cinematic studio depth, teal and amber monitor lighting",
                "visual_mode": "waveform",
            },
            {
                "caption": "Blender renders the final 3D composition",
                "graphic_label": "RENDER TEST",
                "image_prompt": "midnight studio with warm cinematic rim light",
                "visual_mode": "waveform",
            },
        ],
    }
    # Match the headless CPU rendering environment used by daily production.
    os.environ.setdefault("EGL_PLATFORM", "surfaceless")
    os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
    os.environ.setdefault("MESA_LOADER_DRIVER_OVERRIDE", "llvmpipe")

    bundles = create_frame_by_plane_backgrounds(
        scene_plan, background_root, size=(540, 960)
    )
    manifest_path = Path(bundles[0]["manifest_path"]).resolve()
    output_still = output_dir / "single-scene-frame-by-plane-smoke.png"
    config_path = output_dir / "scene-config.json"
    config = {
        "scene_type": "wave_field",
        "seed": 20261115,
        "width": 270,
        "height": 480,
        "fps": 12,
        "duration_seconds": 2.0,
        "threads": 1,
        "samples": 4,
        "geometry_budget_smoke": True,
        "geometry_budget_smoke_limit": 700,
        "model_face_limit": 60000,
        "frame_by_plane_manifest": str(manifest_path),
        "frame_by_plane_required": True,
        "smoke_still": True,
        "smoke_frame": 1,
        "output": str(output_still),
    }
    config_path.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    # Exercise the exact production entry point. The old test wrapper inserted
    # ENGINE_DIR into sys.path before importing blender_scene, hiding a missing
    # bootstrap in Blender's direct --python execution mode.
    blender_script = ENGINE_DIR / "blender_scene.py"
    command = [
        blender, "--background", "--threads", "1",
        "--python", str(blender_script),
        "--", "--config", str(config_path), "--output", str(output_still),
    ]
    rendered = run_checked(command, timeout=300, label="Single-scene Blender + Frame By Plane render")

    report = None
    geometry_report = None
    for line in rendered.stdout.splitlines():
        if line.startswith("FRAME_BY_PLANE_REPORT="):
            report = json.loads(line.split("=", 1)[1])
        elif line.startswith("MODEL_GEOMETRY_SMOKE="):
            geometry_report = json.loads(line.split("=", 1)[1])
    if not isinstance(report, dict):
        raise RuntimeError(
            "Blender produced no machine-readable Frame By Plane report.\n"
            + (rendered.stdout or "")[-5000:]
            + (rendered.stderr or "")[-3000:]
        )
    if report.get("extension_version") != "8.0.1" or int(report.get("layer_count", 0)) != 3:
        raise RuntimeError("The smoke render did not confirm all three Frame By Plane 8.0.1 layers.")
    if not isinstance(geometry_report, dict) or int(geometry_report.get("render_faces", 0)) > 945:
        raise RuntimeError("Blender did not pass its bounded mesh-decimation smoke test.")

    if not output_still.is_file() or output_still.stat().st_size < 1024:
        produced = sorted(path.name for path in output_dir.rglob("*") if path.is_file())
        raise RuntimeError(
            "Blender did not produce the expected one-frame PNG proof. "
            f"Files found={produced}; stdout={(rendered.stdout or '')[-5000:]}; "
            f"stderr={(rendered.stderr or '')[-3000:]}"
        )
    try:
        with Image.open(output_still) as image:
            image.verify()
        with Image.open(output_still) as image:
            if image.size != (270, 480) or image.mode not in {"RGB", "RGBA"}:
                raise RuntimeError(
                    f"Unexpected smoke image properties: size={image.size}, mode={image.mode}"
                )
    except Exception as exc:
        raise RuntimeError(f"The Blender smoke image is invalid: {exc}") from exc

    version = run_checked([blender, "--version"], timeout=20, label="Blender version check")
    version_line = (version.stdout or version.stderr).splitlines()[0]
    print("BLENDER_FRAME_BY_PLANE_SMOKE=" + json.dumps({
        "status": "passed",
        "blender_version": version_line,
        "frame_by_plane_version": report.get("extension_version"),
        "frame_by_plane_layers": report.get("layer_count"),
        "rendered_as": report.get("mode"),
        "rendered_frame": 1,
        "resolution": [270, 480],
        "image_bytes": output_still.stat().st_size,
        "proof_image": str(output_still),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print("Blender + Frame By Plane smoke failed: " + str(exc)[:5000], file=sys.stderr)
        raise SystemExit(1)
