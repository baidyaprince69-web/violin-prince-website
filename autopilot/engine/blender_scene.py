"""Procedural, fully opaque animated 3D scene generator for Blender.

The scene is rendered by Blender from its own camera into an MP4. No transparent
pass, pre-generated scene image or composited Blender overlay is used.
"""
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


def animate_scalar(obj, data_path, frames_values, cycle=False):
    for frame, value in frames_values:
        setattr(obj, data_path, value)
        obj.keyframe_insert(data_path=data_path, frame=frame)
    animation = obj.animation_data
    if animation and animation.action:
        for fcurve in animation.action.fcurves:
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


def build_scene(config):
    clear_scene()
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

    if scene_type in {"string_vibration", "bridge_cutaway", "wave_field"}:
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
        add_violin(wood, gold, silver, dark, frame_end)

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
    camera_data.dof.use_dof = True
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
    track.track_axis = "-Z"
    track.up_axis = "Y"

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
        scene.eevee.taa_render_samples = max(8, min(int(config.get("samples", 16)), 32))
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

    scene.view_settings.view_transform = "AgX" if "AgX" in scene.view_settings.bl_rna.properties["view_transform"].enum_items.keys() else "Standard"
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
    bpy.ops.render.render(animation=True)


def main():
    args = parse_arguments()
    config = json.loads(Path(args.config).read_text(encoding="utf-8"))
    config["output"] = args.output
    Path(args.output).parent.mkdir(parents=True, exist_ok=True)
    build_scene(config)
    print("BLENDER_FULL_FRAME_3D_RENDERED=" + str(Path(args.output).resolve()))


if __name__ == "__main__":
    main()
