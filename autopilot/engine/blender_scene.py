"""Blender-side procedural scene builder. Executed by Blender's bundled Python."""
from __future__ import annotations

import argparse
import json
import math
import random
import sys
from pathlib import Path

import bpy
from mathutils import Vector


def parse_arguments():
    raw = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--config", required=True)
    parser.add_argument("--output", required=True)
    return parser.parse_args(raw)


def clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        for item in list(datablocks):
            if item.users == 0:
                datablocks.remove(item)


def make_material(name, color, metallic=0.0, roughness=0.35, emission=0.0):
    material = bpy.data.materials.new(name=name)
    material.diffuse_color = (*color, 1.0)
    material.use_nodes = True
    shader = material.node_tree.nodes.get("Principled BSDF")
    if shader:
        base = shader.inputs.get("Base Color")
        if base:
            base.default_value = (*color, 1.0)
        metal = shader.inputs.get("Metallic")
        if metal:
            metal.default_value = metallic
        rough = shader.inputs.get("Roughness")
        if rough:
            rough.default_value = roughness
        emission_color = shader.inputs.get("Emission Color") or shader.inputs.get("Emission")
        if emission_color:
            emission_color.default_value = (*color, 1.0)
        emission_strength = shader.inputs.get("Emission Strength")
        if emission_strength:
            emission_strength.default_value = emission
    return material


def add_curve(name, coordinates, material, bevel_depth=0.025):
    curve = bpy.data.curves.new(name=name, type="CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 12
    curve.bevel_depth = bevel_depth
    curve.bevel_resolution = 3
    spline = curve.splines.new("POLY")
    spline.points.add(max(0, len(coordinates) - 1))
    for point, coordinate in zip(spline.points, coordinates):
        point.co = (coordinate[0], coordinate[1], coordinate[2], 1.0)
    obj = bpy.data.objects.new(name, curve)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def add_sphere(name, location, radius, material):
    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=16, ring_count=10, radius=radius, location=location
    )
    obj = bpy.context.object
    obj.name = name
    obj.data.materials.append(material)
    for polygon in obj.data.polygons:
        polygon.use_smooth = True
    return obj


def add_area_light(name, location, energy, color, size):
    bpy.ops.object.light_add(type="AREA", location=location)
    light = bpy.context.object
    light.name = name
    light.data.energy = energy
    light.data.color = color
    light.data.shape = "DISK"
    light.data.size = size
    direction = Vector((0.0, 0.0, 0.0)) - light.location
    light.rotation_euler = direction.to_track_quat("-Z", "Y").to_euler()
    return light


def add_bridge(material):
    # A simple, deliberately stylised bridge model; it is not presented as a
    # dimensionally accurate instrument component.
    profile = [
        (-1.00, -0.82), (1.00, -0.82), (0.76, -0.28),
        (0.43, 0.56), (-0.43, 0.56), (-0.76, -0.28),
    ]
    depth = 0.24
    vertices = [(x, -depth, z) for x, z in profile] + [
        (x, depth, z) for x, z in profile
    ]
    count = len(profile)
    faces = [tuple(range(count)), tuple(reversed(range(count, count * 2)))]
    for index in range(count):
        next_index = (index + 1) % count
        faces.append((index, next_index, count + next_index, count + index))
    mesh = bpy.data.meshes.new("Stylised violin bridge mesh")
    mesh.from_pydata(vertices, [], faces)
    mesh.materials.append(material)
    mesh.update()
    obj = bpy.data.objects.new("Stylised violin bridge", mesh)
    bpy.context.collection.objects.link(obj)
    bevel = obj.modifiers.new("Soft crafted edges", "BEVEL")
    bevel.width = 0.055
    bevel.segments = 3
    obj.modifiers.new("Weighted corner normals", "WEIGHTED_NORMAL")
    return obj


def add_wave_rings(material, phase=0.0):
    for ring_index, radius in enumerate((1.35, 1.85, 2.35)):
        coordinates = []
        for step in range(65):
            angle = math.radians(205 + (130 * step / 64))
            x = math.cos(angle) * radius
            z = math.sin(angle) * radius * 0.68
            y = 0.42 + ring_index * 0.035
            coordinates.append((x, y, z + phase * 0.05))
        add_curve(f"Acoustic wave ring {ring_index + 1}", coordinates, material, 0.012)


def build_scene(config):
    clear_scene()
    seed = int(config.get("seed", 1))
    random.seed(seed)

    gold = make_material("Violin Prince antique gold", (0.82, 0.48, 0.17), metallic=0.62, roughness=0.27, emission=0.16)
    teal = make_material("Violin Prince muted teal", (0.10, 0.63, 0.63), metallic=0.35, roughness=0.30, emission=0.30)
    silver = make_material("Brushed silver strings", (0.55, 0.70, 0.76), metallic=0.82, roughness=0.20, emission=0.05)
    wood = make_material("Warm amber bridge wood", (0.31, 0.13, 0.055), metallic=0.12, roughness=0.31, emission=0.02)

    scene_type = str(config.get("scene_type") or "")
    if scene_type not in {"string_vibration", "bridge_cutaway"}:
        raise ValueError("Unsupported Blender scene type.")

    if scene_type == "bridge_cutaway":
        add_bridge(wood)
        string_height = 0.78
        for leg_x in (-0.56, 0.56):
            add_curve(
                "Bridge foot",
                [(leg_x * 0.7, -0.16, -0.80), (leg_x, -0.20, -0.28), (leg_x * 0.75, -0.18, 0.45)],
                gold,
                0.045,
            )
    else:
        string_height = 0.05

    # Four separate strings, plus a visible oscillation ribbon on the foreground string.
    for index in range(4):
        offset = (index - 1.5) * 0.12
        points = []
        for step in range(85):
            x = -2.25 + (4.5 * step / 84)
            oscillation = 0.22 * math.sin((x + 2.25) * 4.0 + seed % 17) * (1.0 - 0.18 * abs(x))
            if index:
                oscillation *= 0.12
            points.append((x, -0.42 + index * 0.025, string_height + offset + oscillation))
        add_curve(f"Violin string {index + 1}", points, teal if index == 0 else silver, 0.018 if index else 0.028)

    add_wave_rings(teal, phase=(seed % 11) / 11.0)

    # Small, restrained 3D particles give the overlay a sense of depth.
    for index in range(14):
        x = random.uniform(-2.25, 2.25)
        z = random.uniform(-2.8, 2.8)
        y = random.uniform(-0.05, 0.65)
        radius = random.uniform(0.018, 0.045)
        add_sphere(f"Floating light {index + 1}", (x, y, z), radius, gold if index % 3 else teal)

    add_area_light("Warm key", (4.5, -5.5, 5.5), 720, (1.0, 0.72, 0.43), 5.0)
    add_area_light("Cool fill", (-4.0, -2.5, 1.0), 420, (0.38, 0.78, 0.85), 4.0)
    add_area_light("Amber rim", (0.0, 3.0, 4.5), 560, (1.0, 0.48, 0.18), 3.0)

    camera_data = bpy.data.cameras.new("Violin Prince 3D camera")
    camera = bpy.data.objects.new("Violin Prince 3D camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera.location = (0.0, -13.5, 0.45)
    camera_data.type = "ORTHO"
    camera_data.ortho_scale = 8.0
    camera.rotation_euler = (Vector((0.0, 0.0, 0.0)) - camera.location).to_track_quat("-Z", "Y").to_euler()
    scene = bpy.context.scene
    scene.camera = camera

    scene.render.engine = "CYCLES"
    scene.cycles.device = "CPU"
    scene.cycles.samples = max(1, min(int(config.get("samples", 6)), 16))
    if hasattr(scene.cycles, "use_denoising"):
        scene.cycles.use_denoising = False
    scene.render.threads_mode = "FIXED"
    scene.render.threads = max(1, min(int(config.get("threads", 2)), 2))
    scene.render.resolution_x = max(64, min(int(config.get("width", 540)), 1920))
    scene.render.resolution_y = max(64, min(int(config.get("height", 960)), 1920))
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.image_settings.color_depth = "8"
    scene.render.image_settings.compression = 18
    scene.render.film_transparent = True
    scene.render.resolution_percentage = 100
    scene.view_settings.view_transform = "Standard"

    if scene.world is None:
        scene.world = bpy.data.worlds.new("Transparent Violin Prince world")
    scene.world.use_nodes = True
    background = scene.world.node_tree.nodes.get("Background")
    if background:
        background.inputs.get("Strength").default_value = 0.0

    scene.render.filepath = str(Path(config["output"]).resolve())
    scene.frame_set(1)
    bpy.ops.render.render(write_still=True)


def main():
    args = parse_arguments()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    config["output"] = args.output
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    build_scene(config)
    print("BLENDER_SCENE_RENDERED=" + str(Path(args.output).resolve()))


if __name__ == "__main__":
    main()
