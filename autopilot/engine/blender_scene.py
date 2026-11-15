"""Blender 3D hero-scene renderer with mandatory Frame By Plane daily backgrounds.

The licensed instrument is real 3D geometry. Daily production adds native
Frame By Plane image layers behind it for camera-space parallax and 2.5D depth.
Blender renders the composed scene directly to an opaque MP4 clip.
"""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path

# Blender's `--python path/to/blender_scene.py` execution does not guarantee
# that this script's directory is on sys.path. Daily scenes import the local
# Frame By Plane adapter at build time, so add the engine directory explicitly.
ENGINE_DIR = str(Path(__file__).resolve().parent)
if ENGINE_DIR not in sys.path:
    sys.path.insert(0, ENGINE_DIR)

import bpy
from blender_renderer import model_decimation_ratio
from benchmark_telemetry import process_snapshot, write_json_atomic
from mathutils import Matrix, Vector


_PROCESS_START = time.perf_counter()
_TIMINGS = None


def _gpu_runtime_info():
    info = {}
    try:
        import gpu

        for key, function_name in (
            ("vendor", "vendor_get"),
            ("renderer", "renderer_get"),
            ("version", "version_get"),
            ("device_type", "device_type_get"),
        ):
            function = getattr(gpu.platform, function_name, None)
            if callable(function):
                try:
                    info[key] = str(function())
                except Exception as exc:
                    info[key + "_error"] = str(exc)[:180]
    except Exception as exc:
        info["api_error"] = str(exc)[:180]
    return info


def _write_timing_report():
    if not isinstance(_TIMINGS, dict):
        return
    path = str(_TIMINGS.get("diagnostics_path") or "").strip()
    if not path:
        return
    try:
        write_json_atomic(path, _TIMINGS)
    except Exception as exc:
        print("BLENDER_DIAGNOSTICS_WRITE_WARNING=" + str(exc)[:240], flush=True)


def _register_render_telemetry(scene, config):
    """Collect one record per rendered frame and enforce the optional time-budget gate."""
    global _TIMINGS
    if not isinstance(_TIMINGS, dict):
        return []

    preflight_enabled = bool(config.get("preflight_enabled", False))
    diagnostics_enabled = bool(config.get("diagnostics_enabled", False))
    if not preflight_enabled and not diagnostics_enabled:
        return []

    active = {}
    records_by_frame = {}
    writes_before_post = {}
    frame_change_started = {}
    frame_change_durations = {}
    stats_by_frame = {}
    render_stats_records = _TIMINGS.setdefault("render_stats", [])
    frame_records = _TIMINGS.setdefault("frames", [])

    def request_preflight_abort(gate_name, projected_seconds, observed):
        if _TIMINGS.get("preflight", {}).get("aborted"):
            return
        timeout_seconds = max(30, int(config.get("preflight_timeout_seconds", 900)))
        reserve_seconds = max(0, min(int(config.get("preflight_reserve_seconds", 30)), 300))
        budget_seconds = max(30, timeout_seconds - reserve_seconds)
        report = {
            "schema_version": 1,
            "status": "aborted",
            "aborted": True,
            "gate": gate_name,
            "scene_type": str(config.get("scene_type") or ""),
            "frame_count": int(scene.frame_end - scene.frame_start + 1),
            "observed": observed,
            "projected_total_seconds": round(float(projected_seconds), 3),
            "timeout_seconds": timeout_seconds,
            "reserved_seconds": reserve_seconds,
            "usable_budget_seconds": budget_seconds,
            "captured_at_utc": datetime.now(timezone.utc).isoformat(),
            "reason": (
                "Measured frame time projects beyond the configured Blender process budget. "
                "The scene was cancelled after the measured sample; no quality settings were changed."
            ),
        }
        _TIMINGS["preflight"] = report
        _TIMINGS["status"] = "preflight_aborted"
        report_path = str(config.get("preflight_report_path") or "").strip()
        if report_path:
            try:
                write_json_atomic(report_path, report)
            except Exception as exc:
                print("BLENDER_PREFLIGHT_REPORT_WRITE_WARNING=" + str(exc)[:240], flush=True)
        _write_timing_report()
        print("BLENDER_PREFLIGHT_ABORT=" + json.dumps(report, ensure_ascii=False), flush=True)
        # Also close the timeline at this exact frame. If an operator context
        # prevents render.cancel() from running in a handler, Blender's animation
        # loop still has no remaining frames to process.
        try:
            scene.frame_end = int(scene.frame_current)
        except Exception as exc:
            report["frame_end_adjust_error"] = str(exc)[:240]
        try:
            bpy.ops.render.cancel()
        except Exception as exc:
            report["cancel_error"] = str(exc)[:240]
            _write_timing_report()

    def on_render_pre(render_scene):
        frame_number = int(render_scene.frame_current)
        snapshot = process_snapshot()
        active[frame_number] = {
            "started_perf": time.perf_counter(),
            "started_cpu_user": float(snapshot.get("cpu_user_seconds", 0.0)),
            "started_cpu_system": float(snapshot.get("cpu_system_seconds", 0.0)),
            "frame_set_seconds": frame_change_durations.pop(frame_number, 0.0),
            "start_snapshot": snapshot,
        }

    def on_render_post(render_scene):
        frame_number = int(render_scene.frame_current)
        started = active.pop(frame_number, None)
        if not started:
            return
        ended_perf = time.perf_counter()
        snapshot = process_snapshot()
        render_wall_seconds = max(0.0, ended_perf - started["started_perf"])
        frame_set_seconds = max(0.0, float(started.get("frame_set_seconds", 0.0)))
        wall_seconds = frame_set_seconds + render_wall_seconds
        cpu_user = max(
            0.0, float(snapshot.get("cpu_user_seconds", 0.0)) - started["started_cpu_user"]
        )
        cpu_system = max(
            0.0, float(snapshot.get("cpu_system_seconds", 0.0)) - started["started_cpu_system"]
        )
        record = {
            "frame": frame_number,
            "wall_seconds": round(wall_seconds, 6),
            "frame_set_seconds": round(frame_set_seconds, 6),
            "render_wall_seconds": round(render_wall_seconds, 6),
            "cpu_user_seconds": round(cpu_user, 6),
            "cpu_system_seconds": round(cpu_system, 6),
            "cpu_total_seconds": round(cpu_user + cpu_system, 6),
            "process_elapsed_seconds": round(ended_perf - _PROCESS_START, 6),
            "resources_after_frame": snapshot,
            "render_stats": stats_by_frame.get(frame_number),
            "_render_post_perf": ended_perf,
        }
        early_write = writes_before_post.pop(frame_number, None)
        if early_write is not None:
            record["render_write_before_render_post"] = True
            record["render_write_callback_elapsed_seconds"] = round(
                max(0.0, early_write - started["started_perf"]), 6
            )
            record.pop("_render_post_perf", None)
        frame_records.append(record)
        records_by_frame[frame_number] = record
        _TIMINGS["last_frame_completed"] = frame_number
        _write_timing_report()

        if not preflight_enabled or _TIMINGS.get("preflight", {}).get("aborted"):
            return

        total_frames = max(1, int(render_scene.frame_end - render_scene.frame_start + 1))
        setup_seconds = float(
            _TIMINGS.get("stages", {}).get("elapsed_before_render_seconds", 0.0)
        )
        timeout_seconds = max(30, int(config.get("preflight_timeout_seconds", 900)))
        reserve_seconds = max(0, min(int(config.get("preflight_reserve_seconds", 30)), 300))
        budget_seconds = max(30, timeout_seconds - reserve_seconds)

        if frame_number == int(render_scene.frame_start):
            multiplier = float(config.get("preflight_first_frame_multiplier", 1.25))
            projected = setup_seconds + wall_seconds * total_frames
            _TIMINGS["preflight"] = {
                "gate_1": "passed" if projected <= budget_seconds * multiplier else "aborted",
                "first_frame_projection_seconds": round(projected, 3),
                "first_frame_multiplier": multiplier,
                "usable_budget_seconds": budget_seconds,
            }
            if projected > budget_seconds * multiplier:
                request_preflight_abort(
                    "frame_1_projection",
                    projected,
                    {"frame_1_wall_seconds": round(wall_seconds, 3), "setup_seconds": round(setup_seconds, 3)},
                )
                return

        elif frame_number == int(render_scene.frame_start) + 1 and len(frame_records) >= 2:
            first_frame_seconds = float(frame_records[0]["wall_seconds"])
            projected = setup_seconds + first_frame_seconds + (total_frames - 1) * wall_seconds
            _TIMINGS.setdefault("preflight", {})["gate_2"] = (
                "passed" if projected <= budget_seconds else "aborted"
            )
            _TIMINGS["preflight"]["second_frame_projection_seconds"] = round(projected, 3)
            _TIMINGS["preflight"]["usable_budget_seconds"] = budget_seconds
            if projected > budget_seconds:
                request_preflight_abort(
                    "frame_2_projection",
                    projected,
                    {
                        "frame_1_wall_seconds": round(first_frame_seconds, 3),
                        "frame_2_wall_seconds": round(wall_seconds, 3),
                        "setup_seconds": round(setup_seconds, 3),
                    },
                )
            else:
                _write_timing_report()

    def on_frame_change_pre(changed_scene):
        frame_change_started[int(changed_scene.frame_current)] = time.perf_counter()

    def on_frame_change_post(changed_scene):
        frame_number = int(changed_scene.frame_current)
        started_at = frame_change_started.pop(frame_number, None)
        if started_at is not None:
            frame_change_durations[frame_number] = max(0.0, time.perf_counter() - started_at)

    def _stats_time_seconds(value):
        try:
            parts = [float(item) for item in str(value).split(":")]
            if len(parts) == 3:
                return parts[0] * 3600.0 + parts[1] * 60.0 + parts[2]
            if len(parts) == 2:
                return parts[0] * 60.0 + parts[1]
            if len(parts) == 1:
                return parts[0]
        except (TypeError, ValueError):
            return None
        return None

    def on_render_stats(stats_text):
        raw = str(stats_text)
        frame_match = re.search(r"\\bFra:\\s*(\\d+)", raw)
        frame_number = (
            int(frame_match.group(1))
            if frame_match
            else int(scene.frame_current)
        )
        entry = {"frame": frame_number, "raw": raw[:1200]}
        render_match = re.search(r"\\bTime:\\s*([0-9:.]+)", raw)
        saving_match = re.search(r"\\bSaving:\\s*([0-9:.]+)", raw)
        if render_match:
            entry["render_seconds"] = _stats_time_seconds(render_match.group(1))
        if saving_match:
            entry["saving_seconds"] = _stats_time_seconds(saving_match.group(1))
        stats_by_frame[frame_number] = entry
        render_stats_records.append(entry)
        if len(render_stats_records) > 500:
            del render_stats_records[:-500]
        record = records_by_frame.get(frame_number)
        if record is not None:
            record["render_stats"] = entry
        _write_timing_report()

    def on_render_write(render_scene):
        frame_number = int(render_scene.frame_current)
        now = time.perf_counter()
        record = records_by_frame.get(frame_number)
        if record is None:
            # Blender versions can dispatch render_write before render_post.
            # Preserve the observation without inventing an append duration.
            writes_before_post[frame_number] = now
            return
        record["video_append_and_write_seconds"] = round(
            max(0.0, now - (record.get("_render_post_perf") or now)), 6
        )
        record.pop("_render_post_perf", None)
        record["render_write_callback_observed"] = True
        _write_timing_report()

    bpy.app.handlers.render_pre.append(on_render_pre)
    bpy.app.handlers.render_post.append(on_render_post)
    handlers = [
        (bpy.app.handlers.render_pre, on_render_pre),
        (bpy.app.handlers.render_post, on_render_post),
        (bpy.app.handlers.frame_change_pre, on_frame_change_pre),
        (bpy.app.handlers.frame_change_post, on_frame_change_post),
    ]
    bpy.app.handlers.frame_change_pre.append(on_frame_change_pre)
    bpy.app.handlers.frame_change_post.append(on_frame_change_post)
    render_stats_handlers = getattr(bpy.app.handlers, "render_stats", None)
    if isinstance(render_stats_handlers, list):
        render_stats_handlers.append(on_render_stats)
        handlers.append((render_stats_handlers, on_render_stats))
    render_write_handlers = getattr(bpy.app.handlers, "render_write", None)
    if isinstance(render_write_handlers, list):
        render_write_handlers.append(on_render_write)
        handlers.append((render_write_handlers, on_render_write))
    return handlers


def _remove_render_telemetry_handlers(handlers):
    for collection, handler in handlers:
        try:
            if handler in collection:
                collection.remove(handler)
        except Exception:
            pass


def parse_arguments():
    raw = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(raw)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (
        bpy.data.meshes, bpy.data.curves, bpy.data.materials,
        bpy.data.cameras, bpy.data.lights, bpy.data.actions,
    ):
        for item in list(datablocks):
            if item.users == 0:
                datablocks.remove(item)


def material(name, color, metallic=0.0, roughness=0.35, emission=0.0):
    value = bpy.data.materials.new(name=name)
    value.diffuse_color = (*color, 1.0)
    value.use_nodes = True
    shader = value.node_tree.nodes.get("Principled BSDF")
    if shader:
        for key, setting in (
            ("Base Color", (*color, 1.0)),
            ("Metallic", metallic),
            ("Roughness", roughness),
            ("Emission Color", (*color, 1.0)),
            ("Emission", (*color, 1.0)),
            ("Emission Strength", emission),
        ):
            socket = shader.inputs.get(key)
            if socket is not None:
                socket.default_value = setting
    return value


def add_curve(name, coordinates, mat, bevel=0.02, cyclic=False):
    curve = bpy.data.curves.new(name=name, type="CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 16
    curve.bevel_depth = bevel
    curve.bevel_resolution = 3
    spline = curve.splines.new("POLY")
    spline.points.add(max(0, len(coordinates) - 1))
    for point, coordinate in zip(spline.points, coordinates):
        point.co = (*coordinate, 1.0)
    spline.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(mat)
    return obj


def add_cube(name, location, scale, mat, bevel=0.0):
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=location)
    obj = bpy.context.object
    obj.name = name
    obj.dimensions = scale
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    if bevel:
        modifier = obj.modifiers.new("Soft crafted edges", "BEVEL")
        modifier.width = bevel
        modifier.segments = 3
        obj.modifiers.new("Weighted corner normals", "WEIGHTED_NORMAL")
    obj.data.materials.append(mat)
    return obj


def add_sphere(name, location, radius, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=20, ring_count=12, radius=radius, location=location
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    for face in obj.data.polygons:
        face.use_smooth = True
    return obj


def add_area_light(name, location, energy, colour, size, target=(0.0, 0.0, 0.0)):
    bpy.ops.object.light_add(type="AREA", location=location)
    light = bpy.context.object
    light.name = name
    light.data.energy = energy
    light.data.color = colour
    light.data.shape = "DISK"
    light.data.size = size
    direction = Vector(target) - light.location
    light.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return light


def action_fcurves(owner):
    """Return F-curves across Blender's legacy and slotted Action APIs.

    Blender 5.0 removed Action.fcurves. Newer Blender versions store curves in
    an ActionChannelbag associated with the animated data-block's Action Slot.
    """
    animation = getattr(owner, "animation_data", None)
    action = getattr(animation, "action", None) if animation else None
    if action is None:
        return ()

    # Preserve compatibility with older Blender builds where this collection
    # still exists. getattr avoids touching the removed property on Blender 5.
    legacy_curves = getattr(action, "fcurves", None)
    if legacy_curves is not None:
        return tuple(legacy_curves)

    slot = getattr(animation, "action_slot", None)
    if slot is None:
        return ()

    # Blender 5.x exposes a supported helper for retrieving the channelbag.
    try:
        from bpy_extras import anim_utils
        getter = getattr(anim_utils, "action_get_channelbag_for_slot", None)
        if callable(getter):
            channelbag = getter(action, slot)
            if channelbag is not None:
                return tuple(channelbag.fcurves)
    except (AttributeError, ImportError, RuntimeError, TypeError):
        pass

    # Defensive fallback for Blender builds where the convenience helper is
    # unavailable but the slotted Action data model is present.
    curves = []
    for layer in getattr(action, "layers", ()):
        for strip in getattr(layer, "strips", ()):
            try:
                channelbag = strip.channelbag(slot)
            except (AttributeError, RuntimeError, TypeError):
                channelbag = None
            if channelbag is not None:
                curves.extend(tuple(channelbag.fcurves))
    return tuple(curves)


def animate_scalar(obj, data_path, frames_values, cycle=False):
    for frame, value in frames_values:
        setattr(obj, data_path, value)
        obj.keyframe_insert(data_path=data_path, frame=frame)
    for fcurve in action_fcurves(obj):
        if fcurve.data_path == data_path:
            for point in fcurve.keyframe_points:
                point.interpolation = "BEZIER"
            if cycle:
                fcurve.modifiers.new("CYCLES")


def animate_transform(obj, attribute, start, end, frame_start, frame_end):
    setattr(obj, attribute, start)
    obj.keyframe_insert(data_path=attribute, frame=frame_start)
    setattr(obj, attribute, end)
    obj.keyframe_insert(data_path=attribute, frame=frame_end)


def add_bridge(mat):
    profile = [
        (-0.95, -0.80), (0.95, -0.80), (0.74, -0.22),
        (0.43, 0.56), (-0.43, 0.56), (-0.74, -0.22),
    ]
    depth = 0.22
    vertices = [(x, -depth, z) for x, z in profile] + [
        (x, depth, z) for x, z in profile
    ]
    count = len(profile)
    faces = [tuple(range(count)), tuple(reversed(range(count, count * 2)))]
    for index in range(count):
        nxt = (index + 1) % count
        faces.append((index, nxt, count + nxt, count + index))
    mesh = bpy.data.meshes.new("Carved violin bridge geometry")
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(mat)
    mesh.update()
    obj = bpy.data.objects.new("Carved amber violin bridge", mesh)
    bpy.context.collection.objects.link(obj)
    bevel = obj.modifiers.new("Rounded maple edges", "BEVEL")
    bevel.width = 0.055
    bevel.segments = 4
    obj.modifiers.new("Weighted normals", "WEIGHTED_NORMAL")
    return obj


def add_vibrating_string(name, x_start, x_end, y, z, mat, frame_end, seed_offset=0):
    # A real mesh tube with a shape-key displacement down its length.
    along = 48
    sides = 8
    vertices = []
    faces = []
    for index in range(along + 1):
        u = index / along
        x = x_start + (x_end - x_start) * u
        for side in range(sides):
            angle = (2.0 * math.pi * side) / sides
            radius = 0.018
            vertices.append((x, y + math.cos(angle) * radius, z + math.sin(angle) * radius))
    for index in range(along):
        for side in range(sides):
            a = index * sides + side
            b = index * sides + (side + 1) % sides
            c = (index + 1) * sides + (side + 1) % sides
            d = (index + 1) * sides + side
            faces.append((a, b, c, d))
    mesh = bpy.data.meshes.new(name + " mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(mat)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)
    for face in mesh.polygons:
        face.use_smooth = True
    basis = obj.shape_key_add(name="Basis")
    vibration = obj.shape_key_add(name="String vibration")
    for index in range(along + 1):
        u = index / along
        displacement = 0.23 * math.sin(math.pi * u)
        for side in range(sides):
            vertex_index = index * sides + side
            vibration.data[vertex_index].co.z += displacement
    # One full visible vibration cycle across the complete scene duration.
    # Keep every keyframe inside the frame range and avoid legacy Action.fcurves
    # access, which was removed from Blender 5's slotted-action API.
    period = max(8, int(frame_end) - 1)
    frames = [
        (1, -1.0), (1 + period // 4, 0.0), (1 + period // 2, 1.0),
        (1 + (3 * period) // 4, 0.0), (frame_end, -1.0),
    ]
    for frame, strength in frames:
        vibration.value = strength
        vibration.keyframe_insert(data_path="value", frame=frame)
    obj["animation"] = "A shape-key mesh deformation visibly vibrates along the string"
    return obj


def add_ripple_ring(name, radius, y, mat, frame_end, phase=0.0):
    bpy.ops.mesh.primitive_torus_add(
        major_segments=64, minor_segments=8,
        location=(0.0, y, 0.15 + phase), major_radius=radius, minor_radius=0.012,
        rotation=(math.pi / 2.0, 0.0, 0.0),
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(mat)
    for face in obj.data.polygons:
        face.use_smooth = True
    frames = [
        (1, (0.75, 0.75, 0.75)),
        (frame_end // 2, (1.0, 1.0, 1.0)),
        (frame_end, (1.25, 1.25, 1.25)),
    ]
    for frame, scale in frames:
        obj.scale = scale
        obj.keyframe_insert(data_path="scale", frame=frame)
    return obj


def violin_body(mat):
    # A sculpted 2D violin outline extruded into a solid, bevelled 3D body.
    points = [
        (-0.62, -1.65), (-0.98, -1.25), (-0.86, -0.72),
        (-0.46, -0.28), (-0.72, 0.18), (-0.80, 0.72),
        (-0.56, 1.23), (0.0, 1.48), (0.56, 1.23),
        (0.80, 0.72), (0.72, 0.18), (0.46, -0.28),
        (0.86, -0.72), (0.98, -1.25), (0.62, -1.65),
        (0.0, -1.82),
    ]
    curve = bpy.data.curves.new("Violin body silhouette", type="CURVE")
    curve.dimensions = "2D"
    curve.fill_mode = "BOTH"
    curve.resolution_u = 24
    curve.extrude = 0.10
    curve.bevel_depth = 0.045
    curve.bevel_resolution = 4
    spline = curve.splines.new("BEZIER")
    spline.bezier_points.add(len(points) - 1)
    for point, (x, z) in zip(spline.bezier_points, points):
        point.co = (x, z, 0.0)
        point.handle_left_type = "AUTO"
        point.handle_right_type = "AUTO"
    spline.use_cyclic_u = True
    body = bpy.data.objects.new("Solid carved amber violin body", curve)
    bpy.context.collection.objects.link(body)
    body.rotation_euler.x = math.pi / 2.0
    body.location.y = 0.0
    body.data.materials.append(mat)
    return body


def add_violin(mat_wood, mat_gold, mat_strings, mat_dark, frame_end):
    body = violin_body(mat_wood)
    neck = add_cube("Violin neck", (0.0, -0.02, 2.15), (0.22, 0.20, 1.75), mat_wood, 0.045)
    fingerboard = add_cube("Ebony fingerboard", (0.0, -0.18, 2.15), (0.25, 0.13, 1.78), mat_dark, 0.06)
    pegbox = add_cube("Violin pegbox", (0.0, -0.04, 3.12), (0.32, 0.28, 0.48), mat_wood, 0.08)
    for x in (-0.22, 0.22):
        peg = add_cube("Tuning peg", (x, -0.10, 2.95), (0.26, 0.10, 0.075), mat_gold, 0.03)
        peg.rotation_euler.y = -0.12 if x < 0 else 0.12

    # Tailpiece, bridge, saddle and four continuous 3D strings.
    add_cube("Violin tailpiece", (0.0, -0.22, -0.92), (0.27, 0.08, 0.95), mat_dark, 0.10)
    bridge = add_cube("Violin bridge", (0.0, -0.30, -0.35), (0.66, 0.18, 0.27), mat_gold, 0.07)
    bridge.rotation_euler.y = -0.05
    add_cube("Violin saddle", (0.0, -0.02, -1.72), (0.62, 0.12, 0.12), mat_dark, 0.03)
    for index in range(4):
        x = (index - 1.5) * 0.075
        add_curve(
            f"Violin string {index + 1}",
            [(x, -0.315, -1.18), (x, -0.325, -0.34), (x, -0.30, 0.80), (x, -0.28, 1.30), (x, -0.24, 2.90)],
            mat_strings, bevel=0.012,
        )

    # Stylised f-holes are 3D metal-dark channels on the violin's front face.
    for side in (-1, 1):
        x = side * 0.43
        coords = [
            (x, -0.21, 0.25), (x - side * 0.08, -0.23, 0.05),
            (x, -0.23, -0.18), (x + side * 0.06, -0.23, -0.42),
            (x, -0.22, -0.62),
        ]
        add_curve("Violin f-hole detail", coords, mat_dark, bevel=0.035)
        add_sphere("F-hole upper eye", (x, -0.245, 0.28), 0.055, mat_dark)
        add_sphere("F-hole lower eye", (x, -0.245, -0.65), 0.055, mat_dark)

    # The bow is an actual 3D assembly and sweeps across the strings.
    bow = add_curve(
        "Animated violin bow stick",
        [(-1.55, -0.62, 0.05), (-0.75, -0.64, 0.02), (0.0, -0.66, 0.0),
         (0.75, -0.64, -0.02), (1.55, -0.62, -0.05)],
        mat_gold, bevel=0.035,
    )
    hair = add_curve(
        "Bow hair",
        [(-1.55, -0.56, 0.12), (-0.75, -0.57, 0.10), (0.0, -0.58, 0.08),
         (0.75, -0.57, 0.06), (1.55, -0.56, 0.03)],
        mat_strings, bevel=0.009,
    )
    for obj in (bow, hair):
        obj.keyframe_insert(data_path="location", frame=1)
        obj.location.x = 0.65
        obj.location.z = 0.10
        obj.keyframe_insert(data_path="location", frame=max(2, frame_end // 2))
        obj.location.x = -0.35
        obj.location.z = -0.06
        obj.keyframe_insert(data_path="location", frame=frame_end)
    for obj in (body, neck, fingerboard, pegbox, bridge):
        obj.keyframe_insert(data_path="rotation_euler", frame=1)
        obj.rotation_euler.y = 0.035
        obj.keyframe_insert(data_path="rotation_euler", frame=frame_end)
    return body


def add_melody_path(mat_gold, mat_teal, frame_end):
    points = []
    for index in range(9):
        x = -1.45 + index * 0.36
        z = -0.55 + 0.20 * index + 0.16 * math.sin(index * 0.8)
        points.append((x, 0.0, z))
        note = add_sphere(
            f"3D melody note {index + 1}", (x, -0.25, z),
            0.07 + 0.015 * (index % 3), mat_gold if index % 2 else mat_teal,
        )
        animate_transform(
            note, "location",
            (x, -0.25, z - 0.06), (x, -0.25, z + 0.06), 1, frame_end,
        )
    add_curve("Three-dimensional melody contour", points, mat_teal, bevel=0.018)



def decimate_render_meshes(meshes, face_limit=60000, preserve_meshes=()):
    """Reduce imported hero geometry in memory for CPU rendering.

    Separate string meshes and very small detail meshes are preserved. The
    downloaded GLTF/GLB file is never modified. Material assignments remain on
    the evaluated mesh. Up to three bounded collapse passes compensate for
    Blender's approximate face target while keeping the complete hero within
    a predictable geometry budget.
    """
    valid_meshes = [
        obj for obj in meshes
        if getattr(obj, "type", "") == "MESH"
        and getattr(getattr(obj, "data", None), "polygons", None) is not None
    ]
    preserve_ids = {obj.as_pointer() for obj in preserve_meshes}
    original_faces = sum(len(obj.data.polygons) for obj in valid_meshes)
    fixed_meshes = [
        obj for obj in valid_meshes
        if obj.as_pointer() in preserve_ids or len(obj.data.polygons) < 400
    ]
    eligible_meshes = [obj for obj in valid_meshes if obj not in fixed_meshes]
    fixed_faces = sum(len(obj.data.polygons) for obj in fixed_meshes)
    budget = max(100, int(face_limit))
    eligible_budget = max(100, budget - fixed_faces)
    combined_ratio = 1.0
    applied_passes = 0
    decimated_names = set()

    if bpy.context.object is not None and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")

    for pass_index in range(3):
        eligible_faces = sum(len(obj.data.polygons) for obj in eligible_meshes)
        ratio = model_decimation_ratio(eligible_faces, eligible_budget)
        if ratio >= 0.999 or not eligible_meshes:
            break
        combined_ratio *= ratio
        for obj in eligible_meshes:
            # Imported objects can share mesh datablocks. Make the render copy
            # unique before applying modifiers so one part cannot mutate another.
            if int(getattr(obj.data, "users", 1)) > 1:
                obj.data = obj.data.copy()
            modifier = obj.modifiers.new(
                name=f"Violin Prince CPU geometry budget {pass_index + 1}",
                type="DECIMATE",
            )
            modifier.decimate_type = "COLLAPSE"
            modifier.ratio = ratio
            if hasattr(modifier, "use_collapse_triangulate"):
                modifier.use_collapse_triangulate = False
            for selected in tuple(bpy.context.selected_objects):
                selected.select_set(False)
            obj.select_set(True)
            bpy.context.view_layer.objects.active = obj
            result = bpy.ops.object.modifier_apply(modifier=modifier.name)
            obj.select_set(False)
            if "FINISHED" not in result:
                raise RuntimeError(
                    "Could not apply the bounded Decimate modifier to imported model part "
                    + str(obj.name) + ": " + repr(result)
                )
            decimated_names.add(str(obj.name))
        applied_passes += 1

    render_faces = sum(len(obj.data.polygons) for obj in valid_meshes)
    report = {
        "original_faces": int(original_faces),
        "render_faces": int(render_faces),
        "face_limit": int(budget),
        "decimation_ratio": round(float(combined_ratio), 6),
        "passes": int(applied_passes),
        "preserved_faces": int(fixed_faces),
        "preserved_meshes": len(fixed_meshes),
        "decimated_meshes": len(decimated_names),
    }
    if render_faces > budget * 1.35:
        raise RuntimeError(
            "Imported violin remains above the CPU render geometry budget after "
            + str(applied_passes) + " collapse passes: "
            + json.dumps(report, ensure_ascii=False)
        )
    return report

def _run_geometry_budget_smoke(face_limit=700):
    """Exercise the same Blender Decimate path on a temporary high-poly mesh."""
    bpy.ops.mesh.primitive_uv_sphere_add(segments=64, ring_count=32, radius=1.0)
    probe = bpy.context.object
    original_faces = len(probe.data.polygons)
    report = decimate_render_meshes([probe], face_limit=face_limit)
    bpy.data.objects.remove(probe, do_unlink=True)
    if original_faces <= face_limit or report["render_faces"] > face_limit * 1.35:
        raise RuntimeError(
            "Blender geometry-budget smoke did not reduce the temporary mesh: "
            + json.dumps(report, ensure_ascii=False)
        )
    print("MODEL_GEOMETRY_SMOKE=" + json.dumps(report, ensure_ascii=False), flush=True)
    return report


def import_gltf_asset(filepath, face_limit=60000):
    """Import and normalize a downloaded Sketchfab glTF/GLB violin asset."""
    path = Path(filepath).expanduser().resolve()
    if not path.is_file() or path.suffix.casefold() not in {".gltf", ".glb"}:
        raise ValueError("The approved violin asset path must point to an existing .gltf or .glb file.")
    importer = getattr(bpy.ops.import_scene, "gltf", None)
    if importer is None:
        raise RuntimeError("This Blender installation does not provide its glTF importer.")

    before = set(bpy.context.scene.objects)
    result = importer(filepath=str(path))
    if "FINISHED" not in result:
        raise RuntimeError("Blender's glTF importer did not finish successfully.")
    imported = [obj for obj in bpy.context.scene.objects if obj not in before]
    meshes = [obj for obj in imported if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("The downloaded asset contains no mesh geometry.")

    def object_name_chain(obj):
        names = []
        current = obj
        while current is not None:
            names.append(str(current.name).casefold())
            current = current.parent
        return " ".join(names)

    source_bows = [
        obj for obj in meshes
        if any(token in object_name_chain(obj).replace(" ", "") for token in
               ("bow", "bowstick", "bowhair", "horsehair", "bowfrog"))
    ]
    for source_bow in source_bows:
        source_bow.hide_render = True
        source_bow.hide_set(True)
    meshes = [obj for obj in meshes if obj not in source_bows]
    if not meshes:
        raise RuntimeError("The downloaded model contained no visible subject geometry after excluding its source bow.")
    source_strings = [obj for obj in meshes if "string" in object_name_chain(obj)]
    geometry_report = decimate_render_meshes(
        meshes, face_limit=face_limit, preserve_meshes=source_strings
    )
    print("MODEL_GEOMETRY_REPORT=" + json.dumps(geometry_report, ensure_ascii=False), flush=True)

    bpy.context.view_layer.update()
    corners = [
        obj.matrix_world @ Vector(corner)
        for obj in meshes
        for corner in obj.bound_box
    ]
    minimum = Vector((
        min(point.x for point in corners),
        min(point.y for point in corners),
        min(point.z for point in corners),
    ))
    maximum = Vector((
        max(point.x for point in corners),
        max(point.y for point in corners),
        max(point.z for point in corners),
    ))
    center = (minimum + maximum) * 0.5
    dimensions = maximum - minimum
    dimension_values = [float(dimensions.x), float(dimensions.y), float(dimensions.z)]
    length_axis = max(range(3), key=lambda axis: dimension_values[axis])
    depth_axis = min(range(3), key=lambda axis: dimension_values[axis])
    width_axis = next(axis for axis in range(3) if axis not in {length_axis, depth_axis})
    if dimension_values[length_axis] <= 1e-6 or dimension_values[width_axis] <= 1e-6:
        raise RuntimeError("The imported model has invalid or degenerate dimensions.")

    # Re-orient the longest instrument axis vertically (Z), the thinnest axis
    # into depth (Y), and the remaining axis across the body (X). Keep a proper
    # right-handed transform; the camera can then be placed consistently.
    permutation = [width_axis, depth_axis, length_axis]
    inversions = sum(
        1 for i in range(3) for j in range(i + 1, 3)
        if permutation[i] > permutation[j]
    )
    depth_sign = -1.0 if inversions % 2 else 1.0
    scale = 4.0 / dimension_values[length_axis]
    transform = Matrix.Identity(4)
    for row in range(3):
        for column in range(3):
            transform[row][column] = 0.0
    transform[0][width_axis] = scale
    transform[1][depth_axis] = depth_sign * scale
    transform[2][length_axis] = scale
    transform[0][3] = -center[width_axis] * scale
    transform[1][3] = -center[depth_axis] * depth_sign * scale
    transform[2][3] = -center[length_axis] * scale

    root = bpy.data.objects.new("Imported Sketchfab violin asset root", None)
    bpy.context.collection.objects.link(root)
    root.empty_display_type = "PLAIN_AXES"
    root.empty_display_size = 0.18
    root["source_bow_meshes_hidden"] = len(source_bows)
    root["source_string_meshes"] = len(source_strings)

    imported_set = set(imported)
    top_level = [obj for obj in imported if obj.parent not in imported_set]
    for obj in top_level:
        world_matrix = obj.matrix_world.copy()
        obj.parent = root
        obj.matrix_parent_inverse = Matrix.Identity(4)
        obj.matrix_basis = world_matrix
    root.matrix_world = transform
    root["source_asset"] = str(path)
    root["normalization"] = "Longest axis vertical, thinnest axis front-to-back"
    bpy.context.view_layer.update()

    transformed_corners = [
        obj.matrix_world @ Vector(corner)
        for obj in meshes
        for corner in obj.bound_box
    ]
    front_y = min(point.y for point in transformed_corners)
    width = max(point.x for point in transformed_corners) - min(point.x for point in transformed_corners)
    depth = max(point.y for point in transformed_corners) - front_y
    bounds = {
        "front_y": float(front_y),
        "width": float(width),
        "depth": float(depth),
        "min_z": float(min(point.z for point in transformed_corners)),
        "max_z": float(max(point.z for point in transformed_corners)),
        "center_z": float((min(point.z for point in transformed_corners) + max(point.z for point in transformed_corners)) * 0.5),
        "source_bow_meshes_hidden": len(source_bows),
        "source_string_meshes": len(source_strings),
        "geometry_report": geometry_report,
    }
    root["geometry_report"] = json.dumps(geometry_report, ensure_ascii=False)
    return root, bounds


def add_bow_for_imported_violin(bounds, mat_wood, mat_strings, frame_end, mat_ebony):
    """Create one bow assembly with a single animated root over the source strings."""
    front_y = float(bounds["front_y"]) - 0.055
    half_span = max(0.72, min(1.32, float(bounds["width"]) * 0.70))
    bridge_z = float(bounds.get("center_z", 0.0)) - 0.32
    rig = bpy.data.objects.new("BOW RIG — one animated control", None)
    bpy.context.collection.objects.link(rig)
    rig.empty_display_type = "PLAIN_AXES"
    rig.empty_display_size = 0.18
    rig["rig_type"] = "single_parented_bow_assembly"
    rig["visible_bow_rig_count"] = 1

    bow = add_curve(
        "Bow rig | maple stick",
        [
            (-half_span, front_y - 0.105, bridge_z + 0.045),
            (-half_span * 0.5, front_y - 0.100, bridge_z + 0.020),
            (0.0, front_y - 0.098, bridge_z),
            (half_span * 0.5, front_y - 0.100, bridge_z - 0.020),
            (half_span, front_y - 0.105, bridge_z - 0.045),
        ],
        mat_wood, bevel=0.018,
    )
    hair = add_curve(
        "Bow rig | horsehair",
        [
            (-half_span, front_y - 0.032, bridge_z + 0.010),
            (-half_span * 0.5, front_y - 0.030, bridge_z + 0.005),
            (0.0, front_y - 0.029, bridge_z),
            (half_span * 0.5, front_y - 0.030, bridge_z - 0.005),
            (half_span, front_y - 0.032, bridge_z - 0.010),
        ],
        mat_strings, bevel=0.0045,
    )
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(-half_span + 0.16, front_y - 0.075, bridge_z))
    frog = bpy.context.object
    frog.name = "Bow rig | ebony frog"
    frog.dimensions = (0.23, 0.06, 0.07)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    frog.data.materials.append(mat_ebony)
    edge = frog.modifiers.new("Rounded frog edges", "BEVEL")
    edge.width = 0.015
    edge.segments = 3
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=16, ring_count=8, radius=0.03,
        location=(half_span - 0.015, front_y - 0.105, bridge_z - 0.045),
    )
    tip = bpy.context.object
    tip.name = "Bow rig | tip"
    tip.data.materials.append(mat_wood)

    for component in (bow, hair, frog, tip):
        matrix = component.matrix_world.copy()
        component.parent = rig
        component.matrix_parent_inverse = Matrix.Identity(4)
        component.matrix_basis = matrix
    for fraction, x_shift, z_shift in (
        (0.00, 0.0, 0.0), (0.25, 0.11, 0.01), (0.50, -0.11, -0.008),
        (0.75, 0.10, 0.008), (1.00, 0.0, 0.0),
    ):
        frame = max(1, min(frame_end, int(round(1 + (frame_end - 1) * fraction))))
        rig.location = (x_shift, 0.0, z_shift)
        rig.keyframe_insert(data_path="location", frame=frame)
    for curve in action_fcurves(rig):
        for point in curve.keyframe_points:
            point.interpolation = "BEZIER"
            point.handle_left_type = "AUTO"
            point.handle_right_type = "AUTO"
    rig["animation"] = "One rig moves stick, horsehair, frog and tip together."
    return rig


def build_scene(config):
    global _TIMINGS
    build_started = time.perf_counter()
    _TIMINGS = {
        "schema_version": 1,
        "status": "building_scene",
        "scene_type": str(config.get("scene_type") or ""),
        "pid": os.getpid(),
        "started_at_utc": datetime.now(timezone.utc).isoformat(),
        "process_elapsed_at_build_start_seconds": round(build_started - _PROCESS_START, 6),
        "diagnostics_path": str(config.get("diagnostics_path") or ""),
        "stages": {},
        "frames": [],
        "renderer": {},
    }
    clear_scene()
    if bool(config.get("geometry_budget_smoke", False)):
        _run_geometry_budget_smoke(int(config.get("geometry_budget_smoke_limit", 700)))
    random.seed(int(config.get("seed", 1)))
    scene_type = str(config.get("scene_type") or "")
    frame_end = max(24, int(config.get("fps", 24) * config.get("duration_seconds", 3.0)))
    fps = max(12, min(int(config.get("fps", 24)), 30))

    wood = material("Violin Prince amber maple", (0.34, 0.13, 0.045), 0.18, 0.26, 0.02)
    gold = material("Antique gold fittings", (0.82, 0.48, 0.16), 0.65, 0.23, 0.12)
    teal = material("Resonance teal", (0.06, 0.48, 0.50), 0.38, 0.22, 0.35)
    silver = material("Steel strings", (0.62, 0.72, 0.78), 0.88, 0.18, 0.03)
    dark = material("Ebony and shadow", (0.018, 0.026, 0.040), 0.25, 0.30, 0.0)
    background = material("Midnight studio floor", (0.012, 0.022, 0.040), 0.32, 0.28, 0.0)

    if scene_type not in {
        "string_vibration", "bridge_cutaway", "wave_field",
        "melody_path", "comparison", "violin_performance",
    }:
        raise ValueError("Unsupported full-frame Blender scene type: " + scene_type)

    # A real studio set, not an alpha/transparent canvas.
    add_cube("Infinite midnight studio floor", (0.0, 0.8, -2.35), (200.0, 200.0, 0.15), background)
    add_cube("Midnight studio background wall", (0.0, 3.5, 3.0), (200.0, 0.2, 200.0), background)

    asset_path = str(config.get("model_asset_path") or "").strip()
    asset_kind = str(config.get("model_asset_kind") or "generic").casefold()
    model_root = None
    asset_bounds = None
    if asset_path:
        model_import_started = time.perf_counter()
        model_root, asset_bounds = import_gltf_asset(
            asset_path,
            face_limit=int(config.get("model_face_limit", 60000)),
        )
        _TIMINGS["stages"]["model_import_and_decimation_seconds"] = round(
            time.perf_counter() - model_import_started, 6
        )
        model_root["story_asset_kind"] = asset_kind
        model_root.keyframe_insert(data_path="rotation_euler", frame=1)
        model_root.rotation_euler.y = 0.018
        model_root.rotation_euler.z = -0.012
        model_root.keyframe_insert(data_path="rotation_euler", frame=frame_end)
        if asset_kind == "violin":
            bow_wood = material("Bow maple wood", (0.28, 0.095, 0.028), 0.05, 0.27, 0.0)
            ebony = material("Bow frog ebony", (0.012, 0.016, 0.022), 0.08, 0.24, 0.0)
            rig = add_bow_for_imported_violin(asset_bounds, bow_wood, silver, frame_end, ebony)
            model_root["visible_bow_rig_count"] = 1
            model_root["bow_rig_name"] = rig.name
        else:
            model_root["visible_bow_rig_count"] = 0

        # The real mesh is the visual subject. Motion graphics are deliberately
        # restrained so they explain the asset instead of replacing it.
        if scene_type in {"string_vibration", "bridge_cutaway", "wave_field"}:
            for index, radius in enumerate((1.15, 1.60, 2.05)):
                add_ripple_ring(
                    f"Story model resonance ring {index + 1}",
                    radius, float(asset_bounds["front_y"]) - 0.22,
                    teal, frame_end, index * 0.08,
                )
        elif scene_type == "melody_path":
            add_melody_path(gold, teal, frame_end)
        elif scene_type == "comparison":
            for index, x in enumerate((-1.6, 1.6)):
                add_curve(
                    f"Comparison guide {index + 1}",
                    [(x, -0.3, -1.1), (x, -0.3, 1.1)],
                    teal if index == 0 else gold, bevel=0.012,
                )

    elif scene_type in {"string_vibration", "bridge_cutaway", "wave_field"}:
        bridge = add_bridge(wood)
        bridge.location.z = -0.10 if scene_type != "string_vibration" else -0.55
        for index in range(4):
            z = 0.28 + (index - 1.5) * 0.13
            add_vibrating_string(
                f"Animated violin string {index + 1}",
                -2.2, 2.2, -0.42 + index * 0.028, z,
                teal if index == 0 else silver, frame_end, index,
            )
        for index, radius in enumerate((1.0, 1.5, 2.0)):
            add_ripple_ring(
                f"Expanding acoustic resonance ring {index + 1}",
                radius, 0.5 + index * 0.05, teal, frame_end, index * 0.08,
            )
        bridge.keyframe_insert(data_path="rotation_euler", frame=1)
        bridge.rotation_euler.z = 0.045
        bridge.keyframe_insert(data_path="rotation_euler", frame=frame_end)

    elif scene_type == "melody_path":
        add_melody_path(gold, teal, frame_end)

    elif scene_type == "comparison":
        first = add_bridge(wood)
        second = add_bridge(gold)
        first.location.x = -1.0
        second.location.x = 1.0
        first.scale = (0.62, 0.62, 0.62)
        second.scale = (0.62, 0.62, 0.82)
        for obj, direction in ((first, -0.06), (second, 0.06)):
            obj.keyframe_insert(data_path="rotation_euler", frame=1)
            obj.rotation_euler.y = direction
            obj.keyframe_insert(data_path="rotation_euler", frame=frame_end)
        for index in range(4):
            z = 0.32 + (index - 1.5) * 0.12
            add_vibrating_string(
                f"Comparison string {index + 1}", -2.25, 2.25,
                -0.48 + index * 0.03, z, teal if index == 0 else silver, frame_end, index,
            )

    elif scene_type == "violin_performance":
        raise RuntimeError(
            "A real downloaded violin asset is required for cover_performance. "
            "The procedural placeholder violin is deliberately disabled."
        )

    # Suspended dust particles are true 3D objects with their own transforms.
    for index in range(18):
        x = random.uniform(-2.5, 2.5)
        z = random.uniform(-2.0, 2.6)
        y = random.uniform(0.4, 1.4)
        particle = add_sphere(
            f"Floating studio particle {index + 1}",
            (x, y, z), random.uniform(0.018, 0.045),
            gold if index % 3 else teal,
        )
        particle.keyframe_insert(data_path="location", frame=1)
        particle.location.z += random.uniform(0.10, 0.45)
        particle.location.x += random.uniform(-0.12, 0.12)
        particle.keyframe_insert(data_path="location", frame=frame_end)

    add_area_light("Warm cinematic key", (4.5, -5.5, 5.5), 850, (1.0, 0.70, 0.42), 5.0)
    add_area_light("Cool teal fill", (-4.0, -2.5, 1.0), 520, (0.35, 0.75, 0.85), 4.0)
    add_area_light("Amber rim light", (0.0, 2.2, 4.5), 680, (1.0, 0.45, 0.17), 3.5)

    camera_data = bpy.data.cameras.new("Animated Violin Prince cinema camera")
    camera = bpy.data.objects.new("Animated Violin Prince cinema camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera_data.lens = 48.0
    camera_data.sensor_fit = "VERTICAL"
    benchmark_overrides = config.get("benchmark_overrides") or {}
    camera_data.dof.use_dof = not bool(benchmark_overrides.get("disable_dof", False))
    camera_data.dof.aperture_fstop = 5.6

    # A tracked focus object keeps the violin composed while the camera travels.
    focus_target = bpy.data.objects.new("Animated camera focus target", None)
    bpy.context.collection.objects.link(focus_target)
    focus_target.empty_display_type = "SPHERE"
    focus_target.empty_display_size = 0.12
    focus_target.location = (0.0, -0.12, 0.55)
    camera_data.dof.focus_object = focus_target

    track = camera.constraints.new(type="TRACK_TO")
    track.name = "Keep the violin in cinematic focus"
    track.target = focus_target
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"

    scene = bpy.context.scene
    scene.camera = camera

    # Five distinct animated camera beats: establish, left reveal, cross-front
    # sweep, right-side orbit and a final controlled dolly-in. Both the camera
    # and the aim point are keyframed in Blender; this is not post-render zoom.
    camera_moves = [
        (1, (-0.45, -12.4, 0.45), (0.0, -0.12, 0.48), 48.0),
        (1 + frame_end // 4, (-1.75, -10.8, 1.05), (0.0, -0.12, 0.62), 52.0),
        (1 + frame_end // 2, (0.95, -9.9, 1.15), (0.0, -0.12, 0.74), 55.0),
        (1 + (3 * frame_end) // 4, (2.00, -10.7, 0.30), (0.0, -0.12, 0.45), 52.0),
        (frame_end, (0.25, -9.0, 0.95), (0.0, -0.12, 0.72), 58.0),
    ]
    for frame, camera_position, aim_position, focal_length in camera_moves:
        camera.location = camera_position
        camera.keyframe_insert(data_path="location", frame=frame)
        focus_target.location = aim_position
        focus_target.keyframe_insert(data_path="location", frame=frame)
        camera.data.lens = focal_length
        camera.data.keyframe_insert(data_path="lens", frame=frame)

    # Set the first frame explicitly after all camera keys are authored.
    scene.frame_set(1)
    bpy.context.view_layer.update()

    # Daily production must use the pinned Frame By Plane extension. It builds
    # depth-separated image planes behind the real 3D hero model; it is not
    # merely installed as an unused add-on.
    frame_by_plane_report = None
    background_manifest = str(config.get("frame_by_plane_manifest") or "").strip()
    frame_by_plane_required = bool(config.get("frame_by_plane_required", False))
    if frame_by_plane_required and not background_manifest:
        raise RuntimeError("This daily scene requires a Frame By Plane background manifest.")
    frame_by_plane_started = time.perf_counter()
    if background_manifest:
        from frame_by_plane_adapter import build_frame_by_plane_background
        instrument_front_y = (
            float(asset_bounds["front_y"])
            if isinstance(asset_bounds, dict) and asset_bounds.get("front_y") is not None
            else -0.30
        )
        frame_by_plane_report = build_frame_by_plane_background(
            background_manifest,
            camera,
            instrument_front_y,
            frame_end,
            expected_blender="5.2.4",
            expected_extension="8.0.1",
        )
        if int(frame_by_plane_report.get("layer_count", 0)) < 3:
            raise RuntimeError("Frame By Plane did not create the three required cinematic depth layers.")
    _TIMINGS["stages"]["frame_by_plane_setup_seconds"] = round(
        time.perf_counter() - frame_by_plane_started, 6
    )

    world = bpy.data.worlds.new("Violin Prince midnight atmosphere")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.006, 0.012, 0.025, 1.0)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.22
    scene.world = world

    # Eevee produces full-frame real 3D animation at a practical CPU cost.
    engines = scene.render.bl_rna.properties["engine"].enum_items.keys()
    if "BLENDER_EEVEE_NEXT" in engines:
        scene.render.engine = "BLENDER_EEVEE_NEXT"
    elif "BLENDER_EEVEE" in engines:
        scene.render.engine = "BLENDER_EEVEE"
    else:
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = 8

    if hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = max(1, min(int(config.get("samples", 4)), 32))
    if bool(benchmark_overrides.get("disable_shadows", False)):
        for light_object in (obj for obj in scene.objects if obj.type == "LIGHT"):
            if hasattr(light_object.data, "use_shadow"):
                light_object.data.use_shadow = False
    scene.render.threads_mode = "FIXED"
    scene.render.threads = max(1, min(int(config.get("threads", 2)), 2))
    scene.render.resolution_x = max(160, min(int(config.get("width", 360)), 1920))
    scene.render.resolution_y = max(284, min(int(config.get("height", 640)), 1920))
    scene.render.resolution_percentage = 100
    scene.render.fps = fps
    scene.frame_start = 1
    scene.frame_end = frame_end
    scene.frame_step = 1
    scene.render.film_transparent = False

    benchmark_max_frames = max(0, min(int(config.get("benchmark_max_frames", 0) or 0), 8))
    if benchmark_max_frames:
        scene.frame_end = min(int(scene.frame_end), benchmark_max_frames)

    scene.view_settings.view_transform = "AgX" if "AgX" in scene.view_settings.bl_rna.properties["view_transform"].enum_items.keys() else "Standard"

    depsgraph_started = time.perf_counter()
    depsgraph = bpy.context.evaluated_depsgraph_get()
    try:
        depsgraph.update()
    except Exception:
        bpy.context.view_layer.update()
    _TIMINGS["stages"]["depsgraph_update_seconds"] = round(
        time.perf_counter() - depsgraph_started, 6
    )
    _TIMINGS["stages"]["scene_build_total_seconds"] = round(
        time.perf_counter() - build_started, 6
    )
    _TIMINGS["stages"]["elapsed_before_render_seconds"] = round(
        time.perf_counter() - _PROCESS_START, 6
    )
    _TIMINGS["renderer"] = {
        "blender_version": str(getattr(bpy.app, "version_string", "unknown")),
        "render_engine": str(scene.render.engine),
        "gpu_platform": _gpu_runtime_info(),
        "resolution": [int(scene.render.resolution_x), int(scene.render.resolution_y)],
        "resolution_percentage": int(scene.render.resolution_percentage),
        "fps": int(scene.render.fps),
        "eevee_render_samples": (
            int(scene.eevee.taa_render_samples)
            if hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples")
            else None
        ),
        "threads": int(scene.render.threads),
        "depth_of_field_enabled": bool(camera_data.dof.use_dof),
        "frame_by_plane_enabled": bool(frame_by_plane_report),
        "frame_by_plane_layers": int(frame_by_plane_report.get("layer_count", 0))
        if isinstance(frame_by_plane_report, dict) else 0,
        "model_asset_kind": str(config.get("model_asset_kind") or ""),
    }
    _TIMINGS["benchmark"] = {
        "max_sample_frames": benchmark_max_frames or None,
        "overrides": benchmark_overrides,
        "preflight_enabled": bool(config.get("preflight_enabled", False)),
    }
    _write_timing_report()

    # The CI integration proof renders one actual composed frame. It exercises
    # model/scene construction, the slotted Action API, camera setup, native
    # Frame By Plane geometry and the final Eevee composition without spending
    # several minutes encoding a throwaway animation on software-rendered CI.
    # The normal daily production path remains the full animated FFmpeg render.
    if bool(config.get("smoke_still", False)):
        image_settings = scene.render.image_settings
        if hasattr(image_settings, "media_type"):
            image_settings.media_type = "IMAGE"
        image_settings.file_format = "PNG"
        image_settings.color_mode = "RGBA"
        scene.render.use_file_extension = False
        still_path = Path(config["output"]).resolve()
        scene.render.filepath = str(still_path)
        smoke_frame = max(1, min(frame_end, int(config.get("smoke_frame", 1))))
        scene.frame_set(smoke_frame)
        bpy.context.view_layer.update()
        render_handlers = _register_render_telemetry(scene, config)
        render_started = time.perf_counter()
        result = bpy.ops.render.render(write_still=True)
        _remove_render_telemetry_handlers(render_handlers)
        _TIMINGS["stages"]["still_render_wall_seconds"] = round(
            time.perf_counter() - render_started, 6
        )
        _TIMINGS["status"] = "rendered_smoke_still"
        _write_timing_report()
        if "FINISHED" not in result or not still_path.is_file():
            raise RuntimeError(
                "Blender did not write the Frame By Plane smoke still: "
                + str(still_path)
                + "; operator_result="
                + repr(result)
            )
    else:
        # Blender 5 distinguishes image and video media types. VIDEO must be set
        # before the FFMPEG file format, otherwise headless animation may not write.
        if hasattr(scene.render.image_settings, "media_type"):
            scene.render.image_settings.media_type = "VIDEO"
        scene.render.image_settings.file_format = "FFMPEG"
        scene.render.use_file_extension = True
        scene.render.ffmpeg.format = "MPEG4"
        scene.render.ffmpeg.codec = "H264"
        scene.render.ffmpeg.constant_rate_factor = "HIGH"
        scene.render.ffmpeg.ffmpeg_preset = "GOOD"
        scene.render.ffmpeg.gopsize = fps
        scene.render.filepath = str(Path(config["output"]).resolve().with_suffix(""))
        scene.frame_set(1)
        render_handlers = _register_render_telemetry(scene, config)
        render_started = time.perf_counter()
        render_result = bpy.ops.render.render(animation=True)
        _remove_render_telemetry_handlers(render_handlers)
        _TIMINGS["stages"]["animation_render_wall_seconds"] = round(
            time.perf_counter() - render_started, 6
        )
        if _TIMINGS.get("preflight", {}).get("status") == "aborted":
            _TIMINGS["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
            _write_timing_report()
            raise RuntimeError(
                "Blender preflight cancelled the animation after measured frame "
                + str(_TIMINGS.get("last_frame_completed", "unknown"))
                + ". See "
                + str(config.get("preflight_report_path") or "preflight-abort-report.json")
            )
        if "FINISHED" not in render_result:
            raise RuntimeError(
                "Blender animation render operator did not finish: "
                + repr(render_result)
                + "; output_prefix="
                + scene.render.filepath
            )
        _TIMINGS["status"] = "rendered"
        _TIMINGS["ended_at_utc"] = datetime.now(timezone.utc).isoformat()
        _write_timing_report()
    return frame_by_plane_report


def main():
    args = parse_arguments()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    config["output"] = args.output
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    frame_by_plane_report = build_scene(config)
    if frame_by_plane_report is not None:
        print("FRAME_BY_PLANE_REPORT=" + json.dumps(frame_by_plane_report, ensure_ascii=False), flush=True)
    print("BLENDER_FULL_FRAME_3D_RENDERED=" + str(Path(args.output).resolve()), flush=True)


if __name__ == "__main__":
    main()
