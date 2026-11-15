"""Create a Blender viewport reference scene without compositing it into renders.

This is only a modelling aid: the reference image is hidden from rendering and
is never used as a flat image plate in the finished video.
"""
from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path

import bpy


def parse_args():
    raw = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(raw)


def main():
    args = parse_args()
    image_path = Path(args.image).expanduser().resolve()
    manifest_path = Path(args.manifest).expanduser().resolve()
    output_path = Path(args.output).expanduser().resolve()
    if not image_path.is_file():
        raise FileNotFoundError("The authorized Sketchfab preview reference image is missing.")
    if not manifest_path.is_file():
        raise FileNotFoundError("The asset provenance manifest is missing.")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    image = bpy.data.images.load(str(image_path), check_existing=True)
    image.pack()  # Embed the reference so the downloaded .blend is self-contained.

    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)

    reference = bpy.data.objects.new("Sketchfab violin reference — viewport only", None)
    bpy.context.collection.objects.link(reference)
    reference.empty_display_type = "IMAGE"
    reference.data = image
    reference.empty_display_size = 4.0
    reference.empty_image_depth = "BACK"
    reference.rotation_euler.x = math.pi / 2.0
    reference.hide_render = True
    reference.hide_set(False)
    reference["source_url"] = str(manifest.get("source_url") or "")
    reference["creator"] = str(manifest.get("creator") or "")
    reference["license"] = str(manifest.get("license_label") or "Unknown")
    reference["usage_note"] = "Viewport modelling reference only; not part of rendered output."

    provenance = bpy.data.texts.new("Sketchfab asset provenance")
    provenance.write(json.dumps(manifest, ensure_ascii=False, indent=2))
    provenance.use_fake_user = True

    scene = bpy.context.scene
    scene["asset_resolution"] = "reference_only"
    scene["reference_source"] = str(manifest.get("source_url") or "")
    scene["reference_license"] = str(manifest.get("license_label") or "Unknown")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    bpy.ops.wm.save_as_mainfile(filepath=str(output_path))
    print("BLENDER_REFERENCE_SCENE_SAVED=" + str(output_path))


if __name__ == "__main__":
    main()
