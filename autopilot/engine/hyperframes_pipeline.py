"""Motion + HyperFrames scene renderer with existing FFmpeg finishing and QA."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

ENGINE_DIR = Path(__file__).resolve().parent
ANIMATION2D_DIR = ENGINE_DIR / "animation2d"


class HyperFramesRenderError(RuntimeError):
    """Raised when Motion/HyperFrames rendering or verification fails."""


def _run(command: list[str], *, cwd: Path, timeout: int = 900) -> subprocess.CompletedProcess:
    result = subprocess.run(
        command, cwd=str(cwd), capture_output=True, text=True,
        timeout=timeout, check=False,
    )
    if result.returncode:
        detail = (result.stderr or result.stdout or "No diagnostic")[-3500:]
        raise HyperFramesRenderError(
            f"Command failed ({Path(command[0]).name}): {detail}"
        )
    return result


def render_daily_plan(
    engine: Any,
    plan: dict[str, Any],
    scene_images: list[Path],
    audio_path: Path,
    narration_path: Path,
    narration_info: dict[str, Any],
    characters: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build seekable Motion animations, render frame-accurately, then finish with FFmpeg."""
    scenes = plan.get("scenes") or []
    if len(scene_images) != len(scenes) or not scene_images:
        raise HyperFramesRenderError(
            "Every story scene must have one approved illustration plate."
        )

    project_dir = engine.WORK / "animation2d"
    if project_dir.exists():
        shutil.rmtree(project_dir)
    assets_dir = project_dir / "assets"
    scene_assets = assets_dir / "scenes"
    scene_assets.mkdir(parents=True, exist_ok=True)

    staged_characters = []
    for character in characters:
        staged = {**character, "layers": [], "expressions": {}}
        character_dir = assets_dir / "characters" / character["id"]
        character_dir.mkdir(parents=True, exist_ok=True)
        for layer in character["layers"]:
            source = Path(layer["src"]).resolve(strict=True)
            target = character_dir / Path(layer["src"]).name
            shutil.copy2(source, target)
            staged["layers"].append({
                **layer,
                "src": target.relative_to(project_dir).as_posix(),
            })
        for name, expression in character["expressions"].items():
            source = Path(expression["src"]).resolve(strict=True)
            target = character_dir / Path(expression["src"]).name
            shutil.copy2(source, target)
            staged["expressions"][name] = {
                **expression,
                "src": target.relative_to(project_dir).as_posix(),
            }
        staged_characters.append(staged)

    durations = engine.scene_durations_from_narration(narration_info, total_seconds=24.0)
    transition = float(engine.transition_duration(plan))
    starts = [
        0.0,
        max(0.0, float(durations[0]) - transition),
        max(0.0, float(durations[0]) + float(durations[1]) - 2 * transition),
    ]
    staged_scenes = []
    for index, (scene, image_path, scene_duration, scene_start) in enumerate(
        zip(scenes, scene_images, durations, starts)
    ):
        source = Path(image_path).resolve(strict=True)
        target = scene_assets / f"scene-{index + 1}{source.suffix.lower() or '.png'}"
        shutil.copy2(source, target)
        staged_scenes.append({
            "id": f"scene-{index + 1}",
            "start": round(float(scene_start), 4),
            "duration": round(float(scene_duration), 4),
            "image": target.relative_to(project_dir).as_posix(),
            "caption": str(scene.get("caption") or ""),
            "title": str(scene.get("title") or ""),
            "character_actions": scene.get("character_actions") or {},
        })

    project_data = {
        "title": str(plan.get("title") or "Violin Prince"),
        "width": int(engine.W),
        "height": int(engine.H),
        "fps": int(engine.FPS),
        "duration_seconds": 24.0,
        "scenes": staged_scenes,
        "characters": staged_characters,
    }
    project_json = project_dir / "project.json"
    project_json.write_text(
        json.dumps(project_data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node or not npm:
        raise HyperFramesRenderError("Node.js 22+ and npm are required for Motion + HyperFrames.")
    node_version = _run([node, "--version"], cwd=ANIMATION2D_DIR, timeout=20).stdout.strip()
    try:
        major = int(node_version.lstrip("v").split(".", 1)[0])
    except (TypeError, ValueError) as exc:
        raise HyperFramesRenderError("Unable to read the Node.js version.") from exc
    if major < 22:
        raise HyperFramesRenderError("HyperFrames requires Node.js 22 or later.")

    npm_modules = ANIMATION2D_DIR / "node_modules"
    hyperframes_cli = npm_modules / ".bin" / "hyperframes"
    if not hyperframes_cli.is_file():
        _run([npm, "install", "--no-audit", "--no-fund"], cwd=ANIMATION2D_DIR, timeout=600)

    _run([
        node, str(ANIMATION2D_DIR / "build.mjs"),
        "--project", str(project_json),
        "--out-dir", str(project_dir),
    ], cwd=ANIMATION2D_DIR, timeout=180)
    if not hyperframes_cli.is_file():
        raise HyperFramesRenderError("The HyperFrames CLI was not installed.")

    # Lint the isolated HTML composition before frame capture.
    _run([str(hyperframes_cli), "lint"], cwd=project_dir, timeout=180)

    picture_only = engine.OUT / "hyperframes-picture.mp4"
    _run([
        str(hyperframes_cli), "render",
        "--output", str(picture_only),
        "--fps", str(engine.FPS),
        "--quality", "standard",
    ], cwd=project_dir, timeout=1800)
    if not picture_only.is_file() or picture_only.stat().st_size < 4096:
        raise HyperFramesRenderError("HyperFrames did not produce a usable scene MP4.")

    audio_mix = engine.OUT / "daily-audio-mix.wav"
    audio_filter = (
        "[0:a]volume=0.24[bed];"
        "[1:a]highpass=f=75,acompressor=threshold=-20dB:ratio=3:attack=12:release=180,"
        "volume=1.15,asplit=2[voice_sc][voice_mix];"
        "[bed][voice_sc]sidechaincompress=threshold=0.035:ratio=10:attack=18:release=620:"
        "knee=4:makeup=1[ducked];"
        "[ducked][voice_mix]amix=inputs=2:duration=longest:dropout_transition=1,"
        "loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:st=0:d=0.5,"
        "afade=t=out:st=22:d=2[aout]"
    )
    _run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(audio_path), "-i", str(narration_path),
        "-filter_complex", audio_filter, "-map", "[aout]",
        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(audio_mix),
    ], cwd=engine.WORK, timeout=240)

    subtitle_path = engine.OUT / "narration.ass"
    engine.write_kinetic_ass(
        narration_info.get("subtitle_cues", []),
        subtitle_path,
        narration_info.get("word_cues", []),
    )
    font_dir = Path(engine._ensure_brand_fonts()["serif"]).parent.as_posix()
    final_video = engine.OUT / "violin-prince-short.mp4"
    _run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(picture_only), "-i", str(audio_mix),
        "-map", "0:v:0", "-map", "1:a:0",
        "-t", "24",
        "-vf", f"subtitles={subtitle_path.as_posix()}:fontsdir={font_dir}",
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k",
        "-movflags", "+faststart", str(final_video),
    ], cwd=engine.WORK, timeout=600)

    quality = engine.validate_final_video(final_video)
    sample_points = [
        ("OPEN", 0.55),
        ("SCENE 1", min(23.65, starts[0] + float(durations[0]) * 0.55)),
        ("SCENE 2", min(23.65, starts[1] + float(durations[1]) * 0.55)),
        ("SCENE 3", min(23.65, starts[2] + float(durations[2]) * 0.55)),
        ("FINAL FRAME", 23.30),
    ]
    contact_sheet = engine.make_render_contact_sheet(
        final_video, engine.OUT / "visual-contact-sheet.png", sample_points
    )
    quality.update({
        "visual_engine": "Motion + HyperFrames 2D scene renderer",
        "animation_runtime": "Motion for JavaScript",
        "scene_renderer": "HyperFrames frame-accurate seek-driven renderer",
        "render_fps": int(engine.FPS),
        "frame_accurate_timeline": True,
        "scene_timeline": staged_scenes,
        "character_count": len(staged_characters),
        "character_rigging": (
            "layered illustration rigs with joint anchors, hands, poses and facial-expression layers"
            if staged_characters else "no character assets supplied for this story"
        ),
        "motion_features": [
            "keyframes", "spring movement", "gestures", "scene transitions",
            "pose changes", "facial expression layers",
        ],
        "preview_contact_sheet": contact_sheet.name,
        "finishing": "existing FFmpeg audio mix, word-timed captions, MP4 encoding and ffprobe QA",
        "publishing": "disabled in GitHub Actions; release handoff only",
    })
    (engine.OUT / "quality_report.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return quality
