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
    parser.add_argument("--bow-model", help="Optional separately downloaded, licensed bow GLB/glTF.")
    parser.add_argument("--strings-in-instrument", action="store_true",
                        help="Use strings visibly integrated into the real violin mesh.")
    parser.add_argument("--report", required=True)
    parser.add_argument("--width", type=int, default=720)
    parser.add_argument("--height", type=int, default=1280)
    parser.add_argument("--fps", type=int, default=25)
    parser.add_argument("--duration", type=float, default=24.0)
    parser.add_argument("--render-samples", type=int, default=96, help="Eevee temporal / Cycles sampling quality.")
    parser.add_argument("--sample-index", type=int, default=0,
                        help="Zero-based parallel render segment.")
    parser.add_argument("--sample-count", type=int, default=30,
                        help="Frames rendered by this worker.")
    parser.add_argument("--total-samples", type=int, default=600,
                        help="Total Blender-rendered timeline frames.")
    parser.add_argument("--frames-dir", required=True)
    parser.add_argument("--project-path", required=True)
    parser.add_argument("--proof-shot", action="store_true", help="Render one short proof shot, never a full storyboard.")
    parser.add_argument("--background-manifest", help="Story-specific image layers imported through Frame By Plane.")
    return parser.parse_args(raw)


def iter_action_fcurves(animated):
    """Yield animation curves on both Blender's legacy and layered Action APIs."""
    animation_data = getattr(animated, "animation_data", None)
    action = getattr(animation_data, "action", None) if animation_data else None
    if action is None:
        return
    # Blender 4.3 and earlier (and compatible legacy Actions).
    legacy_curves = getattr(action, "fcurves", None)
    if legacy_curves is not None:
        yield from legacy_curves
        return
    # Blender 4.4+ layered Actions; Blender 5.0 removed Action.fcurves.
    slot = getattr(animation_data, "action_slot", None)
    if slot is None:
        return
    for layer in action.layers:
        for strip in layer.strips:
            try:
                channelbag = strip.channelbag(slot)
            except (AttributeError, TypeError, RuntimeError):
                channelbag = None
            if channelbag is not None:
                yield from channelbag.fcurves


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


def add_camera_line(camera, name, points, material, *, bevel=0.006, distance=6.0):
    data = bpy.data.curves.new(name, "CURVE")
    data.dimensions = "3D"
    data.resolution_u = 12
    data.bevel_depth = bevel
    data.bevel_resolution = 3
    spline = data.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, coordinate in zip(spline.points, points):
        point.co = (*coordinate, 1.0)
    obj = bpy.data.objects.new(name, data)
    bpy.context.collection.objects.link(obj)
    obj.parent = camera
    obj.location = (0.0, 0.0, -distance)
    obj.data.materials.append(material)
    return obj


def add_camera_motion_graphics(camera, frame_end, gold, teal, cut_frames, *, proof=False):
    """Create a fixed title-safe progress graphic and animated shot-transition wipes."""
    distance = 6.0
    vertical_span = distance * float(camera.data.sensor_height) / max(1.0, float(camera.data.lens))
    horizontal_span = vertical_span * (9.0 / 16.0)
    y = (0.775 - 0.5) * vertical_span
    x_start = -horizontal_span * 0.82
    width = horizontal_span * 1.64
    progress = add_camera_line(
        camera,
        "Motion graphics | cinematic chapter progress",
        ((0.0, 0.0, 0.0), (width, 0.0, 0.0)),
        gold,
        bevel=0.004,
        distance=distance,
    )
    progress.location = (x_start, y, -distance)
    progress.scale = (0.001, 1.0, 1.0)
    progress.keyframe_insert(data_path="scale", frame=1)
    progress.scale = (1.0, 1.0, 1.0)
    progress.keyframe_insert(data_path="scale", frame=frame_end)
    for curve in iter_action_fcurves(progress):
            for point in curve.keyframe_points:
                point.interpolation = "LINEAR"

    sweeps = []
    for cut_index, cut_frame in enumerate(cut_frames):
        for layer, material in enumerate((teal, gold)):
            offset_y = (layer - 0.5) * vertical_span * 0.055
            sweep = add_camera_line(
                camera,
                f"Motion graphics | scene transition sweep {cut_index + 1}.{layer + 1}",
                ((0.0, -vertical_span * 0.58, 0.0), (0.0, vertical_span * 0.58, 0.0)),
                material,
                bevel=0.009 if layer == 0 else 0.006,
                distance=5.75,
            )
            sweep.location = (-horizontal_span * 1.55, offset_y, -5.75)
            sweep.keyframe_insert(data_path="location", frame=max(1, cut_frame - 3))
            sweep.location = (horizontal_span * 1.55, offset_y, -5.75)
            sweep.keyframe_insert(data_path="location", frame=min(frame_end, cut_frame + 3))
            for curve in iter_action_fcurves(sweep):
                    for point in curve.keyframe_points:
                        point.interpolation = "LINEAR"
            sweeps.append(sweep)
    return {"progress_bar": progress, "transition_sweeps": sweeps}


def import_and_normalise_model(
    model_path: Path,
    *,
    bow_model_path: Path | None = None,
    strings_in_instrument: bool = False,
):
    if not model_path.is_file() or model_path.suffix.casefold() not in {".glb", ".gltf"}:
        raise RuntimeError("A real downloaded .glb/.gltf model is required.")
    before = set(bpy.context.scene.objects)
    result = bpy.ops.import_scene.gltf(filepath=str(model_path))
    if "FINISHED" not in result:
        raise RuntimeError("Blender's glTF importer did not finish.")
    imported = [obj for obj in bpy.context.scene.objects if obj not in before]
    all_meshes = [obj for obj in imported if obj.type == "MESH"]
    if not all_meshes:
        raise RuntimeError("The downloaded GLB/glTF did not contain mesh geometry.")

    def object_name_chain(obj):
        names = []
        current = obj
        while current is not None:
            names.append(str(current.name).casefold())
            current = current.parent
        return " ".join(names)

    bow_tokens = ("bow", "bowstick", "bowhair", "horsehair", "bowfrog")
    source_bows = [
        obj for obj in all_meshes
        if any(token in object_name_chain(obj).replace(" ", "").replace("_", "") for token in bow_tokens)
    ]
    instrument_meshes = [obj for obj in all_meshes if obj not in source_bows]
    if not instrument_meshes:
        raise RuntimeError("The imported model contains a bow but no instrument body.")
    source_strings = [
        obj for obj in instrument_meshes
        if "string" in object_name_chain(obj).replace(" ", "")
    ]
    bow_imported = []
    if not source_bows and bow_model_path is not None:
        separate_bow_path = Path(bow_model_path)
        if not separate_bow_path.is_file() or separate_bow_path.suffix.casefold() not in {".glb", ".gltf"}:
            raise RuntimeError("A separately downloaded real bow .glb/.gltf model is required.")
        bow_before = set(bpy.context.scene.objects)
        bow_result = bpy.ops.import_scene.gltf(filepath=str(separate_bow_path))
        if "FINISHED" not in bow_result:
            raise RuntimeError("Blender's glTF importer did not finish for the separate bow model.")
        bow_imported = [obj for obj in bpy.context.scene.objects if obj not in bow_before]
        source_bows = [obj for obj in bow_imported if obj.type == "MESH"]
        if not source_bows:
            raise RuntimeError("The separately downloaded bow model contains no real mesh geometry.")
    if not source_bows:
        raise RuntimeError(
            "The selected violin and bow assets contain no importable bow geometry. "
            "A procedural bow substitute is not permitted."
        )
    if not source_strings and not strings_in_instrument:
        raise RuntimeError(
            "The selected violin has no separately named string mesh and the story plan "
            "does not verify strings integrated into the downloaded instrument geometry."
        )

    bpy.context.view_layer.update()
    corners = [
        obj.matrix_world @ Vector(corner)
        for obj in instrument_meshes
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

    # Convert the actual instrument to upright layout: width=X, thickness=Y, length=Z.
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
    root = bpy.data.objects.new("Actual imported instrument GLB — scene root", None)
    bpy.context.collection.objects.link(root)
    root.empty_display_type = "PLAIN_AXES"
    root.empty_display_size = 0.15
    root["source_bow_meshes_rigged"] = len(source_bows)
    root["source_string_meshes"] = len(source_strings)
    root["strings_embedded_in_instrument"] = bool(not source_strings and strings_in_instrument)
    root["bow_geometry_source"] = (
        "separate licensed imported bow GLB/glTF" if bow_imported
        else "integrated imported bow meshes from the violin GLB"
    )
    for obj in imported:
        if obj.parent not in imported_set:
            world = obj.matrix_world.copy()
            obj.parent = root
            obj.matrix_parent_inverse = Matrix.Identity(4)
            obj.matrix_basis = world
    root.matrix_world = transform
    bpy.context.view_layer.update()

    # Keep imported instrument and bow textures available in the saved Blender project.
    for image in bpy.data.images:
        if image.source == "FILE" and not image.packed_file:
            try:
                image.pack()
            except Exception:
                pass

    transformed = [
        obj.matrix_world @ Vector(corner)
        for obj in instrument_meshes
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
    return root, instrument_meshes, imported + bow_imported, bounds, source_bows, source_strings


def _principal_direction(points):
    """Estimate the bow's long axis from its imported mesh bounding corners."""
    if len(points) < 2:
        raise RuntimeError("The imported bow geometry has insufficient bounds.")
    centre = sum(points, Vector((0.0, 0.0, 0.0))) / float(len(points))
    covariance = Matrix((
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
    ))
    for point in points:
        delta = point - centre
        for row in range(3):
            for column in range(3):
                covariance[row][column] += delta[row] * delta[column]
    start_axis = max(range(3), key=lambda axis: covariance[axis][axis])
    direction = Vector(tuple(1.0 if axis == start_axis else 0.0 for axis in range(3)))
    for _ in range(48):
        updated = Vector(tuple(
            sum(covariance[row][column] * direction[column] for column in range(3))
            for row in range(3)
        ))
        if updated.length <= 1e-10:
            break
        updated.normalize()
        if min((updated - direction).length, (updated + direction).length) < 1e-8:
            direction = updated
            break
        direction = updated
    projections = [(point - centre).dot(direction) for point in points]
    span = max(projections) - min(projections)
    if span <= 1e-5:
        raise RuntimeError("The imported bow does not have a valid longitudinal axis.")
    return centre, direction.normalized(), span


def make_bow_animation(source_bow_meshes, front_y, bounds, frame_end):
    """Move the real downloaded bow parts under one Blender control rig."""
    if not source_bow_meshes:
        raise RuntimeError("A real imported bow mesh is required; no procedural bow is generated.")

    bpy.context.view_layer.update()
    bow_points = [
        obj.matrix_world @ Vector(corner)
        for obj in source_bow_meshes
        for corner in obj.bound_box
    ]
    centre, long_axis, current_length = _principal_direction(bow_points)
    instrument_length = float(bounds["max_z"] - bounds["min_z"])
    target_length = instrument_length * 1.05
    uniform_scale = target_length / current_length
    rotation = long_axis.rotation_difference(Vector((1.0, 0.0, 0.0)))
    bridge_z = float(bounds["min_z"]) * 0.12 + float(bounds["max_z"]) * 0.02
    target_centre = Vector((0.0, front_y - 0.035, bridge_z))

    # One root transforms the imported stick, hair, frog and tip together.
    # No second bow geometry is created and no source bow mesh remains visible outside this rig.
    bow_root = bpy.data.objects.new("BOW RIG — imported bow assembly control", None)
    bpy.context.collection.objects.link(bow_root)
    bow_root.empty_display_type = "PLAIN_AXES"
    bow_root.empty_display_size = 0.22
    bow_root.matrix_world = Matrix.Identity(4)
    for component in source_bow_meshes:
        world = component.matrix_world.copy()
        component.parent = bow_root
        component.matrix_parent_inverse = Matrix.Identity(4)
        component.matrix_basis = world

    delta = (
        Matrix.Translation(target_centre)
        @ rotation.to_matrix().to_4x4()
        @ Matrix.Scale(uniform_scale, 4)
        @ Matrix.Translation(-centre)
    )
    bow_root.matrix_world = delta
    base_location = bow_root.location.copy()
    bow_root["rig_type"] = "one control rig over imported Sketchfab bow mesh components"
    bow_root["visible_bow_rig_count"] = 1
    bow_root["source_bow_mesh_count"] = len(source_bow_meshes)
    bow_root["contact_plane"] = "imported bow aligned across the imported string mesh near the bridge"
    bow_root["source_meshes_preserved"] = True

    stroke = min(0.16, instrument_length * 0.045)
    poses = (
        (0.00, 0.0, 0.0),
        (0.25, stroke, 0.008),
        (0.50, -stroke, -0.008),
        (0.75, stroke * 0.82, 0.006),
        (1.00, 0.0, 0.0),
    )
    for fraction, x_shift, z_shift in poses:
        frame = max(1, min(frame_end, int(round(1 + (frame_end - 1) * fraction))))
        bow_root.location = base_location + Vector((x_shift, 0.0, z_shift))
        bow_root.keyframe_insert(data_path="location", frame=frame)
    for curve in iter_action_fcurves(bow_root):
            for point in curve.keyframe_points:
                point.interpolation = "BEZIER"
                point.handle_left_type = "AUTO"
                point.handle_right_type = "AUTO"
    bow_root["animation"] = "One imported bow slides in controlled reciprocal strokes across real violin strings."
    return bow_root, list(source_bow_meshes)


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

    if args.proof_shot:
        if not 4.0 <= float(args.duration) <= 5.0:
            raise RuntimeError("A proof shot must be between 4.0 and 5.0 seconds.")
        if args.sample_index != 0 or args.sample_count != args.total_samples or args.total_samples > 125:
            raise RuntimeError(
                "Proof mode is limited to one local segment of at most 125 frames; "
                "a full 600-frame render is forbidden."
            )
    root, meshes, imported, bounds, source_bows, source_strings = import_and_normalise_model(
        Path(args.model),
        bow_model_path=Path(args.bow_model) if args.bow_model else None,
        strings_in_instrument=bool(args.strings_in_instrument),
    )
    body_width = bounds["max_x"] - bounds["min_x"]
    front_y = bounds["front_y"]
    frame_end = int(round(args.duration * args.fps))
    scene = bpy.context.scene

    gold = set_material("Violin Prince antique gold", (0.77, 0.45, 0.17), metallic=0.65, roughness=0.24, emission=0.08)
    teal = set_material("Resonance teal light", (0.035, 0.52, 0.54), metallic=0.25, roughness=0.24, emission=0.48)
    white = set_material("Warm white type and bow horsehair", (0.90, 0.88, 0.80), metallic=0.05, roughness=0.28, emission=0.65)
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

    bow_root, bow_components = make_bow_animation(source_bows, front_y, bounds, frame_end)
    source_string_count = len(source_strings)
    strings = list(source_strings)
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
        for curve in iter_action_fcurves(animated):
                for point in curve.keyframe_points:
                    if int(round(point.co.x)) in cut_end_frames:
                        point.interpolation = "CONSTANT"
                    else:
                        point.interpolation = "BEZIER"
                        point.handle_left_type = "AUTO"
                        point.handle_right_type = "AUTO"

    frame_by_plane_report = None
    if args.background_manifest:
        from frame_by_plane_adapter import build_frame_by_plane_background
        frame_by_plane_report = build_frame_by_plane_background(
            args.background_manifest,
            camera,
            front_y,
            frame_end,
            expected_blender="5.2.4",
            expected_extension="8.0.1",
        )

    # Brand and story labels occupy a fixed top safe band; karaoke captions are
    # burned in separately in a reserved lower band.
    add_text_overlay(camera, "Violin Prince", 0.075, 0.945, 1, frame_end, gold, size=0.022, distance=6.0)
    if args.proof_shot:
        add_text_overlay(camera, "HOW A VIOLIN MAKES SOUND", 0.075, 0.835, 1, frame_end, white, size=0.038, distance=6.0)
        add_text_overlay(camera, "01 / 06", 0.925, 0.945, 1, frame_end, teal, size=0.018, distance=6.0, align="RIGHT")
    else:
        for shot_index, shot in enumerate(shot_specs, start=1):
            start_frame = at_fraction(shot["start"])
            end_frame = max(start_frame + 1, at_fraction(shot["end"]) - 1)
            add_text_overlay(
                camera, shot["label"], 0.075, 0.835,
                start_frame, end_frame, white, size=0.030, distance=6.0,
            )
            add_text_overlay(
                camera, f"{shot_index:02d} / 06", 0.925, 0.945,
                start_frame, end_frame, teal, size=0.018, distance=6.0, align="RIGHT",
            )
    motion_graphics = add_camera_motion_graphics(
        camera, frame_end, gold, teal, cut_end_frames, proof=bool(args.proof_shot)
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
        scene.eevee.taa_render_samples = max(32, min(int(args.render_samples), 256))
    if hasattr(scene, "eevee"):
        if hasattr(scene.eevee, "use_gtao"):
            scene.eevee.use_gtao = True
        if hasattr(scene.eevee, "gtao_distance"):
            scene.eevee.gtao_distance = 3.0
        if hasattr(scene.eevee, "gtao_factor"):
            scene.eevee.gtao_factor = 1.35
    for light_object in scene.objects:
        if light_object.type == "LIGHT":
            if hasattr(light_object.data, "use_shadow"):
                light_object.data.use_shadow = True
            if hasattr(light_object.data, "use_contact_shadow"):
                light_object.data.use_contact_shadow = True
    if render_engine == "CYCLES":
        scene.cycles.device = "CPU"
        scene.cycles.samples = max(48, min(int(args.render_samples), 256))
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
    try:
        scene.view_settings.look = "AgX - Medium High Contrast"
    except (TypeError, ValueError):
        pass
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
        "render_samples": max(32, min(int(args.render_samples), 256)),
        "actual_imported_mesh_count": len(meshes) + len(source_bows),
        "instrument_mesh_count": len(meshes),
        "animated_bow": True,
        "bow_rig_count": 1,
        "bow_rig_components": len(bow_components),
        "source_bow_meshes_rigged": len(source_bows),
        "visible_bow_mesh_count": len(source_bows),
        "source_string_meshes": source_string_count,
        "strings_embedded_in_instrument": bool(args.strings_in_instrument and source_string_count == 0),
        "string_representation": (
            "integrated into the imported violin geometry"
            if args.strings_in_instrument and source_string_count == 0
            else "separate imported violin mesh nodes"
        ),
        "bow_geometry_source": (
            "separate licensed imported bow GLB/glTF" if args.bow_model
            else "integrated imported bow meshes from the violin GLB"
        ),
        "animated_strings": 0,
        "resonance_rings": len(rings),
        "render_architecture": "hybrid_2.5D_plus_real_3D" if frame_by_plane_report else "real_3D_only",
        "frame_by_plane": frame_by_plane_report or {"enabled": False, "reason": "No background manifest supplied."},
        "motion_graphics": {
            "progress_bar": True,
            "transition_sweep_count": len(motion_graphics["transition_sweeps"]),
            "caption_layer_reserved": "ASS word-synchronised captions in lower safe band",
        },
        "3d_title_objects": 2 if args.proof_shot else 7,
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
