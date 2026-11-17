"""Motion + HyperFrames scene renderer with cached per-scene renders and FFmpeg finishing."""
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


def _character_asset_paths(characters: list[dict[str, Any]]) -> list[Path]:
    paths: list[Path] = []
    for character in characters:
        for layer in character.get("layers", []):
            paths.append(Path(layer["src"]).resolve(strict=True))
        for expression in (character.get("expressions") or {}).values():
            paths.append(Path(expression["src"]).resolve(strict=True))
        for pose in (character.get("pose_assets") or {}).values():
            paths.append(Path(pose["src"]).resolve(strict=True))
    return paths


def _verify_scene_clip(path: Path, *, engine: Any) -> dict[str, Any]:
    if not path.is_file() or path.stat().st_size < 4096:
        raise HyperFramesRenderError("HyperFrames did not produce a usable scene MP4.")
    probe = _run([
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=codec_name,width,height,r_frame_rate",
        "-of", "json", str(path),
    ], cwd=path.parent, timeout=60)
    try:
        stream = json.loads(probe.stdout)["streams"][0]
        numerator, denominator = str(stream.get("r_frame_rate", "0/1")).split("/", 1)
        fps = float(numerator) / float(denominator)
    except (KeyError, IndexError, TypeError, ValueError, ZeroDivisionError) as exc:
        raise HyperFramesRenderError("Rendered scene clip has invalid video stream metadata.") from exc
    if (int(stream.get("width", 0)), int(stream.get("height", 0))) != (int(engine.W), int(engine.H)):
        raise HyperFramesRenderError("Rendered scene clip has unexpected frame dimensions.")
    if abs(fps - float(engine.FPS)) > 0.5:
        raise HyperFramesRenderError("Rendered scene clip has an unexpected frame rate.")
    if str(stream.get("codec_name") or "") != "h264":
        raise HyperFramesRenderError("Rendered scene clip must use H.264.")
    return {
        "status": "passed",
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": round(fps, 3),
        "codec": stream.get("codec_name"),
        "file_size_bytes": path.stat().st_size,
    }


def render_daily_plan(
    engine: Any,
    plan: dict[str, Any],
    scene_images: list[Path],
    audio_path: Path,
    narration_path: Path,
    narration_info: dict[str, Any],
    characters: list[dict[str, Any]],
    *,
    beat_analysis: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Render/cache independent scene clips, xfade them, then mix audio and captions."""
    from audio_analysis import analyse_audio_file
    from media_verification import verify_scene_assets
    from scene_checkpoints import (
        load_valid_checkpoint,
        retry_transient,
        save_checkpoint,
        scene_fingerprint,
    )
    from scene_timeline import build_scene_timeline

    scenes = plan.get("scenes") or []
    if len(scene_images) != len(scenes) or not 2 <= len(scenes) <= 4:
        raise HyperFramesRenderError(
            "The render requires two to four scenes and one approved illustration plate per scene."
        )

    beat_analysis = beat_analysis or analyse_audio_file(
        audio_path,
        known_bpm=(plan.get("audio_metadata") or {}).get("bpm")
        if isinstance(plan.get("audio_metadata"), dict) else None,
    )
    transition = float(engine.transition_duration(plan))
    timeline = build_scene_timeline(
        scenes, narration_info, total_seconds=24.0,
        transition_seconds=transition, beat_analysis=beat_analysis,
    )
    timeline_by_id = {item["scene_id"]: item for item in timeline["scenes"]}

    media_report = verify_scene_assets(
        scenes, scene_images, total_seconds=24.0, narration_info=narration_info,
        expected_narration_script=plan.get("narration_script"),
    )
    if media_report.get("status") == "failed":
        raise HyperFramesRenderError(
            "Scene media verification failed: " + json.dumps(media_report.get("errors", []))
        )
    (engine.OUT / "scene-media-verification.json").write_text(
        json.dumps(media_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    from character_visual_validation import verify_character_visuals
    character_visual_reports = []
    for character in characters:
        layer_sources = character.get("layers") or []
        if not layer_sources:
            continue
        character_root = Path(layer_sources[0]["src"]).resolve(strict=True).parent
        character_report = verify_character_visuals(character, character_root)
        if character_report.get("status") == "failed":
            raise HyperFramesRenderError(
                "Character asset verification failed for "
                + str(character.get("id") or "unknown")
                + ": " + json.dumps(character_report.get("errors", []))
            )
        character_visual_reports.append(character_report)
    (engine.OUT / "character-visual-verification.json").write_text(
        json.dumps(character_visual_reports, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    project_dir = engine.WORK / "animation2d"
    if project_dir.exists():
        shutil.rmtree(project_dir)
    assets_dir = project_dir / "assets"
    scene_assets_dir = assets_dir / "scenes"
    scene_assets_dir.mkdir(parents=True, exist_ok=True)

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
        staged["pose_assets"] = {}
        for name, pose in character.get("pose_assets", {}).items():
            source = Path(pose["src"]).resolve(strict=True)
            target = character_dir / Path(pose["src"]).name
            shutil.copy2(source, target)
            staged["pose_assets"][name] = {
                **pose,
                "src": target.relative_to(project_dir).as_posix(),
            }
        staged_characters.append(staged)

    staged_scenes = []
    for index, (scene, image_path, timing) in enumerate(zip(scenes, scene_images, timeline["scenes"])):
        source = Path(image_path).resolve(strict=True)
        scene_id = str(scene["id"])
        target = scene_assets_dir / f"{scene_id}{source.suffix.lower() or '.png'}"
        shutil.copy2(source, target)
        staged_scenes.append({
            "id": scene_id,
            "start": timing["start"],
            "duration": timing["clip_duration"],
            "segment_duration": timing["duration"],
            "image": target.relative_to(project_dir).as_posix(),
            "caption": str(scene.get("caption") or ""),
            "title": str(scene.get("title") or ""),
            "character_actions": scene.get("character_actions") or {},
            "narration_sentence_indexes": timing["narration_sentence_indexes"],
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
    (project_dir / "project.json").write_text(
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

    character_paths = _character_asset_paths(characters)
    cache_root = engine.WORK / "scene-render-cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    scene_clips: list[Path] = []
    scene_cache_records = []
    for index, (scene, image_path, staged_scene) in enumerate(zip(scenes, scene_images, staged_scenes)):
        scene_id = str(scene["id"])
        timing = timeline_by_id[scene_id]
        scene_root = project_dir / "render-scenes" / scene_id
        scene_root.mkdir(parents=True, exist_ok=True)
        scene_fingerprint_value = scene_fingerprint(
            scene,
            image_path,
            renderer_version="motion-hyperframes-per-scene-v1",
            character_asset_paths=character_paths,
            render_settings={
                "width": int(engine.W),
                "height": int(engine.H),
                "fps": int(engine.FPS),
                "duration": timing["clip_duration"],
                "timeline": timing,
                "scene_index": index,
                "total_scene_count": len(scenes),
                "project_title": str(plan.get("title") or "Violin Prince"),
                "transition": engine.scene_transition(plan, index - 1) if index else None,
                "character_definitions": characters,
                "caption_renderer": "kinetic-ass-v1",
            },
        )
        cached = load_valid_checkpoint(cache_root, scene_id, scene_fingerprint_value)
        if cached:
            scene_clips.append(cached)
            scene_cache_records.append({"scene_id": scene_id, "status": "reused", "path": str(cached)})
            continue

        scene_assets = scene_root / "assets"
        shutil.copytree(assets_dir, scene_assets, dirs_exist_ok=True)
        one_scene = {
            **project_data,
            "duration_seconds": float(timing["clip_duration"]),
            "scenes": [{
                **staged_scene,
                "start": 0.0,
                "duration": float(timing["clip_duration"]),
            }],
        }
        scene_project = scene_root / "project.json"
        scene_project.write_text(
            json.dumps(one_scene, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        _run([
            node, str(ANIMATION2D_DIR / "build.mjs"),
            "--project", str(scene_project),
            "--out-dir", str(scene_root),
        ], cwd=ANIMATION2D_DIR, timeout=180)
        _run([str(hyperframes_cli), "lint"], cwd=scene_root, timeout=180)
        raw_clip = scene_root / "scene.mp4"
        retry_transient(
            lambda: _run([
                str(hyperframes_cli), "render",
                "--output", str(raw_clip),
                "--fps", str(engine.FPS),
                "--quality", "standard",
            ], cwd=scene_root, timeout=1800),
            attempts=3,
        )
        clip_qa = _verify_scene_clip(raw_clip, engine=engine)
        cached_path = save_checkpoint(
            cache_root,
            scene_id,
            scene_fingerprint_value,
            raw_clip,
            qa_report=clip_qa,
        )
        scene_clips.append(cached_path)
        scene_cache_records.append({"scene_id": scene_id, "status": "rendered", "path": str(cached_path)})

    # Assemble the scene checkpoint clips with transitions at the narration-aware
    # cut times. A changed soundtrack does not invalidate unchanged picture clips;
    # the final audio/video assembly is still performed on every run.
    picture_only = engine.OUT / "hyperframes-picture.mp4"
    transition_parts = []
    previous_label = "0:v"
    for scene_index in range(1, len(scene_clips)):
        output_label = f"v{scene_index}"
        transition_name = engine.scene_transition(plan, scene_index - 1)
        transition_parts.append(
            f"[{previous_label}][{scene_index}:v]xfade=transition={transition_name}:"
            f"duration={float(timeline['transition_seconds']):.4f}:"
            f"offset={float(timeline['scenes'][scene_index]['start']):.4f}[{output_label}]"
        )
        previous_label = output_label
    transition_parts.append(
        f"[{previous_label}]scale={engine.W}:{engine.H}:flags=lanczos,"
        f"fps={engine.FPS},setsar=1,format=yuv420p[vout]"
    )
    filter_graph = ";".join(transition_parts)
    assemble = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for clip_path in scene_clips:
        assemble.extend(["-i", str(clip_path)])
    _run(assemble + [
        "-filter_complex", filter_graph, "-map", "[vout]",
        "-t", "24", "-an", "-c:v", "libx264", "-preset", "veryfast",
        "-crf", "23", "-pix_fmt", "yuv420p", str(picture_only),
    ], cwd=engine.WORK, timeout=900)
    if not picture_only.is_file() or picture_only.stat().st_size < 4096:
        raise HyperFramesRenderError("FFmpeg did not assemble the cached scene clips.")

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
    sample_points = [("OPEN", 0.55)]
    for index, timing in enumerate(timeline["scenes"]):
        sample_points.append((
            f"SCENE {index + 1}",
            min(23.65, max(0.1, float(timing["start"]) + float(timing["duration"]) * 0.55)),
        ))
    sample_points.append(("FINAL FRAME", 23.30))
    contact_sheet = engine.make_render_contact_sheet(
        final_video, engine.OUT / "visual-contact-sheet.png", sample_points
    )
    quality.update({
        "visual_engine": "Motion + HyperFrames 2D scene renderer",
        "animation_runtime": "Motion for JavaScript",
        "scene_renderer": "independent HyperFrames render with validated per-scene checkpoints",
        "render_fps": int(engine.FPS),
        "frame_accurate_timeline": True,
        "scene_timeline": timeline,
        "scene_render_checkpoints": {
            "cache_directory": "work/scene-render-cache",
            "scenes": scene_cache_records,
            "reused_scene_count": sum(1 for item in scene_cache_records if item["status"] == "reused"),
            "rendered_scene_count": sum(1 for item in scene_cache_records if item["status"] == "rendered"),
        },
        "music_beat_analysis": beat_analysis,
        "scene_media_verification": media_report,
        "character_visual_verification": character_visual_reports,
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
        "finishing": "existing FFmpeg audio mix, word-timed captions, MP4 encoding and independent media QA",
        "publishing": "disabled in GitHub Actions; release handoff only",
    })
    (engine.OUT / "quality_report.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return quality
