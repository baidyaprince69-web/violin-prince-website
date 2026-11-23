"""Validation contract for detailed, layered 2D character rigs."""
from __future__ import annotations

import math
import re
from typing import Any

CHARACTER_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
REQUIRED_LAYER_ROLES = frozenset({
    "torso", "head", "face",
    "left_upper_arm", "left_forearm", "left_hand",
    "right_upper_arm", "right_forearm", "right_hand",
})
REQUIRED_JOINTS = frozenset({
    "neck", "left_shoulder", "left_elbow", "left_wrist",
    "right_shoulder", "right_elbow", "right_wrist",
})
LEG_LAYER_ROLES = frozenset(
    f"{side}_{part}"
    for side in ("left", "right")
    for part in ("thigh", "calf", "foot")
)
LEG_JOINTS = frozenset(
    f"{side}_{joint}"
    for side in ("left", "right")
    for joint in ("hip", "knee", "ankle")
)
FINGER_ROLES = frozenset({
    "finger_index", "finger_middle", "finger_ring", "finger_little"
})
FINGER_JOINTS = frozenset({
    "right_index_base", "right_middle_base",
    "right_ring_base", "right_little_base",
})
FINGER_PHALANGE_ROLES = frozenset(
    f"finger_{finger}_{segment}"
    for finger in ("index", "middle", "ring", "little")
    for segment in ("middle", "tip")
)
FINGER_PHALANGE_JOINTS = frozenset(
    f"right_{finger}_{joint}"
    for finger in ("index", "middle", "ring", "little")
    for joint in ("pip", "dip")
)


class CharacterRigError(ValueError):
    """Raised when illustrated character layers cannot form a safe 2D rig."""


def _finite_number(value: Any, label: str) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise CharacterRigError(f"{label} must be numeric.") from exc
    if not math.isfinite(number):
        raise CharacterRigError(f"{label} must be finite.")
    return number


def validate_character_spec(character: dict[str, Any]) -> dict[str, Any]:
    """Validate image layers, pivot joints, poses and facial-expression assets."""
    if not isinstance(character, dict):
        raise CharacterRigError("Each character must be an object.")
    character_id = str(character.get("id") or "").strip().casefold()
    if not CHARACTER_ID.fullmatch(character_id):
        raise CharacterRigError("Character id must use lowercase letters, numbers, '-' or '_'.")
    layers = character.get("layers")
    if not isinstance(layers, list):
        raise CharacterRigError(f"Character {character_id} must provide a layers array.")

    roles, layer_ids, normalised_layers = set(), set(), []
    for index, layer in enumerate(layers):
        if not isinstance(layer, dict):
            raise CharacterRigError(f"Character {character_id} layer {index + 1} must be an object.")
        role = str(layer.get("role") or layer.get("id") or "").strip().casefold()
        layer_id = str(layer.get("id") or role).strip().casefold()
        if not CHARACTER_ID.fullmatch(layer_id) or not role:
            raise CharacterRigError(f"Character {character_id} has an invalid layer id or role.")
        if layer_id in layer_ids:
            raise CharacterRigError(f"Character {character_id} contains duplicate layer id {layer_id}.")
        layer_ids.add(layer_id)
        roles.add(role)
        src = str(layer.get("src") or "").strip()
        if not src:
            raise CharacterRigError(f"Character {character_id} layer {layer_id} has no image source.")

        geometry = {}
        for key, default in (("x", 0), ("y", 0), ("width", 1), ("height", 1)):
            value = _finite_number(layer.get(key, default), f"{character_id}.{layer_id}.{key}")
            if key in ("width", "height") and value <= 0:
                raise CharacterRigError(f"{character_id}.{layer_id}.{key} must be positive.")
            geometry[key] = value
        pivot_x = _finite_number(layer.get("pivot_x", 0.5), f"{character_id}.{layer_id}.pivot_x")
        pivot_y = _finite_number(layer.get("pivot_y", 0.5), f"{character_id}.{layer_id}.pivot_y")
        if not 0 <= pivot_x <= 1 or not 0 <= pivot_y <= 1:
            raise CharacterRigError(f"{character_id}.{layer_id} pivots must be between 0 and 1.")
        normalised_layers.append({
            **layer, "id": layer_id, "role": role, "src": src,
            **geometry, "pivot_x": pivot_x, "pivot_y": pivot_y,
            "z_index": int(layer.get("z_index", index + 1)),
        })

    missing_roles = sorted(REQUIRED_LAYER_ROLES - roles)
    if missing_roles:
        raise CharacterRigError(
            f"Character {character_id} is missing required illustration layers: "
            + ", ".join(missing_roles)
        )
    present_leg_roles = roles & LEG_LAYER_ROLES
    if present_leg_roles and present_leg_roles != LEG_LAYER_ROLES:
        raise CharacterRigError(
            f"Character {character_id} must provide all six leg layers when enabling a full-body rig."
        )
    present_finger_roles = roles & FINGER_ROLES
    if present_finger_roles and present_finger_roles != FINGER_ROLES:
        raise CharacterRigError(
            f"Character {character_id} must provide all four finger layers when enabling finger articulation."
        )
    present_phalange_roles = roles & FINGER_PHALANGE_ROLES
    if present_phalange_roles and present_phalange_roles != FINGER_PHALANGE_ROLES:
        raise CharacterRigError(
            f"Character {character_id} must provide both middle and tip segments for all four articulated fingers."
        )

    joints = character.get("joints")
    if not isinstance(joints, dict):
        raise CharacterRigError(f"Character {character_id} must define its joint anchors.")
    conditional_joints = set()
    if present_leg_roles:
        conditional_joints.update(LEG_JOINTS)
    if present_finger_roles:
        conditional_joints.update(FINGER_JOINTS)
    if present_phalange_roles:
        conditional_joints.update(FINGER_PHALANGE_JOINTS)
    missing_joints = sorted((REQUIRED_JOINTS | conditional_joints) - set(joints))
    if missing_joints:
        raise CharacterRigError(
            f"Character {character_id} is missing joints: " + ", ".join(missing_joints)
        )
    normalised_joints = {}
    for name, point in joints.items():
        if not isinstance(point, dict):
            raise CharacterRigError(f"Joint {name} must contain x and y coordinates.")
        x = _finite_number(point.get("x"), f"{character_id}.{name}.x")
        y = _finite_number(point.get("y"), f"{character_id}.{name}.y")
        if not 0 <= x <= 1 or not 0 <= y <= 1:
            raise CharacterRigError(f"Joint {name} coordinates must be normalised from 0 to 1.")
        normalised_joints[str(name)] = {"x": x, "y": y}

    # Optional source-mesh deformation and joint-surface metadata is validated
    # here so malformed geometry never reaches the frame-sampled renderer.
    for layer in normalised_layers:
        role = layer["role"]
        mesh = layer.get("mesh_deformation")
        if mesh is not None:
            if not isinstance(mesh, dict):
                raise CharacterRigError(f"{character_id}.{role}.mesh_deformation must be an object.")
            profile = str(mesh.get("profile") or "").strip().casefold()
            if profile not in {"torso", "limb_joint"}:
                raise CharacterRigError(f"{character_id}.{role} has an unsupported mesh profile.")
            driver_role = str(mesh.get("driver_role") or "").strip().casefold()
            if driver_role not in roles:
                raise CharacterRigError(f"{character_id}.{role} mesh driver_role is not a rig layer.")
            axes = {}
            for field in ("axis_start", "axis_end"):
                point = mesh.get(field)
                if not isinstance(point, (list, tuple)) or len(point) != 2:
                    raise CharacterRigError(f"{character_id}.{role} mesh {field} must be a two-value point.")
                values = [_finite_number(point[index], f"{character_id}.{role}.{field}[{index}]")
                          for index in range(2)]
                if any(value < 0 or value > 1 for value in values):
                    raise CharacterRigError(f"{character_id}.{role} mesh {field} must be normalized from 0 to 1.")
                axes[field] = values
            if math.hypot(
                axes["axis_end"][0] - axes["axis_start"][0],
                axes["axis_end"][1] - axes["axis_start"][1],
            ) < 0.08:
                raise CharacterRigError(f"{character_id}.{role} mesh axis is too short.")
            columns = int(mesh.get("columns", 0))
            rows = int(mesh.get("rows", 0))
            if not 2 <= columns <= 8 or not 2 <= rows <= 12:
                raise CharacterRigError(f"{character_id}.{role} mesh grid dimensions are outside supported limits.")
            influence = str(mesh.get("influence") or "").strip().casefold()
            if influence not in {"center", "proximal", "distal"}:
                raise CharacterRigError(f"{character_id}.{role} mesh influence must be center, proximal or distal.")
            max_angle = _finite_number(mesh.get("max_angle_deg"), f"{character_id}.{role}.max_angle_deg")
            max_displacement = _finite_number(
                mesh.get("max_displacement_px"), f"{character_id}.{role}.max_displacement_px"
            )
            if not 0 < max_angle <= 45 or not 0 < max_displacement <= 8:
                raise CharacterRigError(f"{character_id}.{role} mesh deformation limits are unsafe.")
        surface = layer.get("joint_surface")
        if surface is not None:
            if not isinstance(surface, dict):
                raise CharacterRigError(f"{character_id}.{role}.joint_surface must be an object.")
            joint_name = str(surface.get("joint") or "").strip()
            parent_role = str(surface.get("parent_role") or "").strip().casefold()
            child_role = str(surface.get("child_role") or "").strip().casefold()
            if joint_name not in normalised_joints:
                raise CharacterRigError(f"{character_id}.{role} joint surface refers to an unknown joint.")
            if parent_role not in roles or child_role not in roles or parent_role == child_role:
                raise CharacterRigError(f"{character_id}.{role} joint surface needs distinct parent/child rig roles.")
            blend = _finite_number(surface.get("blend_weight", 0.5), f"{character_id}.{role}.blend_weight")
            if not 0 <= blend <= 1:
                raise CharacterRigError(f"{character_id}.{role} joint-surface blend_weight must be 0 to 1.")

    expressions = character.get("expressions")
    if not isinstance(expressions, dict) or "neutral" not in expressions or len(expressions) < 2:
        raise CharacterRigError(
            f"Character {character_id} needs a neutral expression and at least one alternate expression."
        )
    normalised_expressions = {}
    for name, value in expressions.items():
        expression_name = str(name).strip().casefold()
        if not CHARACTER_ID.fullmatch(expression_name):
            raise CharacterRigError(f"Character {character_id} has an invalid expression name.")
        src = value.get("src") if isinstance(value, dict) else value
        if not str(src or "").strip():
            raise CharacterRigError(f"Expression {expression_name} has no image source.")
        normalised_expressions[expression_name] = {"src": str(src).strip()}

    poses = character.get("poses") or {}
    gestures = character.get("gestures") or {}
    if not isinstance(poses, dict) or not isinstance(gestures, dict):
        raise CharacterRigError(f"Character {character_id} poses and gestures must be objects.")
    raw_pose_assets = character.get("pose_assets") or {}
    if not isinstance(raw_pose_assets, dict):
        raise CharacterRigError(f"Character {character_id} pose_assets must be an object.")
    pose_assets = {}
    for name, value in raw_pose_assets.items():
        pose_name = str(name).strip().casefold()
        if not CHARACTER_ID.fullmatch(pose_name):
            raise CharacterRigError(f"Character {character_id} has an invalid pose asset name.")
        src = value.get("src") if isinstance(value, dict) else value
        if not str(src or "").strip():
            raise CharacterRigError(f"Pose asset {pose_name} has no image source.")
        pose_assets[pose_name] = {"src": str(src).strip()}

    raw_props = character.get("props") or {}
    if not isinstance(raw_props, dict):
        raise CharacterRigError(f"Character {character_id} props must be an object keyed by prop id.")
    normalised_props = {}
    valid_attachment_roles = roles | {"torso", "left_hand", "right_hand"}
    for prop_id, prop in raw_props.items():
        prop_name = str(prop_id).strip().casefold()
        if not CHARACTER_ID.fullmatch(prop_name) or not isinstance(prop, dict):
            raise CharacterRigError(f"Character {character_id} has an invalid prop definition.")
        src = str(prop.get("src") or "").strip()
        if not src:
            raise CharacterRigError(f"Prop {prop_name} has no image source.")
        geometry = {}
        for key, default in (("x", 0), ("y", 0), ("width", 1), ("height", 1)):
            value = _finite_number(prop.get(key, default), f"{character_id}.props.{prop_name}.{key}")
            if key in ("width", "height") and value <= 0:
                raise CharacterRigError(f"Prop {prop_name} {key} must be positive.")
            geometry[key] = value
        pivot_x = _finite_number(prop.get("pivot_x", 0.5), f"{prop_name}.pivot_x")
        pivot_y = _finite_number(prop.get("pivot_y", 0.5), f"{prop_name}.pivot_y")
        if not 0 <= pivot_x <= 1 or not 0 <= pivot_y <= 1:
            raise CharacterRigError(f"Prop {prop_name} pivots must be between 0 and 1.")
        attach_to = str(prop.get("attach_to") or "torso").strip().casefold()
        if attach_to not in valid_attachment_roles:
            raise CharacterRigError(f"Prop {prop_name} attaches to unknown rig role {attach_to}.")
        normalised_props[prop_name] = {
            **prop, "id": prop_name, "src": src, **geometry,
            "pivot_x": pivot_x, "pivot_y": pivot_y,
            "z_index": int(prop.get("z_index", 25)),
            "attach_to": attach_to,
        }

    head_asset_maps = {}
    for field in ("head_variants", "head_angles"):
        raw_assets = character.get(field) or {}
        if not isinstance(raw_assets, dict):
            raise CharacterRigError(f"Character {character_id} {field} must be an object.")
        normalised_assets = {}
        for name, asset in raw_assets.items():
            asset_name = str(name).strip().casefold()
            if not CHARACTER_ID.fullmatch(asset_name) or not isinstance(asset, dict):
                raise CharacterRigError(f"Character {character_id} has an invalid {field} entry.")
            src = str(asset.get("src") or "").strip()
            if not src:
                raise CharacterRigError(f"{field[:-1].replace('_', ' ')} {asset_name} has no image source.")
            geometry = {}
            for key, default in (("x", 0), ("y", 0), ("width", 1), ("height", 1)):
                number = _finite_number(asset.get(key, default), f"{character_id}.{field}.{asset_name}.{key}")
                if key in ("width", "height") and number <= 0:
                    raise CharacterRigError(f"{field} {asset_name} {key} must be positive.")
                geometry[key] = number
            pivot_x = _finite_number(asset.get("pivot_x", 0.5), f"{asset_name}.pivot_x")
            pivot_y = _finite_number(asset.get("pivot_y", 0.92), f"{asset_name}.pivot_y")
            if not 0 <= pivot_x <= 1 or not 0 <= pivot_y <= 1:
                raise CharacterRigError(f"{field} {asset_name} pivots must be between 0 and 1.")
            normalised_assets[asset_name] = {
                **asset, "src": src, **geometry,
                "pivot_x": pivot_x, "pivot_y": pivot_y,
                "z_index": int(asset.get("z_index", 85)),
            }
        head_asset_maps[field] = normalised_assets

    return {
        **character,
        "head_variants": head_asset_maps["head_variants"],
        "head_angles": head_asset_maps["head_angles"],
        "id": character_id,
        "layers": normalised_layers,
        "joints": normalised_joints,
        "expressions": normalised_expressions,
        "poses": poses,
        "gestures": gestures,
        "pose_assets": pose_assets,
        "props": normalised_props,
        "scene_actions": character.get("scene_actions") or {},
        "scene_ids": character.get("scene_ids"),
    }
