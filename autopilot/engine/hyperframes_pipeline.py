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


def _validate_scene_motion_report(scene: dict[str, Any], report: dict[str, Any]) -> None:
    """Reject static substitutes when the scene plan explicitly requests motion graphics."""
    if not isinstance(report, dict) or report.get("status") != "passed":
        raise HyperFramesRenderError(
            "Motion builder did not pass its visual-motion contract for "
            + str(scene.get("id") or "unknown scene") + "."
        )
    graphic = scene.get("graphic_data")
    if isinstance(graphic, dict):
        graphic_type = str(graphic.get("type") or "").casefold()
        expected = 1 if graphic_type == "waveform" else len(graphic.get("items") or [])
        scenes = report.get("scenes") or []
        item = next(
            (value for value in scenes if str(value.get("scene_id") or "") == str(scene.get("id") or "")),
            None,
        )
        actual = int((item or {}).get("animated_graphic_items") or 0)
        if expected < 1 or actual < expected:
            raise HyperFramesRenderError(
                f"Scene {scene.get('id')} planned {expected} animated graphic elements "
                f"but Motion generated {actual}; static-image fallback is blocked."
            )
    actions = scene.get("character_actions") or {}
    presenter = actions.get("violin-prince") or {}
    if presenter.get("visible") is True and presenter.get("gesture"):
        scenes = report.get("scenes") or []
        item = next(
            (value for value in scenes if str(value.get("scene_id") or "") == str(scene.get("id") or "")),
            None,
        )
        if int((item or {}).get("animated_presenter_count") or 0) < 1:
            raise HyperFramesRenderError(
                f"Scene {scene.get('id')} shows Violin Prince but contains no articulated gesture animation."
            )


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


def _absolute_scene_project_directory(work_dir: Path) -> Path:
    """Return the scene-project root as an absolute path from the runner cwd."""
    return (work_dir / "animation2d").resolve()


def _build_motion_project(node: str, scene_project: Path, output_dir: Path) -> None:
    """Build a scene using absolute paths because Node runs from ANIMATION2D_DIR.

    The Python pipeline uses repository-relative work paths, but build.mjs
    resolves --project and --out-dir from its own working directory. Passing
    the relative paths directly makes Node look under animation2d/work/.
    """
    _run([
        node, str(ANIMATION2D_DIR / "build.mjs"),
        "--project", str(scene_project.resolve()),
        "--out-dir", str(output_dir.resolve()),
    ], cwd=ANIMATION2D_DIR, timeout=180)




def _verify_director_final_video(
    path: Path,
    *,
    engine: Any,
    expected_duration: float,
) -> dict[str, Any]:
    """Validate a variable-duration director render rather than the legacy 24s format."""
    if not path.is_file() or path.stat().st_size < 150000:
        raise HyperFramesRenderError("Master Director final MP4 is missing or unexpectedly small.")
    probe = _run([
        "ffprobe", "-v", "error",
        "-show_entries",
        "format=duration:stream=codec_type,width,height,sample_rate,channels,codec_name,r_frame_rate",
        "-of", "json", str(path),
    ], cwd=path.parent, timeout=60)
    try:
        data = json.loads(probe.stdout)
        duration = float(data.get("format", {}).get("duration", 0))
        streams = data.get("streams", [])
        video = next(item for item in streams if item.get("codec_type") == "video")
        audio = next(item for item in streams if item.get("codec_type") == "audio")
        numerator, denominator = str(video.get("r_frame_rate", "0/1")).split("/", 1)
        frame_rate = float(numerator) / float(denominator)
    except (KeyError, StopIteration, TypeError, ValueError, ZeroDivisionError) as exc:
        raise HyperFramesRenderError("Master Director MP4 has invalid audio/video stream metadata.") from exc
    if abs(duration - expected_duration) > 0.5:
        raise HyperFramesRenderError(
            f"Master Director MP4 duration {duration:.2f}s does not match its "
            f"{expected_duration:.2f}s storyboard."
        )
    if (int(video.get("width", 0)), int(video.get("height", 0))) != (
        int(engine.W), int(engine.H)
    ):
        raise HyperFramesRenderError("Master Director MP4 has unexpected frame dimensions.")
    if str(video.get("codec_name") or "") != "h264":
        raise HyperFramesRenderError("Master Director MP4 must use H.264 video.")
    if abs(frame_rate - float(engine.FPS)) > 0.5:
        raise HyperFramesRenderError("Master Director MP4 has an unexpected frame rate.")
    if int(audio.get("sample_rate", 0)) < 22050:
        raise HyperFramesRenderError("Master Director mixed audio sample rate is too low.")
    return {
        "status": "passed",
        "duration_seconds": round(duration, 3),
        "width": int(video["width"]),
        "height": int(video["height"]),
        "fps": round(frame_rate, 3),
        "video_codec": str(video.get("codec_name") or ""),
        "audio_codec": str(audio.get("codec_name") or ""),
        "audio_sample_rate": int(audio.get("sample_rate") or 0),
        "file_size_bytes": path.stat().st_size,
    }


def render_master_director_video(
    engine: Any,
    director_plan: dict[str, Any],
    shot_images: list[Path],
    audio_path: Path,
    narration_path: Path,
    narration_info: dict[str, Any],
    *,
    project_dir: Path,
    output_video: Path,
    layer_assets: dict[str, dict[str, Path]] | None = None,
    rig_bundle_dir: Path | None = None,
    production_mode: bool = False,
) -> dict[str, Any]:
    """Render a Master Director composition and mix its audio.

    Procedural v3 plans build environments and objects as independent
    vector/Motion elements and use the articulated presenter rig. Legacy v2
    layered-image plans continue through the image-layer renderer.
    """
    from director_shot_renderer import build_director_hyperframes_project
    from procedural_director_renderer import build_procedural_director_project

    root = Path(project_dir).resolve()
    output = Path(output_video).resolve()
    audio = Path(audio_path).resolve(strict=True)
    narration = Path(narration_path).resolve(strict=True)
    root.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)

    render_mode = str(director_plan.get("render_mode") or "layered_images").casefold()
    if render_mode == "procedural_2d":
        if shot_images or layer_assets:
            raise HyperFramesRenderError(
                "Procedural Director mode refuses generated scene plates or cutout image layers."
            )
        project = build_procedural_director_project(
            director_plan,
            root,
            width=int(engine.W),
            height=int(engine.H),
            fps=int(engine.FPS),
            rig_bundle_dir=rig_bundle_dir,
        )
    elif render_mode == "layered_images":
        project = build_director_hyperframes_project(
            director_plan,
            shot_images,
            root,
            layer_assets=layer_assets,
            width=int(engine.W),
            height=int(engine.H),
            fps=int(engine.FPS),
        )
    else:
        raise HyperFramesRenderError("Unsupported Master Director render_mode: " + render_mode)
    duration = float(project["duration_seconds"])

    brand_fonts = engine._ensure_brand_fonts()
    font_assets = root / "assets" / "fonts"
    font_assets.mkdir(parents=True, exist_ok=True)
    for key, filename in (
        ("serif", "DMSerifDisplay-Regular.ttf"),
        ("sans_regular", "DMSans-Regular.ttf"),
        ("sans_medium", "DMSans-Medium.ttf"),
        ("sans_bold", "DMSans-Bold.ttf"),
    ):
        font_source = brand_fonts.get(key) or brand_fonts.get("serif")
        if not font_source:
            raise HyperFramesRenderError("The Master Director render is missing the Violin Prince font bundle.")
        shutil.copy2(Path(font_source).resolve(strict=True), font_assets / filename)

    node = shutil.which("node")
    npm = shutil.which("npm")
    if not node or not npm:
        raise HyperFramesRenderError("Node.js 22+ and npm are required for the Master Director renderer.")
    node_version = _run([node, "--version"], cwd=ANIMATION2D_DIR, timeout=20).stdout.strip()
    try:
        major = int(node_version.lstrip("v").split(".", 1)[0])
    except (TypeError, ValueError) as exc:
        raise HyperFramesRenderError("Unable to read the Node.js version for Master Director rendering.") from exc
    if major < 22:
        raise HyperFramesRenderError("The Master Director renderer requires Node.js 22 or later.")

    hyperframes_cli = ANIMATION2D_DIR / "node_modules" / ".bin" / "hyperframes"
    if not hyperframes_cli.is_file():
        _run([npm, "install", "--no-audit", "--no-fund"], cwd=ANIMATION2D_DIR, timeout=600)
    _build_motion_project(node, root / "project.json", root)

    motion_report_path = root / "motion-report.json"
    if not motion_report_path.is_file():
        raise HyperFramesRenderError("Master Director Motion builder did not emit its motion report.")
    try:
        motion_report = json.loads(motion_report_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HyperFramesRenderError("Master Director Motion report is unreadable.") from exc
    if motion_report.get("status") != "passed":
        raise HyperFramesRenderError("Master Director Motion build did not pass its animation checks.")

    _run([str(hyperframes_cli), "lint"], cwd=root, timeout=180)
    visual_only = root / "director-visual-only.mp4"
    retry_command = [
        str(hyperframes_cli), "render",
        "--output", str(visual_only),
        "--fps", str(engine.FPS),
        "--quality", "standard",
    ]
    from scene_checkpoints import retry_transient
    retry_transient(
        lambda: _run(retry_command, cwd=root, timeout=1800),
        attempts=3,
    )
    visual_qa = _verify_scene_clip(visual_only, engine=engine)
    duration_probe = _run([
        "ffprobe", "-v", "error", "-show_entries", "format=duration",
        "-of", "json", str(visual_only),
    ], cwd=root, timeout=60)
    try:
        visual_duration = float(json.loads(duration_probe.stdout)["format"]["duration"])
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise HyperFramesRenderError("HyperFrames shot render has no valid duration metadata.") from exc
    if abs(visual_duration - duration) > 0.5:
        raise HyperFramesRenderError(
            f"HyperFrames shot render duration {visual_duration:.2f}s does not match "
            f"the {duration:.2f}s Master Director storyboard."
        )

    audio_mix = output.parent / "master-director-audio-mix.wav"
    fade_start = max(0.0, duration - 2.0)
    audio_filter = (
        "[0:a]volume=0.24[bed];"
        "[1:a]highpass=f=75,acompressor=threshold=-20dB:ratio=3:attack=12:release=180,"
        "volume=1.15,asplit=2[voice_sc][voice_mix];"
        "[bed][voice_sc]sidechaincompress=threshold=0.035:ratio=10:attack=18:release=620:"
        "knee=4:makeup=1[ducked];"
        "[ducked][voice_mix]amix=inputs=2:duration=longest:dropout_transition=1,"
        "loudnorm=I=-16:TP=-1.5:LRA=11,afade=t=in:st=0:d=0.5,"
        f"afade=t=out:st={fade_start:.3f}:d=2[aout]"
    )
    _run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-stream_loop", "-1", "-i", str(audio), "-i", str(narration),
        "-filter_complex", audio_filter, "-map", "[aout]",
        "-t", f"{duration:.3f}",
        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(audio_mix),
    ], cwd=output.parent, timeout=360)

    subtitle_path = output.parent / "master-director-narration.ass"
    engine.write_kinetic_ass(
        narration_info.get("subtitle_cues", []),
        subtitle_path,
        narration_info.get("word_cues", []),
    )
    font_dir = Path(brand_fonts.get("serif") or brand_fonts["sans_regular"]).resolve().parent.as_posix()
    _run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(visual_only), "-i", str(audio_mix),
        "-map", "0:v:0", "-map", "1:a:0",
        "-t", f"{duration:.3f}",
        "-vf", f"subtitles={subtitle_path.as_posix()}:fontsdir={font_dir}",
        "-c:v", "libx264", "-preset", "slow", "-crf", "18",
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(output),
    ], cwd=output.parent, timeout=900)

    final_qa = _verify_director_final_video(
        output,
        engine=engine,
        expected_duration=duration,
    )
    execution_notes = sorted({
        str(scene.get("animation_execution_status") or "")
        for scene in project.get("scenes", [])
    })
    report = {
        "status": "passed",
        "renderer": ("Motion + HyperFrames procedural Master Director" if render_mode == "procedural_2d" else "Motion + HyperFrames Master Director layered-image renderer"),
        "render_mode": render_mode,
        "contract_version": project.get("director_contract"),
        "duration_seconds": duration,
        "shot_count": len(project.get("scenes") or []),
        "shot_ids": [str(scene.get("id") or "") for scene in project.get("scenes") or []],
        "camera_movements": [
            str(scene.get("director_camera", {}).get("movement") or "")
            for scene in project.get("scenes") or []
        ],
        "transitions": project.get("director_transition_summary", []),
        "story_palette": project.get("director_palette", {}),
        "music_sync_cues": project.get("director_music_sync_cues", []),
        "motion_report": motion_report,
        "visual_only_qa": visual_qa,
        "final_video_qa": final_qa,
        "animation_execution_status": execution_notes,
        "independent_layer_motion_count": int(motion_report.get("independent_layer_motion_count") or 0),
        "rendered_layer_count": int(motion_report.get("rendered_layer_count") or 0),
        "shot_layer_manifest": project.get("shot_asset_manifest", []),
        "animated_stagecraft_scene_count": int(motion_report.get("animated_stagecraft_scene_count") or 0),
        "animated_stagecraft_node_count": int(motion_report.get("animated_stagecraft_node_count") or 0),
        "animated_stagecraft_object_count": int(motion_report.get("animated_stagecraft_object_count") or 0),
        "animated_presenter_count": int(motion_report.get("animated_presenter_count") or 0),
        "publish_ready": bool(production_mode),
        "production_mode": bool(production_mode),
        "publish_blocker": (
            None if production_mode else (
                "This is an engineering preview. Daily production approvals must pass before public release."
                if render_mode == "procedural_2d"
                else "The automated cinematic image-generation provider is not connected to the scheduled "
                "production workflow yet. This render path accepts and animates verified separated layers, "
                "but the production pipeline still needs to generate and verify those assets automatically."
            )
        ),
        "output": str(output),
    }
    report_path = output.parent / "master-director-render-report.json"
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return report

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
    work_root = Path(engine.WORK).resolve()
    output_root = Path(engine.OUT).resolve()

    from audio_analysis import analyse_audio_file
    from media_verification import verify_scene_assets
    from scene_checkpoints import (
        load_valid_checkpoint,
        retry_transient,
        save_checkpoint,
        scene_fingerprint,
    )
    from scene_timeline import build_scene_timeline
    from scene_director import direct_scene_composition, SceneDirectionError

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
    try:
        visual_direction_report = direct_scene_composition(plan, timeline, narration_info)
    except SceneDirectionError as exc:
        raise HyperFramesRenderError("Scene direction rejected the plan: " + str(exc)) from exc

    media_report = verify_scene_assets(
        scenes, scene_images, total_seconds=24.0, narration_info=narration_info,
        expected_narration_script=plan.get("narration_script"),
    )
    if media_report.get("status") == "failed":
        raise HyperFramesRenderError(
            "Scene media verification failed: " + json.dumps(media_report.get("errors", []))
        )
    (output_root / "scene-media-verification.json").write_text(
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
    (output_root / "character-visual-verification.json").write_text(
        json.dumps(character_visual_reports, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    # Resolve once from the Python runner's repository-root cwd. All scene roots
    # are then absolute, including HyperFrames' cwd and MP4 --output path.
    project_dir = _absolute_scene_project_directory(work_root)
    if project_dir.exists():
        shutil.rmtree(project_dir)
    assets_dir = project_dir / "assets"
    scene_assets_dir = assets_dir / "scenes"
    scene_assets_dir.mkdir(parents=True, exist_ok=True)

    # Embed the approved channel typefaces in each render project so the
    # browser composition and final FFmpeg subtitles share one typography system.
    brand_fonts = engine._ensure_brand_fonts()
    font_assets_dir = assets_dir / "fonts"
    font_assets_dir.mkdir(parents=True, exist_ok=True)
    for key, filename in (
        ("serif", "DMSerifDisplay-Regular.ttf"),
        ("sans_regular", "DMSans-Regular.ttf"),
        ("sans_medium", "DMSans-Medium.ttf"),
        ("sans_bold", "DMSans-Bold.ttf"),
    ):
        # The production font helper supplies all four faces. A minimal serif-only
        # renderer fixture may supply only the required display face; in that case
        # reuse it for the fixture rather than breaking the filesystem contract.
        source_path = brand_fonts.get(key) or brand_fonts.get("serif")
        if not source_path:
            raise HyperFramesRenderError("The Violin Prince brand font bundle is incomplete.")
        shutil.copy2(Path(source_path).resolve(strict=True), font_assets_dir / filename)

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
            "graphic_label": str(scene.get("graphic_label") or ""),
            "graphic_detail": str(scene.get("graphic_detail") or ""),
            "editorial_index": index + 1,
            "editorial_total": len(scenes),
            "visual_mode": str(scene.get("visual_mode") or ""),
            "character_actions": scene.get("character_actions") or {},
            "graphic_data": scene.get("graphic_data"),
            "visual_composition": scene.get("visual_composition") or {},
            "narration_sentence_indexes": timing["narration_sentence_indexes"],
        })

    project_data = {
        "title": str(plan.get("title") or "Violin Prince"),
        "width": int(engine.W),
        "height": int(engine.H),
        "fps": int(engine.FPS),
        "duration_seconds": 24.0,
        "brand_system": "violin-prince-premium-editorial-v3",
        "brand": {"name": "VIOLIN PRINCE", "palette": ["midnight-navy", "oxidised-teal", "antique-brass", "warm-ivory"]},
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
    cache_root = work_root / "scene-render-cache"
    cache_root.mkdir(parents=True, exist_ok=True)
    scene_clips: list[Path] = []
    scene_cache_records = []
    motion_reports = []
    motion_report_cache = cache_root / "motion-reports"
    motion_report_cache.mkdir(parents=True, exist_ok=True)
    for index, (scene, image_path, staged_scene) in enumerate(zip(scenes, scene_images, staged_scenes)):
        scene_id = str(scene["id"])
        timing = timeline_by_id[scene_id]
        scene_root = project_dir / "render-scenes" / scene_id
        scene_root.mkdir(parents=True, exist_ok=True)
        scene_fingerprint_value = scene_fingerprint(
            scene,
            image_path,
            renderer_version="motion-hyperframes-per-scene-v3-premium-editorial-composition",
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
                "character_actions": scene.get("character_actions") or {},
                "visual_mode": str(scene.get("visual_mode") or ""),
                "graphic_data": scene.get("graphic_data"),
                "visual_composition": scene.get("visual_composition") or {},
                "caption_renderer": "kinetic-ass-premium-v2",
                "brand_system": "violin-prince-premium-editorial-v3",
            },
        )
        cached = load_valid_checkpoint(cache_root, scene_id, scene_fingerprint_value)
        cached_motion_report = motion_report_cache / f"{scene_id}.json"
        if cached and cached_motion_report.is_file():
            try:
                cached_report = json.loads(cached_motion_report.read_text(encoding="utf-8"))
                _validate_scene_motion_report(scene, cached_report)
            except (OSError, ValueError, json.JSONDecodeError):
                cached = None
            else:
                scene_clips.append(cached)
                motion_reports.append(cached_report)
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
        _build_motion_project(node, scene_project, scene_root)
        report_path = scene_root / "motion-report.json"
        if not report_path.is_file():
            raise HyperFramesRenderError(
                f"Motion builder did not emit its required scene report for {scene_id}."
            )
        try:
            scene_motion_report = json.loads(report_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise HyperFramesRenderError(
                f"Motion builder emitted an unreadable scene report for {scene_id}."
            ) from exc
        _validate_scene_motion_report(scene, scene_motion_report)
        cached_motion_report.write_text(
            json.dumps(scene_motion_report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        motion_reports.append(scene_motion_report)
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
    picture_only = output_root / "hyperframes-picture.mp4"
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
        "-t", "24", "-an", "-c:v", "libx264", "-preset", "medium",
        "-crf", "19", "-pix_fmt", "yuv420p", str(picture_only),
    ], cwd=work_root, timeout=900)
    if not picture_only.is_file() or picture_only.stat().st_size < 4096:
        raise HyperFramesRenderError("FFmpeg did not assemble the cached scene clips.")

    audio_path = Path(audio_path).resolve(strict=True)
    narration_path = Path(narration_path).resolve(strict=True)
    audio_mix = output_root / "daily-audio-mix.wav"
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
    ], cwd=work_root, timeout=240)

    subtitle_path = output_root / "narration.ass"
    engine.write_kinetic_ass(
        narration_info.get("subtitle_cues", []),
        subtitle_path,
        narration_info.get("word_cues", []),
    )
    font_dir = Path(engine._ensure_brand_fonts()["serif"]).parent.as_posix()
    final_video = output_root / "violin-prince-short.mp4"
    _run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(picture_only), "-i", str(audio_mix),
        "-map", "0:v:0", "-map", "1:a:0",
        "-t", "24",
        "-vf", f"subtitles={subtitle_path.as_posix()}:fontsdir={font_dir}",
        "-c:v", "libx264", "-preset", "slow", "-crf", "18",
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-level", "4.1",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart", str(final_video),
    ], cwd=work_root, timeout=600)

    quality = engine.validate_final_video(final_video)
    sample_points = [("OPEN", 0.55)]
    for index, timing in enumerate(timeline["scenes"]):
        sample_points.append((
            f"SCENE {index + 1}",
            min(23.65, max(0.1, float(timing["start"]) + float(timing["duration"]) * 0.55)),
        ))
    sample_points.append(("FINAL FRAME", 23.30))
    contact_sheet = engine.make_render_contact_sheet(
        final_video, output_root / "visual-contact-sheet.png", sample_points
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
        "visual_direction": visual_direction_report,
        "motion_graphics": {
            "status": "passed",
            "scene_reports": motion_reports,
            "animated_graphic_scene_count": sum(
                1 for item in motion_reports
                if int(item.get("animated_graphic_item_count") or 0) > 0
            ),
            "animated_graphic_item_count": sum(
                int(item.get("animated_graphic_item_count") or 0)
                for item in motion_reports
            ),
            "animated_presenter_count": sum(
                int(item.get("animated_presenter_count") or 0)
                for item in motion_reports
            ),
        },
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
        "finishing": "premium typography, cinematic grade, narration-led captions, high-quality H.264 export, AAC 192k audio and independent media QA",
        "visual_finish": {"brand_system": "violin-prince-premium-editorial-v3", "typefaces_embedded": True, "video_crf": 18, "video_preset": "slow", "audio_bitrate": "192k"},
        "publishing": "disabled in GitHub Actions; release handoff only",
    })
    (output_root / "quality_report.json").write_text(
        json.dumps(quality, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return quality
