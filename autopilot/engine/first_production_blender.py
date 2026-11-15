"""Produce the first complete Violin Prince short in Blender.

All picture frames are rendered from Blender's imported GLB mesh, scene geometry,
materials, lights, camera path, animated bow, resonance graphics and 3D typography.
FFmpeg is used later only for the narration/music mix and caption finishing.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector


def parse_args():
    raw = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", required=True)
    parser.add_argument("--report", required=True)
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=1280)
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--duration", type=float, default=24.0)
    parser.add_argument("--sample-index", type=int, default=0,
                        help="Zero-based parallel render segment.")
    parser.add_argument("--sample-count", type=int, default=30,
                        help="Frames rendered by this worker.")
    parser.add_argument("--total-samples", type=int, default=600,
                        help="Total Blender-rendered timeline frames.")
    parser.add_argument("--frames-dir", required=True)
    parser.add_argument("--project-path", required=True)
    parser.add_argument("--proof-shot", action="store_true", help="Render one short proof shot, never a full storyboard.")
    return parser.parse_args(raw)


def set_material(name, colour, *, metallic=0.0, roughness=0.35, emission=0.0):
    mat = bpy.data.materials.new(name)
    mat.diffuse_color = (*colour, 1.0)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*colour, 1.0)
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
        emission_socket = bsdf.inputs.get("Emission Color") or bsdf.inputs.get("Emission")
        if emission_socket:
            emission_socket.default_value = (*colour, 1.0)
        strength = bsdf.inputs.get("Emission Strength")
        if strength:
            strength.default_value = emission
    return mat


def add_area_light(name, location, colour, power, size, target=(0.0, 0.0, 0.0)):
    bpy.ops.object.light_add(type="AREA", location=location)
    obj = bpy.context.object
    obj.name = name
    obj.data.energy = power
    obj.data.color = colour
    obj.data.shape = "DISK"
    obj.data.size = size
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat("-Z", "Y").to_euler()
    return obj


def add_curve(name, points, material, bevel=0.012):
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions = "3D"
    data.resolution_u = 24
    data.bevel_depth = bevel
    data.bevel_resolution = 4
    spline = data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, xyz in zip(spline.points, points):
        point.co = (*xyz, 1.0)
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj


def add_text_overlay(camera, text, x, y, start_frame, end_frame, material, *, size=0.035, distance=6.0, align="LEFT"):
    """Place typography in a resolution-independent, camera-locked safe area."""
    data = bpy.data.curves.new("2D-safe title typography", "FONT")
    data.body = text
    vertical_span = distance * float(camera.data.sensor_height) / max(1.0, float(camera.data.lens))
    horizontal_span = vertical_span * (720.0 / 1280.0)
    data.size = vertical_span * float(size)
    data.align_x = align
    data.align_y = "CENTER"
    data.extrude = 0.0008
    data.bevel_depth = 0.0002
    obj = bpy.data.objects.new("Camera-facing title — " + text[:32], data)
    bpy.context.collection.objects.link(obj)
    obj.parent = camera
    obj.location = ((float(x) - 0.5) * horizontal_span, (float(y) - 0.5) * vertical_span, -distance)
    obj.rotation_euler = (0.0, 0.0, 0.0)
    obj.data.materials.append(material)

    obj.scale = (0.001, 0.001, 0.001)
    obj.keyframe_insert(data_path="scale", frame=max(1, start_frame - 8))
    obj.scale = (1.0, 1.0, 1.0)
    obj.keyframe_insert(data_path="scale", frame=start_frame)
    obj.keyframe_insert(data_path="scale", frame=end_frame)
    obj.scale = (0.001, 0.001, 0.001)
    obj.keyframe_insert(data_path="scale", frame=min(10**6, end_frame + 8))
    obj["text_role"] = "camera-facing 3D graphic authored in Blender"
    return obj


def import_and_normalise_model(model_path: Path):
    if not model_path.is_file() or model_path.suffix.casefold() not in {".glb", ".gltf"}:
        raise RuntimeError("A real downloaded .glb/.gltf model is required.")
    before = set(bpy.context.scene.objects)
    result = bpy.ops.import_scene.gltf(filepath=str(model_path))
    if "FINISHED" not in result:
        raise RuntimeError("Blender's glTF importer did not finish.")
    imported = [obj for obj in bpy.context.scene.objects if obj not in before]
    meshes = [obj for obj in imported if obj.type == "MESH"]
    if not meshes:
        raise RuntimeError("The downloaded GLB/glTF did not contain mesh geometry.")

    def object_name_chain(obj):
        names = []
        current = obj
        while current is not None:
            names.append(str(current.name).casefold())
            current = current.parent
        return " ".join(names)

    bow_tokens = ("bow", "bowstick", "bowhair", "horsehair", "bowfrog")
    source_bows = [obj for obj in meshes if any(token in object_name_chain(obj).replace(" ", "") for token in bow_tokens)]
    for source_bow in source_bows:
        source_bow.hide_render = True
        source_bow.hide_set(True)
    instrument_meshes = [obj for obj in meshes if obj not in source_bows]
    if not instrument_meshes:
        raise RuntimeError("Every imported mesh was classified as a bow; no violin body remains.")
    source_strings = [obj for obj in instrument_meshes if "string" in object_name_chain(obj)]
    meshes = instrument_meshes

    bpy.context.view_layer.update()
    corners = [
        obj.matrix_world @ Vector(corner)
        for obj in meshes
        for corner in obj.bound_box
    ]
    minimum = Vector((
        min(p.x for p in corners), min(p.y for p in corners), min(p.z for p in corners)
    ))
    maximum = Vector((
        max(p.x for p in corners), max(p.y for p in corners), max(p.z for p in corners)
    ))
    centre = (minimum + maximum) * 0.5
    dimensions = maximum - minimum
    sizes = [float(dimensions.x), float(dimensions.y), float(dimensions.z)]
    length_axis = max(range(3), key=lambda axis: sizes[axis])
    depth_axis = min(range(3), key=lambda axis: sizes[axis])
    width_axis = next(axis for axis in range(3) if axis not in {length_axis, depth_axis})
    if min(sizes) <= 1e-6:
        raise RuntimeError("The imported GLB has invalid dimensions.")

    # Convert to upright violin layout: width=X, thickness=Y, instrument length=Z.
    permutation = [width_axis, depth_axis, length_axis]
    inversions = sum(
        1 for i in range(3) for j in range(i + 1, 3)
        if permutation[i] > permutation[j]
    )
    depth_sign = -1.0 if inversions % 2 else 1.0
    scale = 4.0 / sizes[length_axis]
    transform = Matrix.Identity(4)
    for row in range(3):
        for column in range(3):
            transform[row][column] = 0.0
    transform[0][width_axis] = scale
    transform[1][depth_axis] = depth_sign * scale
    transform[2][length_axis] = scale
    transform[0][3] = -centre[width_axis] * scale
    transform[1][3] = -centre[depth_axis] * depth_sign * scale
    transform[2][3] = -centre[length_axis] * scale

    imported_set = set(imported)
    root = bpy.data.objects.new("Actual imported violin GLB — scene root", None)
    bpy.context.collection.objects.link(root)
    root.empty_display_type = "PLAIN_AXES"
    root.empty_display_size = 0.15
    root["source_bow_meshes_hidden"] = len(source_bows)
    root["source_string_meshes"] = len(source_strings)
    for obj in imported:
        if obj.parent not in imported_set:
            world = obj.matrix_world.copy()
            obj.parent = root
            obj.matrix_parent_inverse = Matrix.Identity(4)
            obj.matrix_basis = world
    root.matrix_world = transform
    bpy.context.view_layer.update()

    # Keep the imported textures packed so the saved Blender project is portable.
    for image in bpy.data.images:
        if image.source == "FILE" and not image.packed_file:
            try:
                image.pack()
            except Exception:
                pass

    transformed = [
        obj.matrix_world @ Vector(corner)
        for obj in meshes
        for corner in obj.bound_box
    ]
    bounds = {
        "min_x": min(p.x for p in transformed),
        "max_x": max(p.x for p in transformed),
        "min_y": min(p.y for p in transformed),
        "max_y": max(p.y for p in transformed),
        "min_z": min(p.z for p in transformed),
        "max_z": max(p.z for p in transformed),
        "front_y": min(p.y for p in transformed),
    }
    return root, meshes, imported, bounds


def make_bow_animation(front_y, body_width, bounds, frame_end, gold, hair_mat):
    """Build one coherent bow assembly and animate it as a single rig."""
    half = max(0.72, min(1.32, body_width * 0.70))
    bridge_z = float(bounds["min_z"]) * 0.12 + float(bounds["max_z"]) * 0.02
    bow_root = bpy.data.objects.new("BOW RIG — single performance control", None)
    bpy.context.collection.objects.link(bow_root)
    bow_root.empty_display_type = "PLAIN_AXES"
    bow_root.empty_display_size = 0.22
    bow_root.location = (0.0, 0.0, 0.0)
    bow_root["rig_type"] = "single_parented_bow_assembly"
    bow_root["visible_bow_rig_count"] = 1
    bow_root["contact_plane"] = "parallel to bridge; horsehair aligned just above the imported string plane"

    stick = add_curve(
        "Bow rig | tapered maple stick",
        [
            (-half, front_y - 0.150, bridge_z + 0.055),
            (-half * 0.5, front_y - 0.142, bridge_z + 0.025),
            (0.0, front_y - 0.137, bridge_z),
            (half * 0.5, front_y - 0.142, bridge_z - 0.025),
            (half, front_y - 0.150, bridge_z - 0.055),
        ],
        gold, bevel=0.018,
    )
    hair = add_curve(
        "Bow rig | continuous horsehair ribbon",
        [
            (-half, front_y - 0.075, bridge_z + 0.015),
            (-half * 0.5, front_y - 0.071, bridge_z + 0.007),
            (0.0, front_y - 0.069, bridge_z),
            (half * 0.5, front_y - 0.071, bridge_z - 0.007),
            (half, front_y - 0.075, bridge_z - 0.015),
        ],
        hair_mat, bevel=0.0045,
    )

    # Frog and tip are children of the same rig control.
    bpy.ops.mesh.primitive_cube_add(size=1.0, location=(-half + 0.18, front_y - 0.116, bridge_z + 0.006))
    frog = bpy.context.object
    frog.name = "Bow rig | ebony frog"
    frog.dimensions = (0.24, 0.065, 0.075)
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    frog.data.materials.append(hair_mat)
    frog_bevel = frog.modifiers.new("Soft frog edges", "BEVEL")
    frog_bevel.width = 0.018
    frog_bevel.segments = 3

    bpy.ops.mesh.primitive_uv_sphere_add(
        segments=16, ring_count=8, radius=0.035,
        location=(half - 0.015, front_y - 0.150, bridge_z - 0.055),
    )
    tip = bpy.context.object
    tip.name = "Bow rig | rounded tip"
    tip.data.materials.append(gold)

    components = (stick, hair, frog, tip)
    for component in components:
        world = component.matrix_world.copy()
        component.parent = bow_root
        component.matrix_parent_inverse = Matrix.Identity(4)
        component.matrix_basis = world

    poses = (
        (0.00, 0.0, 0.0),
        (0.25, 0.115, 0.012),
        (0.50, -0.115, -0.008),
        (0.75, 0.105, 0.010),
        (1.00, 0.0, 0.0),
    )
    for fraction, x_shift, z_shift in poses:
        frame = max(1, min(frame_end, int(round(1 + (frame_end - 1) * fraction))))
        bow_root.location = (x_shift, 0.0, z_shift)
        bow_root.keyframe_insert(data_path="location", frame=frame)
    if bow_root.animation_data and bow_root.animation_data.action:
        for curve in bow_root.animation_data.action.fcurves:
            for point in curve.keyframe_points:
                point.interpolation = "BEZIER"
                point.handle_left_type = "AUTO"
                point.handle_right_type = "AUTO"
    bow_root["animation"] = "One parented bow rig performs short reciprocal strokes across the strings."
    return bow_root, components


def make_vibrating_strings(front_y, body_width, bounds, frame_end, silver, source_string_count=0):
    # Do not overlay a second string set when the imported model already has strings.
    if int(source_string_count) > 0:
        return []
    # Source mesh remains untouched; these four thin metal lines clarify the
    # string-to-bridge path in close camera shots.
    half = min(body_width * 0.22, 0.33)
    z_top = bounds["max_z"] * 0.67
    z_bottom = bounds["min_z"] * 0.63
    output = []
    for index in range(4):
        x = (index - 1.5) * (half * 2.0 / 3.0)
        points = [
            (x, front_y - 0.085, z_bottom),
            (x, front_y - 0.090, z_bottom * 0.25),
            (x, front_y - 0.095, 0.0),
            (x, front_y - 0.090, z_top * 0.62),
            (x, front_y - 0.080, z_top),
        ]
        obj = add_curve(f"Animated explanatory string {index + 1}", points, silver, bevel=0.0045)
        obj["animation"] = "subtle string oscillation layered in the Blender scene"
        # Slight global sway is intentionally restrained.
        for frame, strength in ((1, 0.0), (120, 0.012), (240, -0.012), (360, 0.009), (frame_end, 0.0)):
            obj.location.y = strength
            obj.keyframe_insert(data_path="location", frame=frame)
        output.append(obj)
    return output


def make_resonance_rings(front_y, frame_end, teal):
    rings = []
    for index, radius in enumerate((0.62, 0.90, 1.18)):
        bpy.ops.mesh.primitive_torus_add(
            major_segments=72,
            minor_segments=12,
            major_radius=radius,
            minor_radius=0.008,
            location=(0.0, front_y - 0.45, -0.20 + index * 0.10),
            rotation=(math.pi / 2.0, 0.0, 0.0),
        )
        ring = bpy.context.object
        ring.name = f"Expanding acoustic resonance ring {index + 1}"
        ring.data.materials.append(teal)
        for fraction, factor in (
            (0.00, (0.01, 0.01, 0.01)),
            (0.35, (0.70, 0.70, 0.70)),
            (0.50, (1.00, 1.00, 1.00)),
            (0.65, (1.28, 1.28, 1.28)),
            (0.82, (1.55, 1.55, 1.55)),
            (1.00, (1.80, 1.80, 1.80)),
        ):
            frame = max(1, min(frame_end, int(round(1 + (frame_end - 1) * fraction))))
            ring.scale = factor
            ring.keyframe_insert(data_path="scale", frame=frame)
        rings.append(ring)
    return rings


def build_scene(args):
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for datablocks in (bpy.data.meshes, bpy.data.curves, bpy.data.materials, bpy.data.cameras, bpy.data.lights):
        for item in list(datablocks):
            if item.users == 0:
                datablocks.remove(item)

    root, meshes, imported, bounds = import_and_normalise_model(Path(args.model))
    body_width = bounds["max_x"] - bounds["min_x"]
    front_y = bounds["front_y"]
    frame_end = int(round(args.duration * args.fps))
    scene = bpy.context.scene

    gold = set_material("Violin Prince antique gold", (0.77, 0.45, 0.17), metallic=0.65, roughness=0.24, emission=0.08)
    teal = set_material("Resonance teal light", (0.035, 0.52, 0.54), metallic=0.25, roughness=0.24, emission=0.48)
    white = set_material("Warm white type", (0.90, 0.88, 0.80), metallic=0.05, roughness=0.28, emission=0.65)
    silver = set_material("Fine string silver", (0.50, 0.64, 0.73), metallic=0.88, roughness=0.18, emission=0.03)
    floor_mat = set_material("Midnight navy stage", (0.008, 0.018, 0.035), metallic=0.28, roughness=0.32)

    # Studio floor, circular plinth and subtle atmospheric environment.
    bpy.ops.mesh.primitive_plane_add(size=200.0, location=(0.0, 0.0, bounds["min_z"] - 0.58))
    floor = bpy.context.object
    floor.name = "Infinite midnight studio floor"
    floor.data.materials.append(floor_mat)

    bpy.ops.mesh.primitive_cylinder_add(vertices=128, radius=max(body_width * 0.64, 1.0), depth=0.10,
                                        location=(0.0, 0.15, bounds["min_z"] - 0.53))
    plinth = bpy.context.object
    plinth.name = "Low circular display plinth"
    plinth.data.materials.append(floor_mat)
    bevel = plinth.modifiers.new("Soft plinth rim", "BEVEL")
    bevel.width = 0.045
    bevel.segments = 3
    plinth.modifiers.new("Plinth weighted normals", "WEIGHTED_NORMAL")

    # Dust is made of real small 3D spheres with slow, unobtrusive movement.
    dust_mat = set_material("Gold dust emission", (0.72, 0.39, 0.13), metallic=0.0, roughness=0.3, emission=0.7)
    for index in range(26):
        x = math.sin(index * 2.37) * 2.45
        z = -1.9 + (index % 9) * 0.47
        y = 0.55 + (index % 5) * 0.22
        radius = 0.012 + (index % 4) * 0.006
        bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, radius=radius, location=(x, y, z))
        particle = bpy.context.object
        particle.name = f"Atmospheric gold particle {index + 1}"
        particle.data.materials.append(dust_mat)
        for frame, dz, dx in ((1, 0.0, 0.0), (frame_end, 0.18 + (index % 3) * 0.08, 0.10 * math.sin(index))):
            particle.location = (x + dx, y, z + dz)
            particle.keyframe_insert(data_path="location", frame=frame)

    add_area_light("Large warm key light", (4.5, -5.0, 5.5), (1.0, 0.70, 0.44), 1050, 5.5)
    add_area_light("Cool teal fill light", (-4.5, -3.0, 0.4), (0.30, 0.70, 0.90), 650, 4.5)
    add_area_light("Amber rim light", (0.0, 2.5, 4.0), (1.0, 0.38, 0.12), 950, 3.0)
    add_area_light("Soft front reflection", (0.0, -6.0, 0.0), (0.72, 0.82, 1.0), 240, 4.0)

    world = bpy.data.worlds.new("Midnight blue world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs["Color"].default_value = (0.004, 0.010, 0.024, 1.0)
    world.node_tree.nodes["Background"].inputs["Strength"].default_value = 0.20
    scene.world = world

    bow_root, bow_components = make_bow_animation(front_y, body_width, bounds, frame_end, gold, white)
    source_string_count = int(root.get("source_string_meshes", 0))
    strings = make_vibrating_strings(front_y, body_width, bounds, frame_end, silver, source_string_count)
    rings = make_resonance_rings(front_y, frame_end, teal)

    # Animated cinematic camera: reveal, bridge macro, f-hole sweep, scroll detail, hero return.
    camera_data = bpy.data.cameras.new("Violin Prince cinematic camera")
    camera = bpy.data.objects.new("Violin Prince cinematic camera", camera_data)
    bpy.context.collection.objects.link(camera)
    camera_data.lens = 52.0
    camera_data.sensor_fit = "VERTICAL"
    camera_data.sensor_height = 24.0
    camera_data.dof.use_dof = True
    camera_data.dof.aperture_fstop = 5.6
    scene.camera = camera

    focus = bpy.data.objects.new("Camera focus target", None)
    bpy.context.collection.objects.link(focus)
    focus.empty_display_type = "SPHERE"
    focus.empty_display_size = 0.05
    camera_data.dof.focus_object = focus
    track = camera.constraints.new(type="TRACK_TO")
    track.target = focus
    track.track_axis = "TRACK_NEGATIVE_Z"
    track.up_axis = "UP_Y"

    # Six authored scenes with distinct framing and hard cuts between shots.
    shot_specs = [
        {"label": "THE HERO REVEAL", "start": 0.000, "end": 0.145,
         "start_camera": (2.4, front_y - 10.8, 0.75), "end_camera": (0.9, front_y - 9.8, 0.55),
         "start_target": (0.0, front_y, 0.15), "end_target": (0.0, front_y, 0.18),
         "start_lens": 49.0, "end_lens": 53.0},
        {"label": "BOW MEETS THE STRINGS", "start": 0.145, "end": 0.3125,
         "start_camera": (1.4, front_y - 5.2, 0.20), "end_camera": (-0.4, front_y - 4.7, -0.12),
         "start_target": (0.0, front_y, -0.25), "end_target": (0.0, front_y, -0.30),
         "start_lens": 76.0, "end_lens": 84.0},
        {"label": "THE BRIDGE TRANSFERS VIBRATION", "start": 0.3125, "end": 0.500,
         "start_camera": (-1.6, front_y - 4.8, -0.28), "end_camera": (0.9, front_y - 4.5, -0.35),
         "start_target": (0.0, front_y, -0.42), "end_target": (0.0, front_y, -0.42),
         "start_lens": 88.0, "end_lens": 92.0},
        {"label": "THE BODY RESONATES", "start": 0.500, "end": 0.7083,
         "start_camera": (-1.4, front_y - 5.0, -0.55), "end_camera": (1.3, front_y - 4.8, -0.42),
         "start_target": (0.0, front_y, -0.55), "end_target": (0.0, front_y, -0.55),
         "start_lens": 78.0, "end_lens": 86.0},
        {"label": "THE SCROLL AND TUNING PEGS", "start": 0.7083, "end": 0.8542,
         "start_camera": (1.15, front_y - 4.8, 2.55), "end_camera": (-0.25, front_y - 4.3, 2.72),
         "start_target": (0.0, front_y, 1.55), "end_target": (0.0, front_y, 1.62),
         "start_lens": 82.0, "end_lens": 88.0},
        {"label": "THE FINAL HERO SHOT", "start": 0.8542, "end": 1.000,
         "start_camera": (-2.2, front_y - 10.6, 0.70), "end_camera": (0.0, front_y - 10.0, 0.60),
         "start_target": (0.0, front_y, 0.12), "end_target": (0.0, front_y, 0.12),
         "start_lens": 50.0, "end_lens": 54.0},
    ]
    def at_fraction(fraction):
        return max(1, min(frame_end, int(round(1 + (frame_end - 1) * fraction))))

    camera_moves = []
    cut_end_frames = []
    active_shots = [shot_specs[0]] if args.proof_shot else shot_specs
    for shot in active_shots:
        start_frame = at_fraction(0.0 if args.proof_shot else shot["start"])
        end_frame = frame_end if args.proof_shot else max(start_frame + 1, at_fraction(shot["end"]) - 1)
        camera_moves.extend((
            (start_frame, shot["start_camera"], shot["start_target"], shot["start_lens"]),
            (end_frame, shot["end_camera"], shot["end_target"], shot["end_lens"]),
        ))
        if not args.proof_shot and shot is not shot_specs[-1]:
            cut_end_frames.append(end_frame)

    for frame, position, target, lens in camera_moves:
        camera.location = position
        camera.keyframe_insert(data_path="location", frame=frame)
        focus.location = target
        focus.keyframe_insert(data_path="location", frame=frame)
        camera.data.lens = lens
        camera.data.keyframe_insert(data_path="lens", frame=frame)
    for animated in (camera, focus, camera.data):
        action = animated.animation_data.action if animated.animation_data else None
        if action:
            for curve in action.fcurves:
                for point in curve.keyframe_points:
                    if int(round(point.co.x)) in cut_end_frames:
                        point.interpolation = "CONSTANT"
                    else:
                        point.interpolation = "BEZIER"
                        point.handle_left_type = "AUTO"
                        point.handle_right_type = "AUTO"

    # Brand and story labels occupy a fixed top safe band; karaoke captions are
    # burned in separately in a reserved lower band.
    add_text_overlay(camera, "Violin Prince", 0.075, 0.945, 1, frame_end, gold, size=0.022, distance=6.0)
    if args.proof_shot:
        add_text_overlay(camera, "HOW A VIOLIN MAKES SOUND", 0.075, 0.835, 1, frame_end, white, size=0.038, distance=6.0)
    else:
        for shot in shot_specs:
            start_frame = at_fraction(shot["start"])
            end_frame = max(start_frame + 1, at_fraction(shot["end"]) - 1)
            add_text_overlay(
                camera, shot["label"], 0.075, 0.835,
                start_frame, end_frame, white, size=0.030, distance=6.0,
            )

    # Select the Eevee identifier exposed by this installed Blender build.
    # Blender 5.0 uses BLENDER_EEVEE; earlier 4.x builds used BLENDER_EEVEE_NEXT.
    engine_items = scene.render.bl_rna.properties["engine"].enum_items
    supported_engines = {item.identifier for item in engine_items}
    if "BLENDER_EEVEE" in supported_engines:
        render_engine = "BLENDER_EEVEE"
    elif "BLENDER_EEVEE_NEXT" in supported_engines:
        render_engine = "BLENDER_EEVEE_NEXT"
    elif "CYCLES" in supported_engines:
        render_engine = "CYCLES"
    else:
        raise RuntimeError("This Blender build exposes no supported Eevee or Cycles render engine.")
    scene.render.engine = render_engine
    if hasattr(scene, "eevee") and hasattr(scene.eevee, "taa_render_samples"):
        scene.eevee.taa_render_samples = 64
    if render_engine == "CYCLES":
        scene.cycles.device = "CPU"
        scene.cycles.samples = 48
    scene.render.threads_mode = "FIXED"
    scene.render.threads = max(1, min(os.cpu_count() or 2, 4))
    scene.render.resolution_x = args.width
    scene.render.resolution_y = args.height
    scene.render.resolution_percentage = 100
    scene.render.fps = args.fps
    scene.frame_start = 1
    scene.frame_end = frame_end
    scene.frame_step = 1
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX"
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.use_file_extension = True
    scene.render.image_settings.compression = 20

    frames_dir = Path(args.frames_dir).expanduser().resolve()
    frames_dir.mkdir(parents=True, exist_ok=True)
    report_path = Path(args.report).expanduser().resolve()
    report_path.parent.mkdir(parents=True, exist_ok=True)
    project_path = Path(args.project_path).expanduser().resolve()
    project_path.parent.mkdir(parents=True, exist_ok=True)

    if args.total_samples < 2 or args.sample_count < 1:
        raise RuntimeError("At least two total samples and one sample per segment are required.")
    if args.sample_index < 0:
        raise RuntimeError("The render segment index cannot be negative.")
    start_index = args.sample_index * args.sample_count
    end_index = min(start_index + args.sample_count, args.total_samples)
    if start_index >= args.total_samples:
        raise RuntimeError("This render segment begins outside the total sample range.")

    # Pack textures and save one reusable editable project before the frame workers render.
    for image in bpy.data.images:
        if image.source == "FILE" and not image.packed_file:
            try:
                image.pack()
            except Exception:
                pass
    if args.sample_index == 0:
        bpy.ops.wm.save_as_mainfile(filepath=str(project_path))

    sample_records = []
    for global_index in range(start_index, end_index):
        # At 600 samples for this 600-frame timeline, each native frame is rendered exactly once.
        timeline_frame = 1 + round(
            global_index * (frame_end - 1) / (args.total_samples - 1)
        )
        scene.frame_set(timeline_frame)
        output_frame = frames_dir / f"frame_{global_index:04d}.png"
        scene.render.filepath = str(output_frame)
        bpy.ops.render.render(write_still=True)
        if not output_frame.is_file() or output_frame.stat().st_size < 1024:
            raise RuntimeError("Blender did not create the expected image: " + str(output_frame))
        sample_records.append({
            "sample_index": global_index,
            "timeline_frame": timeline_frame,
            "file": str(output_frame),
            "bytes": output_frame.stat().st_size,
        })
        print(
            "FIRST_PRODUCTION_FRAME "
            + str(global_index + 1) + "/" + str(args.total_samples)
            + " timeline=" + str(timeline_frame)
        )

    report = {
        "status": "blender_frame_samples_completed",
        "renderer": "Blender " + render_engine,
        "model_source": str(Path(args.model).resolve()),
        "model_type": "imported GLB mesh; not a procedural substitute",
        "resolution": [args.width, args.height],
        "target_fps": args.fps,
        "duration_seconds": args.duration,
        "timeline_frame_count": frame_end,
        "sample_count": len(sample_records),
        "total_samples": args.total_samples,
        "sample_index": args.sample_index,
        "sample_start": start_index,
        "sample_end_exclusive": end_index,
        "camera_moves": len(camera_moves),
        "storyboard_scenes": 1 if args.proof_shot else len(shot_specs),
        "proof_shot_only": bool(args.proof_shot),
        "native_resolution": [args.width, args.height],
        "render_samples": 64 if render_engine != "CYCLES" else 48,
        "actual_imported_mesh_count": len(meshes),
        "animated_bow": True,
        "bow_rig_count": 1,
        "bow_rig_components": len(bow_components),
        "source_bow_meshes_hidden": int(root.get("source_bow_meshes_hidden", 0)),
        "source_string_meshes": source_string_count,
        "animated_strings": len(strings),
        "resonance_rings": len(rings),
        "3d_title_objects": 5,
        "blend_project": str(project_path) if args.sample_index == 0 else None,
        "samples": sample_records,
    }
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("BLENDER_FIRST_PRODUCTION_REPORT=" + json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    try:
        build_scene(parse_args())
    except Exception as exc:
        print("FIRST_PRODUCTION_BLENDER_FAILED: " + str(exc)[:1800], file=sys.stderr)
        sys.exit(1)
