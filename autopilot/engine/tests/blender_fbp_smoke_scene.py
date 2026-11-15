"""Blender-side entry point for the isolated Frame By Plane smoke render."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy

ENGINE_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE_DIR))

import blender_scene


def verify_blender_action_slots() -> None:
    """Exercise the same F-curve helper used by scalar and bow-rig animation."""
    probe = bpy.data.objects.new("VP Smoke | slotted Action probe", None)
    bpy.context.scene.collection.objects.link(probe)
    probe.location = (0.0, 0.0, 0.0)
    probe.keyframe_insert(data_path="location", frame=1)
    probe.location.x = 0.5
    probe.location.z = 0.15
    probe.keyframe_insert(data_path="location", frame=24)

    curves = blender_scene.action_fcurves(probe)
    if len(curves) < 3:
        raise RuntimeError(
            "Blender's slotted Action API returned fewer than three location F-curves: "
            + str(len(curves))
        )
    for curve in curves:
        for point in curve.keyframe_points:
            point.interpolation = "BEZIER"
            point.handle_left_type = "AUTO"
            point.handle_right_type = "AUTO"

    camera_data = bpy.data.cameras.new("VP Smoke | scalar Action probe")
    blender_scene.animate_scalar(camera_data, "lens", [(1, 35.0), (24, 55.0)])
    scalar_curves = blender_scene.action_fcurves(camera_data)
    if not any(curve.data_path == "lens" for curve in scalar_curves):
        raise RuntimeError("Blender's slotted Action API did not expose the camera-lens F-curve.")
    if any(
        point.interpolation != "BEZIER"
        for curve in scalar_curves
        for point in curve.keyframe_points
    ):
        raise RuntimeError("The scalar animation helper did not apply Bezier interpolation.")

    bpy.data.objects.remove(probe, do_unlink=True)
    bpy.data.cameras.remove(camera_data)


def main() -> None:
    raw = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args(raw)

    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    config["output"] = args.output
    config["smoke_still"] = True
    if tuple(bpy.app.version[:3]) != (5, 2, 4):
        raise RuntimeError("The smoke test requires Blender 5.2.4; found " + str(bpy.app.version_string))

    verify_blender_action_slots()
    report = blender_scene.build_scene(config)
    if not isinstance(report, dict) or int(report.get("layer_count", 0)) != 3:
        raise RuntimeError("The scene did not build and report all three native Frame By Plane layers.")
    print("FRAME_BY_PLANE_REPORT=" + json.dumps(report, ensure_ascii=False), flush=True)
    print("BLENDER_FBP_SMOKE_STILL=" + str(Path(args.output).resolve()), flush=True)


if __name__ == "__main__":
    main()
