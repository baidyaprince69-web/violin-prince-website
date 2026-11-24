"""Preview-only multi-layer video compositor for Violin Prince."""
from __future__ import annotations
import argparse
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont
from typing import Any


class CompositionError(RuntimeError):
    """Invalid timeline or failed media render."""


_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_HEX = re.compile(r"^#?[0-9a-fA-F]{6}$")


def _number(value: Any, name: str, low: float, high: float) -> float:
    if isinstance(value, bool):
        raise CompositionError(f"{name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise CompositionError(f"{name} must be numeric") from exc
    if not math.isfinite(result) or result < low or result > high:
        raise CompositionError(f"{name} must be between {low} and {high}")
    return result


def _path(raw: Any, root: Path, label: str) -> Path:
    if not isinstance(raw, str) or not raw.strip():
        raise CompositionError(f"{label} requires a media path")
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        return candidate.resolve(strict=True)
    except OSError as exc:
        raise CompositionError(f"{label} media file does not exist: {raw}") from exc


def validate_timeline(data: dict[str, Any], root: str | Path) -> dict[str, Any]:
    """Validate a JSON timeline and resolve every media path."""
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise CompositionError("Timeline must have schema_version=1")
    if data.get("preview_only") is not True or data.get("publish_enabled") is not False:
        raise CompositionError("This renderer only accepts preview_only=true and publish_enabled=false")
    base_dir = Path(root).resolve()
    width = int(_number(data.get("width", 720), "width", 2, 4096))
    height = int(_number(data.get("height", 1280), "height", 2, 4096))
    fps = int(_number(data.get("fps", 25), "fps", 1, 60))
    if width % 2 or height % 2:
        raise CompositionError("H.264 canvas dimensions must be even")
    duration = _number(data.get("duration_seconds"), "duration_seconds", 0.5, 600)

    raw_layers = data.get("video_layers")
    if not isinstance(raw_layers, list) or not raw_layers:
        raise CompositionError("At least one video layer is required")
    layers, ids = [], set()
    for i, item in enumerate(raw_layers):
        if not isinstance(item, dict):
            raise CompositionError(f"Video layer {i+1} must be an object")
        ident = str(item.get("id") or "").casefold()
        if not _ID.fullmatch(ident) or ident in ids:
            raise CompositionError(f"Invalid or duplicate video layer id: {ident}")
        ids.add(ident)
        kind = str(item.get("kind") or "video").casefold()
        if kind not in {"video", "image"}:
            raise CompositionError(f"{ident}: kind must be video or image")
        start = _number(item.get("start_seconds", 0), f"{ident}.start_seconds", 0, duration)
        end = _number(item.get("end_seconds", duration), f"{ident}.end_seconds", 0.01, duration)
        if end <= start:
            raise CompositionError(f"{ident}: end_seconds must be after start_seconds")
        w = int(_number(item.get("width", width), f"{ident}.width", 2, width*2))
        h = int(_number(item.get("height", height), f"{ident}.height", 2, height*2))
        if w % 2 or h % 2:
            raise CompositionError(f"{ident}: layer dimensions must be even")
        fit = str(item.get("fit") or "contain").casefold()
        if fit not in {"contain", "cover", "stretch"}:
            raise CompositionError(f"{ident}: fit must be contain, cover or stretch")
        crop = item.get("camera_crop")
        if crop is not None:
            if not isinstance(crop, dict):
                raise CompositionError(f"{ident}: camera_crop must be an object")
            crop_values = {
                key: _number(crop.get(key), f"{ident}.camera_crop.{key}", 0.01 if key in {"width", "height"} else 0, 1)
                for key in ("x", "y", "width", "height")
            }
            if crop_values["x"] + crop_values["width"] > 1.000001 or crop_values["y"] + crop_values["height"] > 1.000001:
                raise CompositionError(f"{ident}: camera_crop must remain inside the source frame")
        else:
            crop_values = None
        grade = item.get("grade")
        if grade is not None and not isinstance(grade, dict):
            raise CompositionError(f"{ident}: grade must be an object")
        grade_values = None if grade is None else {
            "contrast": _number(grade.get("contrast", 1), f"{ident}.grade.contrast", 0.5, 2),
            "saturation": _number(grade.get("saturation", 1), f"{ident}.grade.saturation", 0, 2),
            "brightness": _number(grade.get("brightness", 0), f"{ident}.grade.brightness", -1, 1),
            "gamma": _number(grade.get("gamma", 1), f"{ident}.grade.gamma", 0.1, 3),
        }
        framing = str(item.get("camera_framing") or "").casefold()
        allowed_framings = {"full_body_wide", "medium_performance", "instrument_hands_close_up", "face_close_up"}
        if framing and framing not in allowed_framings:
            raise CompositionError(f"{ident}: unsupported camera_framing {framing}")
        shot_id = str(item.get("shot_id") or "")
        if shot_id and not _ID.fullmatch(shot_id):
            raise CompositionError(f"{ident}: invalid shot_id")
        raw_move = item.get("camera_move")
        if raw_move is not None and not isinstance(raw_move, dict):
            raise CompositionError(f"{ident}: camera_move must be an object")
        move_type = str((raw_move or {}).get("type") or "locked").casefold()
        allowed_moves = {"locked", "push_in", "pull_out", "pan_left", "pan_right", "tilt_up", "tilt_down", "handheld"}
        if move_type not in allowed_moves:
            raise CompositionError(f"{ident}: unsupported camera_move {move_type}")
        camera_move = None if raw_move is None or move_type == "locked" else {
            "type": move_type,
            "intensity": _number(raw_move.get("intensity", 0.5), f"{ident}.camera_move.intensity", 0, 1),
        }
        layers.append({
            "id": ident, "kind": kind, "path": _path(item.get("path"), base_dir, ident),
            "start": start, "end": end, "length": end-start,
            "source_in": _number(item.get("source_in_seconds", 0), f"{ident}.source_in_seconds", 0, 600),
            "x": int(_number(item.get("x", 0), f"{ident}.x", -width, width)),
            "y": int(_number(item.get("y", 0), f"{ident}.y", -height, height)),
            "width": w, "height": h, "fit": fit,
            "opacity": _number(item.get("opacity", 1), f"{ident}.opacity", 0, 1),
            "fade_in": _number(item.get("fade_in_seconds", 0), f"{ident}.fade_in_seconds", 0, end-start),
            "fade_out": _number(item.get("fade_out_seconds", 0), f"{ident}.fade_out_seconds", 0, end-start),
            "role": str(item.get("role") or ("base" if i == 0 else "overlay")),
            "camera_crop": crop_values, "camera_framing": framing,
            "camera_move": camera_move,
            "shot_id": shot_id, "shot_label": str(item.get("shot_label") or ""),
            "grade": grade_values,
        })
    first = layers[0]
    if first["start"] != 0 or first["end"] < duration - 1e-6:
        raise CompositionError("First video layer must cover the complete timeline")
    if (first["x"], first["y"], first["width"], first["height"]) != (0, 0, width, height):
        raise CompositionError("First video layer must fill the output canvas")

    text_layers, text_items = [], data.get("text_layers", [])
    if not isinstance(text_items, list):
        raise CompositionError("text_layers must be an array")
    for i, item in enumerate(text_items):
        if not isinstance(item, dict):
            raise CompositionError(f"Text layer {i+1} must be an object")
        ident = str(item.get("id") or f"text-{i+1}").casefold()
        if not _ID.fullmatch(ident) or ident in ids:
            raise CompositionError(f"Invalid or duplicate text layer id: {ident}")
        ids.add(ident)
        content = str(item.get("text") or "")
        if not content or len(content) > 240:
            raise CompositionError(f"{ident}: text must contain 1–240 characters")
        start = _number(item.get("start_seconds", 0), f"{ident}.start_seconds", 0, duration)
        end = _number(item.get("end_seconds", duration), f"{ident}.end_seconds", 0.01, duration)
        if end <= start:
            raise CompositionError(f"{ident}: invalid time range")
        color = str(item.get("color") or "#FFFFFF")
        if not _HEX.fullmatch(color):
            raise CompositionError(f"{ident}: color must be a six-digit hex value")
        fade_in = _number(item.get("fade_in_seconds", 0), f"{ident}.fade_in_seconds", 0, end-start)
        fade_out = _number(item.get("fade_out_seconds", 0), f"{ident}.fade_out_seconds", 0, end-start)
        text_layers.append({
            "id": ident, "text": content, "start": start, "end": end, "fade_in": fade_in, "fade_out": fade_out,
            "x": int(item.get("x", 40)), "y": int(item.get("y", height-170)),
            "size": int(_number(item.get("font_size", 40), f"{ident}.font_size", 10, 180)),
            "color": "0x"+color.lstrip("#").upper(),
            "alpha": _number(item.get("alpha", 1), f"{ident}.alpha", 0, 1),
            "border": int(_number(item.get("border_width", 0), f"{ident}.border_width", 0, 8)),
        })

    raw_audio = data.get("audio_tracks")
    if not isinstance(raw_audio, list) or not raw_audio:
        raise CompositionError("At least one voice audio track is required")
    audio, voice_count, private = [], 0, False
    for i, item in enumerate(raw_audio):
        if not isinstance(item, dict):
            raise CompositionError(f"Audio track {i+1} must be an object")
        ident = str(item.get("id") or "").casefold()
        role = str(item.get("role") or "").casefold()
        if not _ID.fullmatch(ident) or ident in ids:
            raise CompositionError(f"Invalid or duplicate audio track id: {ident}")
        ids.add(ident)
        if role not in {"voice", "music", "sfx"}:
            raise CompositionError(f"{ident}: role must be voice, music or sfx")
        voice_count += int(role == "voice")
        start = _number(item.get("start_seconds", 0), f"{ident}.start_seconds", 0, duration)
        end = _number(item.get("end_seconds", duration), f"{ident}.end_seconds", 0.01, duration)
        if end <= start:
            raise CompositionError(f"{ident}: invalid time range")
        length = end-start
        is_private = item.get("private_source") is True
        private = private or is_private
        audio.append({
            "id": ident, "role": role, "path": _path(item.get("path"), base_dir, ident),
            "start": start, "end": end, "length": length,
            "source_in": _number(item.get("source_in_seconds", 0), f"{ident}.source_in_seconds", 0, 600),
            "gain": 10 ** (_number(item.get("gain_db", 0), f"{ident}.gain_db", -48, 18)/20),
            "fade_in": _number(item.get("fade_in_seconds", 0), f"{ident}.fade_in_seconds", 0, length),
            "fade_out": _number(item.get("fade_out_seconds", 0), f"{ident}.fade_out_seconds", 0, length),
            "loop": item.get("loop") is True, "private": is_private,
        })
    if voice_count == 0:
        raise CompositionError("At least one track with role='voice' is required")
    return {
        "width": width, "height": height, "fps": fps, "duration": duration,
        "layers": layers, "text": text_layers, "audio": audio, "private": private,
        "title": str(data.get("title") or "Violin Prince cinematic preview"),
    }


def _run(command: list[str], cwd: Path, timeout: int = 900) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, cwd=cwd, check=True, capture_output=True,
                              text=True, timeout=timeout)
    except FileNotFoundError as exc:
        raise CompositionError(f"Required media tool not found: {command[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or str(exc))[-4000:]
        raise CompositionError(f"Media render failed: {detail}") from exc
    except subprocess.TimeoutExpired as exc:
        raise CompositionError(f"Media render timed out: {command[0]}") from exc


def _probe(path: Path, ffprobe: str, cwd: Path) -> dict[str, Any]:
    result = _run([ffprobe, "-v", "error", "-show_entries",
        "format=duration:stream=codec_type,codec_name,width,height,avg_frame_rate,sample_rate,channels",
        "-of", "json", str(path)], cwd, 90)
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CompositionError(f"FFprobe returned invalid metadata for {path.name}") from exc


def _esc(text: str) -> str:
    return (text.replace("\\", "\\\\").replace("'", "\\'").replace(":", "\\:")
            .replace(",", "\\,").replace("%", "\\%").replace("[", "\\[")
            .replace("]", "\\]").replace(";", "\\;"))


def _camera_crop(layer: dict[str, Any]) -> str:
    crop = layer.get("camera_crop")
    if not crop:
        return ""
    x, y, width, height = (crop[key] for key in ("x", "y", "width", "height"))
    # Keep the crop aligned to even pixels for stable H.264 4:2:0 output.
    return (
        f"crop=w=trunc(iw*{width:.6f}/2)*2:h=trunc(ih*{height:.6f}/2)*2:"
        f"x=trunc(iw*{x:.6f}/2)*2:y=trunc(ih*{y:.6f}/2)*2"
    )


def _grade(layer: dict[str, Any]) -> str:
    grade = layer.get("grade")
    if not grade:
        return ""
    return (
        f"eq=contrast={grade['contrast']:.4f}:saturation={grade['saturation']:.4f}:"
        f"brightness={grade['brightness']:.4f}:gamma={grade['gamma']:.4f}"
    )


def _camera_move(layer: dict[str, Any], fps: int) -> str:
    """Compile a bounded frame-seekable camera move over a trimmed shot."""
    move = layer.get("camera_move")
    if not move:
        return ""
    kind, intensity = move["type"], move["intensity"]
    width, height = layer["width"], layer["height"]
    frames = max(2, int(round(layer["length"] * fps)))
    progress = f"on/{frames - 1}"
    delta = 0.14 * intensity
    if kind == "push_in":
        zoom = f"1+{delta:.5f}*{progress}"
        x = "(iw-iw/zoom)/2"
        y = "(ih-ih/zoom)/2"
    elif kind == "pull_out":
        zoom = f"1+{delta:.5f}*(1-{progress})"
        x = "(iw-iw/zoom)/2"
        y = "(ih-ih/zoom)/2"
    elif kind in {"pan_left", "pan_right"}:
        zoom = f"1+{0.12 * intensity:.5f}"
        travel = f"0.82*(1-({progress}))" if kind == "pan_left" else f"0.82*({progress})"
        x = f"(iw-iw/zoom)*(0.09+{travel})"
        y = "(ih-ih/zoom)/2"
    elif kind in {"tilt_up", "tilt_down"}:
        zoom = f"1+{0.12 * intensity:.5f}"
        travel = f"0.82*({progress})" if kind == "tilt_down" else f"0.82*(1-({progress}))"
        x = "(iw-iw/zoom)/2"
        y = f"(ih-ih/zoom)*(0.09+{travel})"
    else:
        # Deterministic low-amplitude camera drift; no per-frame random jitter.
        zoom = f"1+{0.025 * intensity:.5f}"
        amplitude = 2.0 + 9.0 * intensity
        x = f"(iw-iw/zoom)/2+{amplitude:.3f}*sin(on*0.11)"
        y = f"(ih-ih/zoom)/2+{amplitude * 0.72:.3f}*sin(on*0.15)"
    return f"zoompan=z='{zoom}':x='{x}':y='{y}':d=1:s={width}x{height}:fps={fps}"


def _scale(layer: dict[str, Any]) -> str:
    w, h, fit = layer["width"], layer["height"], layer["fit"]
    if fit == "stretch":
        return f"scale={w}:{h},setsar=1"
    if fit == "cover":
        return f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},setsar=1"
    return f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2:color=black@0,setsar=1"


def _filtergraph(t: dict[str, Any], audio_offset: int) -> str:
    d, fps = t["duration"], t["fps"]
    base = t["layers"][0]
    base_filters = [
        f"[0:v]trim=start={base['source_in']:.4f}:duration={d:.4f},setpts=PTS-STARTPTS,fps={fps}"
    ]
    for expression in (_camera_crop(base), _scale(base), _grade(base), _camera_move(base, fps)):
        if expression:
            base_filters.append(expression)
    base_filters.append("format=yuv420p[v0]")
    filters = [",".join(base_filters)]
    current = "v0"
    for n, layer in enumerate(t["layers"][1:], 1):
        start, end = layer["start"], layer["end"]
        video_steps = [
            f"[{n}:v]trim=start={layer['source_in']:.4f}:duration={layer['length']:.4f}",
            "setpts=PTS-STARTPTS",
        ]
        for expression in (_camera_crop(layer), _scale(layer), _grade(layer),
                           _camera_move(layer, fps), "format=rgba"):
            if expression:
                video_steps.append(expression)
        video_steps.append(f"colorchannelmixer=aa={layer['opacity']:.4f}")
        video_chain = ",".join(video_steps)
        if layer.get("fade_in", 0):
            video_chain += f",fade=t=in:st=0:d={layer['fade_in']:.4f}:alpha=1"
        if layer.get("fade_out", 0):
            fade_start = max(0.0, layer["length"]-layer["fade_out"])
            video_chain += f",fade=t=out:st={fade_start:.4f}:d={layer['fade_out']:.4f}:alpha=1"
        video_chain += f",setpts=PTS+{start:.4f}/TB"
        filters.append(video_chain + f"[ov{n}]")
        out = f"v{n}"
        filters.append(
            f"[{current}][ov{n}]overlay=x={layer['x']}:y={layer['y']}:eof_action=pass:"
            f"shortest=0:repeatlast=0:enable='between(t,{start:.4f},{end:.4f})'[{out}]"
        )
        current = out
    filters.append(f"[{current}]format=yuv420p[vout]")

    groups: dict[str, list[str]] = {"voice": [], "music": [], "sfx": []}
    for n, track in enumerate(t["audio"]):
        idx = audio_offset+n
        start, end = track["start"], track["end"]
        delay = int(round(start*1000))
        steps = [
            f"[{idx}:a]aresample=48000",
            f"atrim=start={track['source_in']:.4f}:duration={track['length']:.4f}",
            "asetpts=PTS-STARTPTS", f"volume={track['gain']:.6f}",
            f"adelay={delay}:all=1",
        ]
        if track["fade_in"]:
            steps.append(f"afade=t=in:st={start:.4f}:d={track['fade_in']:.4f}")
        if track["fade_out"]:
            steps.append(f"afade=t=out:st={end-track['fade_out']:.4f}:d={track['fade_out']:.4f}")
        steps.extend([f"apad=whole_dur={d:.4f}", f"atrim=duration={d:.4f}[a{n}]"])
        filters.append(",".join(steps))
        groups[track["role"]].append(f"a{n}")

    def mix(labels: list[str], out: str) -> str | None:
        if not labels:
            return None
        if len(labels) == 1:
            filters.append(f"[{labels[0]}]anull[{out}]")
        else:
            inputs = "".join(f"[{x}]" for x in labels)
            filters.append(f"{inputs}amix=inputs={len(labels)}:duration=longest:dropout_transition=0:normalize=0[{out}]")
        return out

    voice = mix(groups["voice"], "voicebus")
    music = mix(groups["music"], "musicbus")
    sfx = mix(groups["sfx"], "sfxbus")
    final = []
    filters.append("[voicebus]highpass=f=70,acompressor=threshold=-20dB:ratio=2.5:attack=10:release=180,asplit=2[voiceforduck][voiceformix]")
    final.append("voiceformix")
    if music:
        filters.append("[musicbus][voiceforduck]sidechaincompress=threshold=0.025:ratio=8:attack=20:release=520:knee=4:makeup=1[musicducked]")
        final.append("musicducked")
    if sfx:
        final.append("sfxbus")
    inputs = "".join(f"[{x}]" for x in final)
    filters.append(f"{inputs}amix=inputs={len(final)}:duration=longest:dropout_transition=0:normalize=0,alimiter=limit=0.95,atrim=duration={d:.4f}[aout]")
    return ";".join(filters)


def _rasterize_text_layers(t: dict[str, Any], destination: Path) -> list[dict[str, Any]]:
    """Rasterise title/caption layers so text works with FFmpeg builds lacking drawtext."""
    records = []
    width, height = t["width"], t["height"]
    for item in t["text"]:
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)
        font_candidates = [
            Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
            Path("/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf"),
            Path("/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf"),
        ]
        font_path = next((value for value in font_candidates if value.is_file()), None)
        try:
            font = ImageFont.truetype(str(font_path), item["size"]) if font_path else ImageFont.load_default()
        except OSError:
            font = ImageFont.load_default()
        hex_value = item["color"].removeprefix("0x")
        rgb = tuple(int(hex_value[index:index+2], 16) for index in (0, 2, 4))
        alpha = round(item["alpha"] * 255)
        draw.text(
            (item["x"], item["y"]),
            item["text"],
            font=font,
            fill=(*rgb, alpha),
            stroke_width=item["border"],
            stroke_fill=(0, 0, 0, round(0.58 * alpha)),
            spacing=max(2, round(item["size"] * 0.18)),
        )
        image_path = destination / f".vp-text-layer-{item['id']}.png"
        canvas.save(image_path)
        records.append({
            "id": item["id"], "kind": "image", "path": image_path,
            "start": item["start"], "end": item["end"],
            "length": item["end"]-item["start"], "source_in": 0.0,
            "x": 0, "y": 0, "width": width, "height": height,
            "fit": "stretch", "opacity": 1.0,
            "fade_in": item["fade_in"], "fade_out": item["fade_out"],
            "role": "text",
            "camera_crop": None, "camera_framing": "", "camera_move": None,
            "shot_id": "", "shot_label": "", "grade": None,
        })
    return records


def compose_video(manifest_path: str | Path, output_path: str | Path,
                  report_path: str | Path | None = None) -> dict[str, Any]:
    manifest = Path(manifest_path).expanduser().resolve(strict=True)
    output = Path(output_path).expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CompositionError("Timeline manifest is not readable JSON") from exc
    t = validate_timeline(data, manifest.parent)
    text_layer_report = list(t["text"])
    t["layers"].extend(_rasterize_text_layers(t, output.parent))
    t["text"] = []
    ffmpeg, ffprobe = shutil.which("ffmpeg"), shutil.which("ffprobe")
    if not ffmpeg or not ffprobe:
        raise CompositionError("FFmpeg and FFprobe must be installed on PATH")

    for layer in t["layers"]:
        meta = _probe(layer["path"], ffprobe, output.parent)
        video = next((s for s in meta.get("streams", []) if s.get("codec_type") == "video"), None)
        if not video:
            raise CompositionError(f"Video layer {layer['id']} has no video stream")
        if layer["kind"] == "video":
            source_duration = float((meta.get("format") or {}).get("duration") or 0)
            if source_duration + 0.02 < layer["source_in"] + layer["length"]:
                raise CompositionError(f"Video layer {layer['id']} is shorter than its requested time range")

    args = []
    for layer in t["layers"]:
        if layer["kind"] == "image":
            args += ["-loop", "1", "-t", f"{t['duration']:.4f}", "-i", str(layer["path"])]
        else:
            args += ["-i", str(layer["path"])]
    audio_offset = len(t["layers"])
    for track in t["audio"]:
        if track["loop"]:
            args += ["-stream_loop", "-1"]
        args += ["-i", str(track["path"])]

    graph = _filtergraph(t, audio_offset)
    _run([
        ffmpeg, "-y", "-hide_banner", "-loglevel", "error", *args,
        "-filter_complex", graph, "-map", "[vout]", "-map", "[aout]",
        "-t", f"{t['duration']:.4f}", "-r", str(t["fps"]),
        "-c:v", "libx264", "-preset", "medium", "-crf", "19",
        "-pix_fmt", "yuv420p", "-profile:v", "high", "-c:a", "aac",
        "-b:a", "192k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart",
        str(output),
    ], output.parent, 1800)

    final = _probe(output, ffprobe, output.parent)
    streams = final.get("streams") or []
    video = next((s for s in streams if s.get("codec_type") == "video"), None)
    audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
    measured = float((final.get("format") or {}).get("duration") or 0)
    if not video or not audio:
        raise CompositionError("Rendered video must contain video and mixed audio streams")
    if (int(video.get("width", 0)), int(video.get("height", 0))) != (t["width"], t["height"]):
        raise CompositionError("Rendered dimensions do not match the timeline")
    if video.get("codec_name") != "h264" or audio.get("codec_name") != "aac":
        raise CompositionError("Output codecs must be H.264 video and AAC audio")
    if abs(measured-t["duration"]) > max(0.12, 1.5/t["fps"]):
        raise CompositionError("Rendered duration does not match the timeline")
    try:
        num, den = str(video.get("avg_frame_rate", "0/1")).split("/")
        measured_fps = float(num)/float(den)
    except (ValueError, ZeroDivisionError):
        measured_fps = 0.0
    if abs(measured_fps-t["fps"]) > 0.1:
        raise CompositionError("Rendered frame rate does not match the timeline")

    report = {
        "status": "passed", "preview_only": True, "publish_enabled": False,
        "publish_ready": False, "private_media": t["private"],
        "public_artifact_allowed": not t["private"], "title": t["title"],
        "output": str(output), "file_size_bytes": output.stat().st_size,
        "duration_seconds": round(measured, 3), "width": t["width"], "height": t["height"],
        "fps": round(measured_fps, 3), "video_codec": "h264", "audio_codec": "aac",
        "audio_sample_rate": int(audio.get("sample_rate") or 0),
        "video_layers": [{"id": x["id"], "role": x["role"], "kind": x["kind"],
                          "start_seconds": x["start"], "end_seconds": x["end"],
                          "shot_id": x["shot_id"], "shot_label": x["shot_label"],
                          "camera_framing": x["camera_framing"],
                          "camera_crop": x["camera_crop"], "camera_move": x["camera_move"],
                          "grade": x["grade"]} for x in t["layers"]],
        "camera_shots": [
            {"shot_id": x["shot_id"], "label": x["shot_label"], "framing": x["camera_framing"],
             "start_seconds": x["start"], "end_seconds": x["end"],
             "camera_crop": x["camera_crop"], "camera_move": x["camera_move"]}
            for x in t["layers"] if x["camera_framing"]
        ],
        "camera_shot_count": len([x for x in t["layers"] if x["camera_framing"]]),
        "camera_moves": [
            {"layer_id": x["id"], "shot_id": x["shot_id"], "type": x["camera_move"]["type"],
             "intensity": x["camera_move"]["intensity"], "duration_seconds": x["length"]}
            for x in t["layers"] if x["camera_move"]
        ],
        "camera_move_count": len([x for x in t["layers"] if x["camera_move"]]),
        "distinct_camera_framings": sorted({x["camera_framing"] for x in t["layers"] if x["camera_framing"]}),
        "text_layers": [{"id": x["id"], "start_seconds": x["start"], "end_seconds": x["end"],
                         "fade_in_seconds": x["fade_in"], "fade_out_seconds": x["fade_out"]}
                        for x in text_layer_report],
        "audio_tracks": [{"id": x["id"], "role": x["role"], "private_source": x["private"]} for x in t["audio"]],
        "audio_mix": {"voice_present": True,
                      "music_present": any(x["role"] == "music" for x in t["audio"]),
                      "sfx_present": any(x["role"] == "sfx" for x in t["audio"]),
                      "music_ducking": any(x["role"] == "music" for x in t["audio"])},
    }
    report_file = Path(report_path).expanduser().resolve() if report_path else output.with_suffix(".report.json")
    report_file.parent.mkdir(parents=True, exist_ok=True)
    report_file.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Compose a preview-only Violin Prince cinematic video.")
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--report")
    args = parser.parse_args()
    try:
        result = compose_video(args.manifest, args.output, args.report)
        print("CINEMATIC_COMPOSITION_REPORT="+json.dumps(result, ensure_ascii=False), flush=True)
        return 0
    except Exception as exc:
        print("Cinematic composition stopped safely: "+str(exc)[:1800], file=sys.stderr, flush=True)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
