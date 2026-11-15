"""Safe Frame By Plane integration for Violin Prince's headless Blender renderer."""
from __future__ import annotations

import importlib
import inspect
import json
import math
import re
import tomllib
from pathlib import Path

LOCKED_BLENDER = "5.2.4"
LOCKED_FRAME_BY_PLANE = "8.0.1"
OFFICIAL_REPOSITORY_MODULE = "violin_prince_official"
OFFICIAL_REPOSITORY_URL = "https://extensions.blender.org/api/v1/extensions/"
SUPPORTED_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".exr", ".webp"}
MAX_LAYER_FILES = 500
MAX_LAYER_BYTES = 80 * 1024 * 1024


class FrameByPlaneError(RuntimeError):
    """Raised when the installed extension or layer bundle is unsafe or incompatible."""


def _safe_name(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_-]+", "-", str(value or "").strip()).strip("-")
    if not cleaned:
        raise FrameByPlaneError("Every Frame By Plane layer needs a non-empty name.")
    return cleaned[:64]


def load_background_manifest(manifest_path: str | Path) -> dict:
    """Load and strictly validate a story-specific layer manifest and its media."""
    path = Path(manifest_path).expanduser().resolve()
    if not path.is_file():
        raise FrameByPlaneError(f"Background manifest does not exist: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise FrameByPlaneError(f"Could not read background manifest: {exc}") from exc
    if not isinstance(data, dict) or data.get("schema_version") != 1:
        raise FrameByPlaneError("Unsupported Frame By Plane background manifest schema.")
    layers = data.get("layers")
    if not isinstance(layers, list) or not 1 <= len(layers) <= 12:
        raise FrameByPlaneError("A background bundle must contain between 1 and 12 layers.")

    root = path.parent.resolve()
    validated, names = [], set()
    for index, raw in enumerate(layers):
        if not isinstance(raw, dict):
            raise FrameByPlaneError(f"Layer {index} is not an object.")
        name = _safe_name(raw.get("name", ""))
        if name.casefold() in names:
            raise FrameByPlaneError(f"Duplicate Frame By Plane layer name: {name}")
        names.add(name.casefold())
        files = raw.get("files")
        if files is None:
            files = [raw.get("file")]
        if not isinstance(files, list) or not 1 <= len(files) <= MAX_LAYER_FILES:
            raise FrameByPlaneError(f"Layer {name} has an invalid file/sequence list.")

        resolved_files, total_bytes = [], 0
        for relative in files:
            if not isinstance(relative, str) or not relative.strip():
                raise FrameByPlaneError(f"Layer {name} contains an empty media path.")
            media = (root / relative).resolve()
            try:
                media.relative_to(root)
            except ValueError as exc:
                raise FrameByPlaneError(f"Layer {name} media path escapes its bundle.") from exc
            if not media.is_file() or media.suffix.lower() not in SUPPORTED_IMAGE_SUFFIXES:
                raise FrameByPlaneError(f"Layer {name} media is missing or unsupported: {relative}")
            total_bytes += media.stat().st_size
            if total_bytes > MAX_LAYER_BYTES:
                raise FrameByPlaneError(f"Layer {name} exceeds the media size safety limit.")
            resolved_files.append(media)

        def number(key, default):
            try:
                value = float(raw.get(key, default))
            except (TypeError, ValueError) as exc:
                raise FrameByPlaneError(f"Layer {name} has an invalid {key}.") from exc
            if not math.isfinite(value):
                raise FrameByPlaneError(f"Layer {name} has a non-finite {key}.")
            return value

        depth = number("distance", 2.0)
        cover = number("cover_scale", 1.25)
        parallax_x = number("parallax_x", 0.0)
        parallax_z = number("parallax_z", 0.0)
        center_z = number("center_z", 0.0)
        if not 0.25 <= depth <= 30.0:
            raise FrameByPlaneError(f"Layer {name} distance must be between 0.25 and 30.")
        if not 0.5 <= cover <= 3.0:
            raise FrameByPlaneError(f"Layer {name} cover_scale must be between 0.5 and 3.")
        if abs(parallax_x) > 1.0 or abs(parallax_z) > 1.0:
            raise FrameByPlaneError(f"Layer {name} parallax offsets must be within ±1 Blender unit.")

        validated.append({
            "name": name, "role": str(raw.get("role", "background")),
            "files": resolved_files, "directory": resolved_files[0].parent,
            "file_names": [item.name for item in resolved_files],
            "distance": depth, "cover_scale": cover,
            "parallax_x": parallax_x, "parallax_z": parallax_z,
            "center_z": center_z, "bytes": total_bytes,
        })

    return {
        "schema_version": 1, "style": str(data.get("style", "custom")),
        "resolution": data.get("resolution", [1080, 1920]),
        "manifest_path": str(path), "layers": validated,
    }


def verify_frame_by_plane(
    *,
    expected_blender: str = LOCKED_BLENDER,
    expected_extension: str = LOCKED_FRAME_BY_PLANE,
    bpy_module=None,
):
    """Fail closed unless the pinned Blender LTS and official FBP extension are enabled."""
    if bpy_module is None:
        try:
            import bpy as bpy_module
        except ImportError as exc:
            raise FrameByPlaneError("This check must run inside Blender's Python runtime.") from exc

    try:
        expected_version = tuple(int(part) for part in expected_blender.split("."))
        actual_version = tuple(int(part) for part in bpy_module.app.version[:3])
    except (AttributeError, TypeError, ValueError) as exc:
        raise FrameByPlaneError("Could not read Blender's numeric version tuple.") from exc
    if actual_version != expected_version:
        raise FrameByPlaneError(
            f"Violin Prince pins Blender {expected_blender}; found "
            + ".".join(str(part) for part in actual_version)
        )
    actual_blender = ".".join(str(part) for part in actual_version)

    # Blender's extension CLI installs the package into its official
    # blender_org repository. Resolve the actual loaded add-on module rather
    # than assuming a custom repository module or cache directory.
    enabled_modules = [
        str(getattr(item, "module", ""))
        for item in bpy_module.context.preferences.addons
        if str(getattr(item, "module", "")).startswith("bl_ext.")
        and str(getattr(item, "module", "")).endswith(".frame_by_plane")
    ]
    repos = getattr(bpy_module.context.preferences.extensions, "repos", ())
    matching = []
    for module_name in enabled_modules:
        parts = module_name.split(".")
        if len(parts) != 3:
            continue
        repo_module = parts[1]
        for repo in repos:
            if str(getattr(repo, "module", "")) != repo_module:
                continue
            remote_url = str(getattr(repo, "remote_url", "") or "").rstrip("/")
            if remote_url == OFFICIAL_REPOSITORY_URL.rstrip("/"):
                matching.append((module_name, repo))
    if len(matching) != 1:
        raise FrameByPlaneError(
            "Expected exactly one enabled Frame By Plane add-on from Blender's official "
            f"extensions.blender.org repository; found {len(matching)}."
        )
    module_name, repo = matching[0]

    try:
        extension_module = importlib.import_module(module_name)
        builder = importlib.import_module(module_name + ".builder")
    except Exception as exc:
        raise FrameByPlaneError(f"Could not import installed Frame By Plane modules: {exc}") from exc

    module_file = getattr(extension_module, "__file__", None)
    if not module_file:
        raise FrameByPlaneError("Frame By Plane's installed module did not expose a filesystem location.")
    package_dir = Path(module_file).resolve().parent
    manifest_path = package_dir / "blender_manifest.toml"
    if not manifest_path.is_file():
        raise FrameByPlaneError(
            "Frame By Plane is imported but its package manifest is missing: " + str(manifest_path)
        )
    try:
        manifest = tomllib.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        raise FrameByPlaneError(f"Could not read installed Frame By Plane manifest: {exc}") from exc

    extension_id = str(manifest.get("id", ""))
    version = str(manifest.get("version", ""))
    raw_license = manifest.get("license", [])
    license_id = " ".join(raw_license) if isinstance(raw_license, list) else str(raw_license)
    if extension_id != "frame_by_plane" or version != expected_extension:
        raise FrameByPlaneError(
            f"Expected Frame By Plane {expected_extension}; found "
            f"{extension_id or 'unknown'} {version or 'unknown'}."
        )
    if "GPL-3.0" not in license_id.upper():
        raise FrameByPlaneError(f"Unexpected Frame By Plane licence identifier: {license_id!r}")

    build_rig = getattr(builder, "build_fbp_rig", None)
    place_layers = getattr(builder, "fbp_layer_placement", None)
    if not callable(build_rig):
        available_builder = sorted(
            name for name in dir(builder)
            if name.startswith(("build_", "fbp_", "camera_"))
        )
        raise FrameByPlaneError(
            "Frame By Plane does not expose its native image-layer builder: "
            f"module={getattr(builder, '__file__', '<unknown>')}; "
            f"available={available_builder[:100]}"
        )
    required = {
        "context", "rig_name", "directory", "files_list", "location",
        "target_collection", "follow_collection_color",
    }
    try:
        builder_parameters = inspect.signature(build_rig).parameters
        available = set(builder_parameters)
    except (TypeError, ValueError) as exc:
        raise FrameByPlaneError("Could not inspect the Frame By Plane native layer builder.") from exc
    if not required.issubset(available):
        raise FrameByPlaneError(
            f"Frame By Plane builder API changed; missing {sorted(required - available)}."
        )

    return {
        "blender_version": actual_blender,
        "blender_version_string": str(getattr(bpy_module.app, "version_string", actual_blender)),
        "extension_id": extension_id,
        "extension_version": version,
        "extension_license": license_id,
        "repository_module": str(repo.module),
        "repository_url": str(repo.remote_url),
        "package_path": str(package_dir.resolve()),
        "module_name": module_name,
        "builder": build_rig,
        # Frame By Plane 8.0.1 has the native layer builder but does not expose
        # the later camera-placement helper. The adapter supplies an equivalent
        # camera-space placement fallback for that pinned release.
        "placement_factory": place_layers if callable(place_layers) else None,
        "placement_source": "frame_by_plane" if callable(place_layers) else "violin_prince_camera_adapter",
        "builder_parameters": sorted(available),
        "module": extension_module,
    }


class _AdapterCameraPlacement:
    """Camera-aware placement compatible with Frame By Plane 8.0.1.

    Frame By Plane 8.0.1 exposes build_fbp_rig but not the later
    fbp_layer_placement helper. This mirrors the extension's camera-frame
    placement contract using Blender's public camera/mathutils APIs.
    """

    def __init__(self, scene, camera, anchor, vector_type):
        self.scene = scene
        self.anchor = vector_type(anchor)
        self.camera = None
        self.rotation = None
        self.forward = None
        self.origin = None
        self.uses_camera = False

        if camera is None or getattr(camera, "type", "") != "CAMERA":
            return

        try:
            cam_loc, cam_rot, _cam_scale = camera.matrix_world.decompose()
            cam_rot.normalize()
            forward = cam_rot @ vector_type((0.0, 0.0, -1.0))
            if forward.length < 1e-8:
                return
            forward.normalize()

            camera_data = camera.data
            clip_start = max(1e-4, float(getattr(camera_data, "clip_start", 0.1) or 0.1))
            clip_end = max(
                clip_start * 2.0,
                float(getattr(camera_data, "clip_end", 1000.0) or 1000.0),
            )
            depth = float((self.anchor - cam_loc).dot(forward))
            if not (clip_start * 1.5 < depth < clip_end * 0.95):
                depth = min(max(10.0, clip_start * 2.0), clip_end * 0.5)

            frame = camera_data.view_frame(scene=scene)
            center_x = sum(point.x for point in frame) / 4.0
            center_y = sum(point.y for point in frame) / 4.0
            if getattr(camera_data, "type", "PERSP") == "ORTHO":
                local = vector_type((center_x, center_y, -depth))
            else:
                frame_z = abs(float(frame[0].z))
                if frame_z < 1e-8:
                    frame_z = 1.0
                local = vector_type((center_x, center_y, -frame_z)) * (depth / frame_z)

            self.camera = camera
            self.rotation = cam_rot
            self.forward = forward
            self.origin = cam_loc + cam_rot @ local
            self.uses_camera = True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError, ZeroDivisionError):
            self.uses_camera = False

    def location(self, offset=0.0):
        if not self.uses_camera:
            raise FrameByPlaneError("The active camera could not be resolved for 2.5D layer placement.")
        return self.origin + self.forward * float(offset or 0.0)

    def place(self, rig, offset=0.0):
        if not rig or not self.uses_camera:
            return False
        try:
            rig.location = self.location(offset)
            mode = str(getattr(rig, "rotation_mode", "XYZ") or "XYZ")
            if mode == "QUATERNION":
                rig.rotation_quaternion = self.rotation.copy()
            elif mode == "AXIS_ANGLE":
                axis, angle = self.rotation.to_axis_angle()
                rig.rotation_axis_angle = (angle, axis.x, axis.y, axis.z)
            else:
                rig.rotation_euler = self.rotation.to_euler(mode)
            try:
                rig.fbp_is_vertical = abs(self.forward.z) < (0.5 ** 0.5)
            except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
                pass
            return True
        except (AttributeError, ReferenceError, RuntimeError, TypeError, ValueError):
            return False


def build_frame_by_plane_background(
    manifest_path: str | Path, camera, instrument_front_y: float, frame_end: int,
    *, expected_blender: str = LOCKED_BLENDER,
    expected_extension: str = LOCKED_FRAME_BY_PLANE, bpy_module=None,
):
    """Create camera-facing, depth-separated Frame By Plane layers behind the 3D hero."""
    if bpy_module is None:
        import bpy as bpy_module
    from mathutils import Vector

    bundle = load_background_manifest(manifest_path)
    runtime = verify_frame_by_plane(
        expected_blender=expected_blender, expected_extension=expected_extension,
        bpy_module=bpy_module,
    )
    scene = bpy_module.context.scene
    collection = bpy_module.data.collections.new("VP / Frame By Plane / Cinematic Background")
    scene.collection.children.link(collection)
    original_frame = int(scene.frame_current)
    scene.frame_set(1)
    bpy_module.context.view_layer.update()

    if runtime["placement_factory"] is not None:
        placement = runtime["placement_factory"](
            scene, camera=camera, anchor=(0.0, float(instrument_front_y), 0.0),
        )
        placement_source = "frame_by_plane"
    else:
        placement = _AdapterCameraPlacement(
            scene, camera, (0.0, float(instrument_front_y), 0.0), Vector,
        )
        placement_source = "violin_prince_camera_adapter"
    if not bool(getattr(placement, "uses_camera", False)):
        raise FrameByPlaneError("The active camera could not be bound to the 2.5D multiplane layout.")

    camera_origin = camera.matrix_world.translation.copy()
    camera_rotation = camera.matrix_world.to_quaternion()
    view_frame = camera.data.view_frame(scene=scene)
    frame_width = max(point.x for point in view_frame) - min(point.x for point in view_frame)
    frame_height = max(point.y for point in view_frame) - min(point.y for point in view_frame)
    frame_depth = max(1e-6, abs(float(view_frame[0].z)))
    if frame_width <= 0 or frame_height <= 0:
        raise FrameByPlaneError("The active camera returned an invalid view frame.")

    built_layers = []
    try:
        for layer in sorted(bundle["layers"], key=lambda item: item["distance"], reverse=True):
            position = Vector(placement.location(offset=layer["distance"]))
            distance = max(0.5, (position - camera_origin).length)
            scale_to_depth = distance / frame_depth
            world_width = frame_width * scale_to_depth * layer["cover_scale"]
            world_height = frame_height * scale_to_depth * layer["cover_scale"]
            uniform_scale = world_height * 0.5

            rig = runtime["builder"](
                bpy_module.context, "VP_FBP_" + layer["name"],
                str(layer["directory"]), list(layer["file_names"]), tuple(position),
                target_collection=collection, follow_collection_color=False,
            )
            if not placement.place(rig, offset=layer["distance"]):
                raise FrameByPlaneError(f"Frame By Plane could not place layer {layer['name']} relative to the camera.")
            plane = getattr(rig, "fbp_plane_target", None)
            if plane is None or getattr(plane, "type", "") != "MESH":
                raise FrameByPlaneError(f"Frame By Plane made no renderable image plane for {layer['name']}.")

            # FBP stores the source aspect in the plane mesh; keep the controller scale uniform.
            rig.scale = (uniform_scale, uniform_scale, uniform_scale)
            rig.hide_render = True
            plane.hide_render = False
            plane["vp_fbp_layer_role"] = layer["role"]
            plane["vp_fbp_depth"] = layer["distance"]
            rig["vp_fbp_layer_role"] = layer["role"]
            rig["vp_fbp_story_style"] = bundle["style"]
            rig["vp_fbp_source_manifest"] = bundle["manifest_path"]
            rig["vp_fbp_parallax"] = [layer["parallax_x"], layer["parallax_z"]]

            base = rig.location.copy()
            screen_offset = camera_rotation @ Vector((layer["parallax_x"], layer["parallax_z"], 0.0))
            for frame, sign in ((1, -1.0), (max(2, int(frame_end)), 1.0)):
                rig.location = base + screen_offset * sign
                rig.keyframe_insert(data_path="location", frame=frame)

            animation = getattr(rig, "animation_data", None)
            action = getattr(animation, "action", None) if animation else None
            curves = tuple(getattr(action, "fcurves", ()) or ()) if action else ()
            if not curves and action is not None:
                slot = getattr(animation, "action_slot", None)
                for action_layer in getattr(action, "layers", ()):
                    for strip in getattr(action_layer, "strips", ()):
                        try:
                            channelbag = strip.channelbag(slot) if slot is not None else None
                        except (AttributeError, TypeError, RuntimeError):
                            channelbag = None
                        if channelbag is not None:
                            curves = tuple(channelbag.fcurves)
                            break
                    if curves:
                        break
            for curve in curves:
                for point in curve.keyframe_points:
                    point.interpolation = "BEZIER"
                    point.handle_left_type = "AUTO"
                    point.handle_right_type = "AUTO"

            built_layers.append({
                "name": layer["name"], "role": layer["role"],
                "rig": rig.name, "plane": plane.name,
                "source_files": [str(item) for item in layer["files"]],
                "distance": layer["distance"],
                "world_size": [round(world_width, 4), round(world_height, 4)],
                "parallax": [layer["parallax_x"], layer["parallax_z"]],
                "source_bytes": layer["bytes"],
            })
    finally:
        scene.frame_set(original_frame)
        bpy_module.context.view_layer.update()

    return {
        "enabled": True,
        "mode": "native Frame By Plane multiplane layers + real 3D hero objects",
        "blender_version": runtime["blender_version"],
        "extension_id": runtime["extension_id"],
        "extension_version": runtime["extension_version"],
        "extension_license": runtime["extension_license"],
        "repository_module": runtime["repository_module"],
        "style": bundle["style"], "layer_count": len(built_layers),
        "layers": built_layers,
        "depth_order": "camera-facing planes placed behind the imported 3D violin and bow",
        "parallax": "camera-space depth plus per-layer motion",
        "placement_source": placement_source,
        "builder_parameters": runtime["builder_parameters"],
    }
