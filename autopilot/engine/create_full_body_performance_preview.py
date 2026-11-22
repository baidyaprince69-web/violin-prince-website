#!/usr/bin/env python3
"""Build a non-publishing Motion project for the full-body violin rig preview."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any


def stage_asset(bundle: Path, asset_root: Path, source: str) -> str:
    source_path = (bundle / str(source)).resolve(strict=True)
    if bundle.resolve() not in source_path.parents:
        raise ValueError(f"Character asset path escapes its rig bundle: {source}")
    destination = asset_root / source_path.name
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source_path, destination)
    return destination.relative_to(asset_root.parent.parent.parent).as_posix()


def _build_preview_music_sync(
    duration_seconds: float,
    *,
    bpm: float | None = 100.0,
    audio_path: str | Path | None = None,
    music_map: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a validated beat map from real audio, or an explicitly labelled preview grid."""
    duration = float(duration_seconds)
    if not 0 < duration <= 600:
        raise ValueError("Music-sync duration must be between zero and 600 seconds.")

    if audio_path:
        from audio_analysis import analyse_audio_file

        if music_map is not None:
            required = ("bpm", "beat_times", "downbeats", "onsets")
            missing = [key for key in required if key not in music_map]
            if missing:
                raise ValueError(
                    "The supplied sampled-violin event map is missing: "
                    + ", ".join(missing)
                )
            if float(music_map.get("duration_seconds", 0)) < duration:
                raise ValueError("The sampled-violin event map is shorter than the preview.")
            analysis = analyse_audio_file(
                audio_path,
                known_bpm=float(music_map["bpm"]),
                known_beat_times=music_map["beat_times"],
                known_downbeats=music_map["downbeats"],
                known_onsets=music_map["onsets"],
            )
        else:
            analysis = analyse_audio_file(audio_path, known_bpm=bpm)
        beats = [
            float(value) for value in analysis.get("beat_times", [])
            if 0 <= float(value) < duration
        ]
        downbeats = [
            float(value) for value in analysis.get("downbeats", [])
            if 0 <= float(value) < duration
        ]
        onsets = [
            float(value) for value in analysis.get("onsets", [])
            if 0 <= float(value) < duration
        ]
        if analysis.get("status") == "low_confidence" or len(beats) < 2:
            raise ValueError(
                "Audio beat analysis did not produce a reliable beat map. "
                "Supply a clearer audio source or a verified BPM."
            )
        if not onsets and beats:
            beat_period = 60.0 / float(analysis["bpm"])
            onsets = [
                round(time + beat_period * 0.5, 4)
                for time in beats
                if time + beat_period * 0.5 < duration
            ]
        return {
            "status": analysis.get("status", "analysed"),
            "source": (
                music_map.get("audio_source", "decoded_audio")
                if music_map is not None else
                analysis.get("source", "decoded_audio")
            ),
            "audio_attached": True,
            "bpm": float(analysis["bpm"]),
            "confidence": float(analysis.get("confidence", 0.0)),
            "duration_seconds": duration,
            "beat_times": [round(value, 4) for value in beats],
            "downbeats": [round(value, 4) for value in downbeats],
            "onsets": [round(value, 4) for value in onsets],
            "audio_license": music_map.get("license") if music_map is not None else None,
            "audio_attribution": music_map.get("attribution") if music_map is not None else None,
            "event_map_source": (
                "sampled_violin_arrangement_note_events"
                if music_map is not None else None
            ),
            "analysis_status": analysis.get("status"),
            "analysis_source": analysis.get("source"),
            "decode_backend": analysis.get("decode_backend"),
            "decoded_audio_duration_seconds": analysis.get("duration_seconds"),
        }

    tempo = 100.0 if bpm is None else float(bpm)
    if not 40 <= tempo <= 240:
        raise ValueError("Preview BPM must be between 40 and 240.")
    period = 60.0 / tempo
    count = int(duration / period) + 1
    beats = [round(index * period, 4) for index in range(count) if index * period < duration]
    onsets = [
        round(time + period * 0.5, 4)
        for time in beats
        if time + period * 0.5 < duration
    ]
    return {
        "status": "preview_grid",
        "source": "preview_tempo_grid_no_audio_asset",
        "audio_attached": False,
        "bpm": tempo,
        "confidence": 1.0,
        "duration_seconds": duration,
        "beat_times": beats,
        "downbeats": beats[::4],
        "onsets": onsets,
    }


def build_preview_project(
    bundle_dir: str | Path,
    output_dir: str | Path,
    *,
    audio_path: str | Path | None = None,
    bpm: float | None = None,
    music_map_path: str | Path | None = None,
) -> dict[str, Any]:
    bundle = Path(bundle_dir).resolve(strict=True)
    output = Path(output_dir).resolve()
    asset_root = output / "assets" / "characters" / "violin-prince"
    asset_root.mkdir(parents=True, exist_ok=True)
    character_path = bundle / "character.json"
    if not character_path.is_file():
        raise FileNotFoundError("The full-body rig bundle does not contain character.json.")

    character = json.loads(character_path.read_text(encoding="utf-8"))
    composite_base_mode = bool(character.get("base_art"))
    segmented_body_mode = composite_base_mode and character.get("performance_base_mode") == "segmented_source_body"
    if composite_base_mode:
        character["base_art"]["src"] = stage_asset(bundle, asset_root, character["base_art"]["src"])
    if character.get("performance", {}).get("instrument_performance") is not True:
        raise ValueError("The candidate character bundle is not marked as an instrument-performance rig.")
    for layer in character.get("layers", []):
        layer["src"] = stage_asset(bundle, asset_root, layer["src"])
    for collection_name in ("expressions", "pose_assets", "props", "head_variants", "head_angles"):
        for asset in (character.get(collection_name) or {}).values():
            asset["src"] = stage_asset(bundle, asset_root, asset["src"])

    music_map = None
    if music_map_path:
        music_map = json.loads(
            Path(music_map_path).read_text(encoding="utf-8")
        )
        if not isinstance(music_map, dict):
            raise ValueError("The supplied violin music map must be a JSON object.")
    if music_map is not None and not audio_path:
        raise ValueError("A sampled-violin event map requires its corresponding audio file.")

    music_sync = _build_preview_music_sync(
        8,
        bpm=bpm,
        audio_path=audio_path,
        music_map=music_map,
    )
    scene = {
        "id": "full-body-violin-performance",
        "start": 0,
        "duration": 8,
        "visual_mode": "full_body_performance",
        "background_color": "#08111b",
        "graphic_label": "FULL-BODY RIG TEST",
        "title": "",
        "caption": "",
        "character_actions": {
            "violin-prince": {
                "visible": True,
                "gesture": "violin_performance",
                "instrument_performance": True,
                "expression": "neutral",
                **({} if composite_base_mode else {
                    "head_angle": "front",
                    "head_angle_sequence": ["front", "three_quarter", "profile_right", "profile_left", "front"],
                    "head_angle_cycle_duration_seconds": 7.2,
                }),
                "x": 46,
                "y": 58,
                "scale": 0.84,
                "loop": True,
                "cycle_duration_seconds": 2.4,
                "start_offset": 0.12,
                "music_sync": music_sync,
                "prop_keyframes": {
                    "bow": {
                        "rotate": [0, -3.5, 3.5, -3.5, 3.5, 0],
                        "translate": [
                            "-18px -4px", "18px 4px", "-18px -4px",
                            "18px 4px", "-18px -4px", "0px 0px"
                        ]
                    },
                    **({} if composite_base_mode and not segmented_body_mode else {
                        "violin": {"rotate": [0, -0.45, 0.35, 0.45, 0]},
                    }),
                },
            }
        },
    }
    project = {
        "schema_version": 4,
        "title": "",
        "width": 720,
        "height": 1280,
        "fps": 25,
        "duration_seconds": 8,
        "brand_system": "violin-prince-fullbody-performance-rig-v1",
        "render_mode": "preview_only",
        "director_palette": {
            "dominant": "#08111b",
            "secondary": "#f5ecde",
            "accent": "#d9b77a",
        },
        "scenes": [scene],
        "characters": [character],
        "publishing": {
            "enabled": False,
            "preview_only": True,
            "schedule_enabled": False,
        },
        "diagnostics": {
            "publishing": "disabled",
            "preview_only": True,
            "character_rig": "segmented_source_aligned_limbs" if segmented_body_mode else
                ("intact_full_body_composite_review" if composite_base_mode else "segmented_full_body"),
            "instrument_performance": "candidate_requires_visual_review",
            "music_sync_source": music_sync["source"],
            "music_sync_bpm": music_sync["bpm"],
            "music_sync_analysis_status": music_sync.get("analysis_status", music_sync["status"]),
            "music_sync_audio_license": music_sync.get("audio_license"),
        },
    }
    (output / "project.json").write_text(
        json.dumps(project, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    rig_note = (
        "Non-publishing source-aligned full-body rig preview. Both arm chains, "
        "both hand overlays, both thigh/calf/foot chains and four finger controls "
        "are separate frame-seekable layers cut from the intact performance source. "
        "Small joint overlaps seal elbows, wrists, knees and ankles. The original "
        "head, torso and violin stay on the source-aligned underpaint base. "
        if segmented_body_mode else
        "Non-publishing complete-body review preview. The original source body "
        "is preserved while the bow and finger controls are tested. "
        if composite_base_mode else
        "Non-publishing segmented full-body rig preview. Inspect all layers "
        "and motion before any production use. "
    )
    music_note = (
        f"Beat/onset timing validated against attached audio ({music_sync['source']}) "
        f"at {music_sync['bpm']:.1f} BPM. "
        + (
            f"Sampled-instrument licence: {music_sync['audio_license']}; "
            "this is not a creator-recorded performance. "
            if music_sync.get("audio_license") else ""
        )
        if music_sync["audio_attached"] else
        f"Preview timing uses a declared {music_sync['bpm']:.1f} BPM grid; "
        "no song audio is attached. "
    )
    (output / "README.txt").write_text(
        rig_note + music_note + "Publishing and scheduling are disabled.\n",
        encoding="utf-8",
    )
    return {
        "status": "preview_project_ready",
        "duration_seconds": project["duration_seconds"],
        "canvas": [project["width"], project["height"]],
        "layer_count": len(character.get("layers", [])),
        "prop_ids": sorted((character.get("props") or {}).keys()),
        "head_variant_ids": sorted((character.get("head_variants") or {}).keys())
        if not composite_base_mode else [],
        "head_angle_ids": sorted((character.get("head_angles") or {}).keys())
        if not composite_base_mode else [],
        "composite_base_mode": composite_base_mode,
        "segmented_body_mode": segmented_body_mode,
        "full_body_visual_mode": "segmented_source_body" if segmented_body_mode else
            ("intact_composite_base" if composite_base_mode else "segmented_limb_rig"),
        "bow_hand_mode": "source_aligned_independent_hand_layer" if segmented_body_mode else
            ("original_source_hand_overlay" if composite_base_mode else "segmented"),
        "publishing": "disabled",
        "preview_only": True,
        "music_sync": music_sync,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--audio", default="", help="Optional audio track used for beat/onset timing.")
    parser.add_argument("--music-map", default="",
                        help="Optional JSON arrangement/event map matching --audio.")
    parser.add_argument("--bpm", type=float, default=None,
                        help="Verified tempo for the preview grid or optional audio phase alignment.")
    args = parser.parse_args()
    result = build_preview_project(
        args.bundle,
        args.output,
        audio_path=args.audio or None,
        bpm=args.bpm,
        music_map_path=args.music_map or None,
    )
    print("FULL_BODY_PREVIEW_PROJECT=" + json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
