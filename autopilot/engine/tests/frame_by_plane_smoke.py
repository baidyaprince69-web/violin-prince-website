"""One-frame headless Blender test for the pinned Frame By Plane integration."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import bpy

ENGINE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ENGINE))
from frame_by_plane_adapter import build_frame_by_plane_background, verify_frame_by_plane


def main():
    raw=sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
    parser=argparse.ArgumentParser()
    parser.add_argument("--manifest",required=True)
    parser.add_argument("--output-dir",required=True)
    parser.add_argument("--report",required=True)
    args=parser.parse_args(raw)
    runtime=verify_frame_by_plane()
    scene=bpy.context.scene
    # Blender's background startup file contains a default cube, camera and
    # light. The cube sits directly in front of this test's background planes
    # and falsely appears as a large gray occlusion in the smoke render.
    # Start from a clean object scene so this test measures FBP layer output.
    for existing_object in tuple(bpy.data.objects):
        bpy.data.objects.remove(existing_object, do_unlink=True)
    scene.camera = None
    engines={item.identifier for item in scene.render.bl_rna.properties["engine"].enum_items}
    scene.render.engine="BLENDER_EEVEE" if "BLENDER_EEVEE" in engines else "BLENDER_EEVEE_NEXT"
    scene.render.resolution_x=360
    scene.render.resolution_y=640
    scene.render.resolution_percentage=100
    scene.render.image_settings.file_format="PNG"
    scene.render.fps=25

    camera_data=bpy.data.cameras.new("FBP smoke camera data")
    camera=bpy.data.objects.new("FBP smoke camera",camera_data)
    scene.collection.objects.link(camera)
    camera.location=(0.0,-8.0,0.0)
    camera.rotation_euler=(1.57079632679,0.0,0.0)
    camera_data.lens=50
    camera_data.sensor_fit="VERTICAL"
    camera_data.sensor_height=24
    scene.camera=camera

    result=build_frame_by_plane_background(args.manifest,camera,instrument_front_y=0.0,frame_end=2)
    if result["layer_count"]!=3:
        raise RuntimeError(f"Expected 3 Frame By Plane layers, got {result['layer_count']}")
    scene.frame_set(1)
    output_dir=Path(args.output_dir)
    output_dir.mkdir(parents=True,exist_ok=True)
    frame_path=output_dir/"frame-by-plane-smoke.png"
    scene.render.filepath=str(frame_path)
    bpy.ops.render.render(write_still=True)
    blend_path=output_dir/"frame-by-plane-smoke.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend_path))
    report={
        "status":"frame_by_plane_smoke_rendered",
        "blender_version":runtime["blender_version"],
        "extension_version":runtime["extension_version"],
        "layer_count":result["layer_count"],
        "layers":result["layers"],
        "render_resolution":[scene.render.resolution_x,scene.render.resolution_y],
        "render_file":str(frame_path),"blend_file":str(blend_path),
        "note":"One-frame image-layer integration test, not the 115-frame violin proof.",
    }
    Path(args.report).parent.mkdir(parents=True,exist_ok=True)
    Path(args.report).write_text(json.dumps(report,indent=2)+"\n",encoding="utf-8")
    print("FRAME_BY_PLANE_SMOKE_REPORT="+json.dumps(report))


if __name__=="__main__":
    main()
