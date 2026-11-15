#!/usr/bin/env python3
"""Run a bounded, manual-only Blender benchmark against a saved Run artifact.

This script never builds a new story, generates new imagery, uploads media, or
imports a publisher. It restores only the licensed model omitted from the
Run #63 artifact and reuses the saved creative plan and Frame By Plane images.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import statistics
import sys
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ENGINE_DIR = Path(__file__).resolve().parent
REPO_ROOT = ENGINE_DIR.parents[1]
if str(ENGINE_DIR) not in sys.path:
    sys.path.insert(0, str(ENGINE_DIR))

from benchmark_telemetry import capture_host_diagnostics, write_json_atomic
from blender_renderer import (
    blender_render_fps,
    blender_render_resolution,
    render_scene_video,
)
from story_asset_resolver import resolve_story_asset, StoryAssetError

WORK = REPO_ROOT / "work"
PACKAGE = WORK / "package"
OUTPUT = WORK / "output"
DIAGNOSTICS = OUTPUT / "blender-diagnostics"

VALID_SUITES = {"full_matrix", "baseline_and_contention", "ablation_only"}
VALID_EGL_MODES = {"surfaceless", "unset", "xvfb"}


def _scene_type_for_mode(mode: str) -> str:
    mapping = {
        "macro_3d": "string_vibration",
        "mechanism_3d": "bridge_cutaway",
        "waveform": "wave_field",
        "melody_map": "melody_path",
        "comparison": "comparison",
        "cover_performance": "violin_performance",
    }
    try:
        return mapping[mode]
    except KeyError as exc:
        raise RuntimeError(f"Unsupported saved visual mode for benchmark: {mode!r}") from exc


def _restore_saved_package() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    plan_path = PACKAGE / "creative_plan.json"
    if not plan_path.is_file():
        raise RuntimeError(
            "The selected source run artifact does not contain package/creative_plan.json. "
            "Select the Run #63 production artifact, not a prepared-package artifact."
        )

    try:
        plan = json.loads(plan_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("The saved creative_plan.json is unreadable.") from exc

    scenes = plan.get("scenes")
    if not isinstance(scenes, list) or len(scenes) != 3:
        raise RuntimeError("The saved creative plan must contain exactly three scenes.")

    for index, scene in enumerate(scenes, start=1):
        if not isinstance(scene, dict):
            raise RuntimeError(f"Saved scene {index} is not a JSON object.")
        mode = str(scene.get("visual_mode") or "").strip()
        _scene_type_for_mode(mode)

        manifest = PACKAGE / "frame-by-plane" / f"scene-{index}" / "background-manifest.json"
        if not manifest.is_file():
            raise RuntimeError(
                f"Run artifact is missing the saved Frame By Plane manifest for scene {index}: {manifest}"
            )
        try:
            manifest_data = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Scene {index} Frame By Plane manifest is unreadable.") from exc
        layers = manifest_data.get("layers")
        if not isinstance(layers, list) or len(layers) < 3:
            raise RuntimeError(f"Scene {index} manifest does not describe the required three image layers.")
        for layer in layers:
            image_name = str(layer.get("file") or "").strip()
            if not image_name or not (manifest.parent / image_name).is_file():
                raise RuntimeError(
                    f"Scene {index} Frame By Plane image is missing: {image_name or '[no file]'}"
                )
        scene["frame_by_plane_manifest"] = str(manifest.resolve())
        scene["frame_by_plane_required"] = True
        scene["frame_by_plane_layer_count"] = len(layers)

    model_record = plan.get("model_asset") or {}
    model_path = Path(str(model_record.get("local_model_path") or "")).expanduser()
    if not model_path.is_file() or model_path.suffix.casefold() not in {".gltf", ".glb"}:
        print(
            "Saved artifact does not include the original downloaded glTF/GLB; "
            "restoring the already selected licensed model from the saved plan.",
            flush=True,
        )
        try:
            model_record = resolve_story_asset(
                plan,
                WORK / "story-assets",
                access_token=os.environ.get("SKETCHFAB_ACCESS_TOKEN"),
            )
        except (StoryAssetError, OSError, ValueError) as exc:
            raise RuntimeError(
                "Could not restore the licensed model selected by the Run #63 plan. "
                "Check the SKETCHFAB_ACCESS_TOKEN repository secret. "
                + str(exc)[:700]
            ) from exc
        model_path = Path(str(model_record.get("local_model_path") or "")).expanduser()

    if not model_path.is_file() or model_path.suffix.casefold() not in {".gltf", ".glb"}:
        raise RuntimeError("The restored story asset is not a valid local glTF/GLB file.")

    plan["model_asset"] = dict(model_record)
    plan["model_asset"]["local_model_path"] = str(model_path.resolve())
    for scene in scenes:
        scene["model_asset_path"] = str(model_path.resolve())
        scene["model_asset_kind"] = str(scene.get("model_asset_kind") or plan.get("asset_kind") or "generic")
        scene["model_asset_required"] = True

    # Persist the exact paths used for this new runner for artifact inspection.
    plan_path.write_text(json.dumps(plan, ensure_ascii=False, indent=2), encoding="utf-8")
    return plan, scenes


def _median_frame_time(result: dict[str, Any]) -> float | None:
    timings = result.get("timings")
    frames = timings.get("frames") if isinstance(timings, dict) else None
    values = [
        float(item["wall_seconds"])
        for item in (frames or [])
        if isinstance(item, dict) and item.get("wall_seconds") is not None
    ]
    return statistics.median(values) if values else None


def _render_case(
    case_name: str,
    scene_index: int,
    scene: dict[str, Any],
    *,
    overrides: dict[str, Any] | None = None,
    timeout_seconds: int,
) -> dict[str, Any]:
    safe_name = "".join(
        char.lower() if char.isalnum() else "-"
        for char in case_name
    ).strip("-")
    output_path = OUTPUT / f"benchmark-{safe_name}-scene-{scene_index + 1}.mp4"
    try:
        result = render_scene_video(
            scene,
            output_path,
            scene_index=scene_index,
            duration_seconds=8.0,
            enabled=True,
            resolution=blender_render_resolution(),
            fps=blender_render_fps(),
            timeout_seconds=timeout_seconds,
            benchmark_overrides=overrides or {},
        )
        if not result:
            raise RuntimeError("Blender renderer unexpectedly skipped an enabled benchmark scene.")
        return {
            "case": case_name,
            "scene_index": scene_index + 1,
            "visual_mode": scene.get("visual_mode"),
            "status": "completed",
            "output": str(output_path),
            "diagnostics": result.get("diagnostics_path"),
            "host_diagnostics": os.environ.get("BLENDER_HOST_DIAGNOSTICS_PATH")
            or str(DIAGNOSTICS / "host-diagnostics.json"),
            "timings_path": result.get("timings_path"),
            "timings": result.get("timings"),
            "benchmark_overrides": dict(overrides or {}),
            "median_frame_wall_seconds": _median_frame_time(result),
            "video": {
                key: result.get(key)
                for key in ("duration_seconds", "width", "height", "codec", "frame_rate")
            },
        }
    except Exception as exc:
        return {
            "case": case_name,
            "scene_index": scene_index + 1,
            "visual_mode": scene.get("visual_mode"),
            "status": "failed",
            "error": str(exc)[:1400],
            "traceback": traceback.format_exc()[-5000:],
            "output": str(output_path),
            "diagnostics": str(DIAGNOSTICS / f"{output_path.stem}.log"),
            "timings_path": str(DIAGNOSTICS / f"{output_path.stem}.timings.json"),
            "benchmark_overrides": dict(overrides or {}),
        }


def _run_group(
    case_name: str,
    indexed_scenes: list[tuple[int, dict[str, Any]]],
    *,
    workers: int,
    timeout_seconds: int,
    overrides: dict[str, Any] | None = None,
    lp_num_threads: str | None = None,
) -> list[dict[str, Any]]:
    old_workers = os.environ.get("BLENDER_RENDER_WORKERS")
    old_lp = os.environ.get("LP_NUM_THREADS")
    old_host_path = os.environ.get("BLENDER_HOST_DIAGNOSTICS_PATH")
    safe_case = "".join(char.lower() if char.isalnum() else "-" for char in case_name).strip("-")
    case_host_path = DIAGNOSTICS / f"host-{safe_case}.json"
    os.environ["BLENDER_HOST_DIAGNOSTICS_PATH"] = str(case_host_path)
    os.environ["BLENDER_RENDER_WORKERS"] = str(max(1, min(workers, 3)))
    if lp_num_threads is None:
        os.environ.pop("LP_NUM_THREADS", None)
    else:
        os.environ["LP_NUM_THREADS"] = lp_num_threads

    try:
        results: list[dict[str, Any]] = []
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=max(1, min(workers, len(indexed_scenes), 3)),
            thread_name_prefix="blender-benchmark",
        ) as executor:
            futures = {
                executor.submit(
                    _render_case,
                    case_name,
                    index,
                    scene,
                    overrides=overrides,
                    timeout_seconds=timeout_seconds,
                ): index
                for index, scene in indexed_scenes
            }
            for future in concurrent.futures.as_completed(futures):
                results.append(future.result())
        results.sort(key=lambda item: int(item["scene_index"]))
        return results
    finally:
        if old_workers is None:
            os.environ.pop("BLENDER_RENDER_WORKERS", None)
        else:
            os.environ["BLENDER_RENDER_WORKERS"] = old_workers
        if old_lp is None:
            os.environ.pop("LP_NUM_THREADS", None)
        else:
            os.environ["LP_NUM_THREADS"] = old_lp
        if old_host_path is None:
            os.environ.pop("BLENDER_HOST_DIAGNOSTICS_PATH", None)
        else:
            os.environ["BLENDER_HOST_DIAGNOSTICS_PATH"] = old_host_path


def _build_suite(
    suite: str,
    scenes: list[dict[str, Any]],
    timeout_seconds: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    scene_one = [(0, scenes[0])]
    all_scenes = list(enumerate(scenes))

    print("BENCHMARK_CASE=single_worker_baseline", flush=True)
    results.extend(
        _run_group(
            "single_worker_baseline",
            scene_one,
            workers=1,
            timeout_seconds=timeout_seconds,
        )
    )

    if suite in {"baseline_and_contention", "full_matrix"}:
        print("BENCHMARK_CASE=three_worker_contention", flush=True)
        results.extend(
            _run_group(
                "three_worker_contention",
                all_scenes,
                workers=3,
                timeout_seconds=timeout_seconds,
            )
        )

    if suite == "full_matrix":
        print("BENCHMARK_CASE=three_worker_lp_num_threads_1", flush=True)
        results.extend(
            _run_group(
                "three_worker_lp_num_threads_1",
                all_scenes,
                workers=3,
                timeout_seconds=timeout_seconds,
                lp_num_threads="1",
            )
        )

    if suite in {"ablation_only", "full_matrix"}:
        ablations = (
            ("disable_dof", {"disable_dof": True}),
            ("disable_frame_by_plane", {"disable_frame_by_plane": True}),
            ("disable_model", {"disable_model": True}),
            ("disable_shadows", {"disable_shadows": True}),
            ("samples_1", {"samples": 1}),
        )
        for case_name, overrides in ablations:
            print("BENCHMARK_CASE=" + case_name, flush=True)
            results.extend(
                _run_group(
                    case_name,
                    scene_one,
                    workers=1,
                    timeout_seconds=timeout_seconds,
                    overrides=overrides,
                )
            )
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--suite", choices=sorted(VALID_SUITES), required=True)
    parser.add_argument("--sample-frames", type=int, default=None)
    parser.add_argument("--egl-mode", choices=sorted(VALID_EGL_MODES), default=None)
    args = parser.parse_args()

    if os.environ.get("PUBLISH_ENABLED", "false").strip().casefold() not in {
        "false", "0", "no", "off", ""
    }:
        raise SystemExit("Safety check failed: PUBLISH_ENABLED must remain false.")
    os.environ["PUBLISH_ENABLED"] = "false"
    # This diagnostic runner never uses any publishing credentials or publisher module.
    os.environ["AUTOPILOT_API_URL"] = ""
    os.environ["AUTOPILOT_JOB_TOKEN"] = ""

    try:
        sample_frames = args.sample_frames or int(os.environ.get("BENCH_MAX_FRAMES", "3"))
    except (TypeError, ValueError) as exc:
        raise SystemExit("Sample frame count must be an integer from 1 to 8.") from exc
    if not 1 <= sample_frames <= 8:
        raise SystemExit("Sample frame count must be between 1 and 8.")
    os.environ["BENCH_MAX_FRAMES"] = str(sample_frames)

    egl_mode = args.egl_mode or os.environ.get("BENCH_EGL_MODE", "surfaceless")
    if egl_mode not in VALID_EGL_MODES:
        raise SystemExit("EGL mode must be surfaceless, unset, or xvfb.")
    os.environ["BENCH_EGL_MODE"] = egl_mode

    if os.environ.get("BLENDER_BENCHMARK_DIAGNOSTICS") != "1":
        raise SystemExit("BLENDER_BENCHMARK_DIAGNOSTICS=1 is required.")
    os.environ["BLENDER_RENDER_DIAGNOSTICS"] = "1"
    os.environ["BLENDER_RENDER_ENABLED"] = "true"
    os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
    os.environ["MESA_LOADER_DRIVER_OVERRIDE"] = "llvmpipe"

    try:
        timeout_seconds = int(os.environ.get("BENCH_RENDER_TIMEOUT_SECONDS", "2400"))
    except (TypeError, ValueError) as exc:
        raise SystemExit("BENCH_RENDER_TIMEOUT_SECONDS must be an integer.") from exc
    if not 60 <= timeout_seconds <= 3600:
        raise SystemExit("Benchmark subprocess timeout must be between 60 and 3600 seconds.")

    WORK.mkdir(parents=True, exist_ok=True)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    DIAGNOSTICS.mkdir(parents=True, exist_ok=True)
    host = capture_host_diagnostics(DIAGNOSTICS / "host-diagnostics.json")
    print("BENCHMARK_HOST=" + json.dumps({
        "cpu_count_os": host["hardware"].get("cpu_count_os"),
        "cpu_affinity": host["hardware"].get("cpu_affinity"),
        "nproc_visible": host["hardware"].get("nproc_visible"),
        "memory_total": host["hardware"].get("memory_total"),
        "memory_available": host["hardware"].get("memory_available"),
        "cgroup": host["hardware"].get("cgroup"),
    }, ensure_ascii=False), flush=True)

    plan, scenes = _restore_saved_package()
    print("BENCHMARK_PACKAGE_RESTORED=1; scenes=3; fbp_layers_per_scene=3", flush=True)
    print(
        "BENCHMARK_SETTINGS="
        + json.dumps({
            "suite": args.suite,
            "sample_frames": sample_frames,
            "egl_mode": egl_mode,
            "resolution": blender_render_resolution(),
            "fps": blender_render_fps(),
            "samples": os.environ.get("BLENDER_RENDER_SAMPLES", "4"),
            "model_face_limit": os.environ.get("BLENDER_MODEL_FACE_LIMIT", "60000"),
            "workers_baseline": 1,
            "workers_contention": 3,
            "blender_process_timeout_seconds": timeout_seconds,
            "publishing": False,
            "model_asset_uid": (plan.get("model_asset") or {}).get("model_uid"),
        }, ensure_ascii=False),
        flush=True,
    )

    results = _build_suite(args.suite, scenes, timeout_seconds)
    summary = {
        "schema_version": 1,
        "status": "completed" if results and all(item.get("status") == "completed" for item in results) else "partial_or_failed",
        "captured_at_utc": datetime.now(timezone.utc).isoformat(),
        "repository": os.environ.get("GITHUB_REPOSITORY"),
        "source_run_id": os.environ.get("SOURCE_RUN_ID"),
        "workflow_run_id": os.environ.get("GITHUB_RUN_ID"),
        "suite": args.suite,
        "sample_frames": sample_frames,
        "egl_mode": egl_mode,
        "publishing": False,
        "host_diagnostics": str(DIAGNOSTICS / "host-diagnostics.json"),
        "results": results,
    }

    baseline = next(
        (item for item in results if item.get("case") == "single_worker_baseline" and item.get("status") == "completed"),
        None,
    )
    if baseline and baseline.get("median_frame_wall_seconds"):
        base_time = float(baseline["median_frame_wall_seconds"])
        contention = next(
            (
                item for item in results
                if item.get("case") == "three_worker_contention"
                and item.get("scene_index") == 1
                and item.get("status") == "completed"
                and item.get("median_frame_wall_seconds")
            ),
            None,
        )
        if contention:
            cont_time = float(contention["median_frame_wall_seconds"])
            summary["scene_1_contention_slowdown_ratio"] = round(cont_time / base_time, 4) if base_time else None

    summary_path = DIAGNOSTICS / "benchmark-summary.json"
    write_json_atomic(summary_path, summary)
    print("BENCHMARK_SUMMARY=" + str(summary_path), flush=True)
    print(
        "BENCHMARK_RESULT_COUNTS="
        + json.dumps({
            "completed": sum(item.get("status") == "completed" for item in results),
            "failed": sum(item.get("status") == "failed" for item in results),
            "scene_1_contention_slowdown_ratio": summary.get("scene_1_contention_slowdown_ratio"),
        }, ensure_ascii=False),
        flush=True,
    )
    return 0 if results and all(item.get("status") == "completed" for item in results) else 1


if __name__ == "__main__":
    sys.exit(main())
