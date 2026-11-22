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
FULL_BODY_LAYER_ROLES = frozenset({
    "left_thigh", "left_shin", "left_foot",
    "right_thigh", "right_shin", "right_foot",
    "right_index_finger", "right_middle_finger",
    "right_ring_finger", "right_little_finger",
})
FULL_BODY_JOINTS = frozenset({
    "left_hip", "left_knee", "left_ankle",
    "right_hip", "right_knee", "right_ankle",
    "right_index_knuckle", "right_middle_knuckle",
    "right_ring_knuckle", "right_little_knuckle",
})


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

    required_roles = REQUIRED_LAYER_ROLES | (
        FULL_BODY_LAYER_ROLES if str(character.get("body_scope") or "").casefold() == "full_body" else frozenset()
    )
    missing_roles = sorted(required_roles - roles)
    if missing_roles:
        raise CharacterRigError(
            f"Character {character_id} is missing required illustration layers: "
            + ", ".join(missing_roles)
        )

    joints = character.get("joints")
    if not isinstance(joints, dict):
        raise CharacterRigError(f"Character {character_id} must define its joint anchors.")
    required_joints = REQUIRED_JOINTS | (
        FULL_BODY_JOINTS if str(character.get("body_scope") or "").casefold() == "full_body" else frozenset()
    )
    missing_joints = sorted(required_joints - set(joints))
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
        raise CharacterRigError(f"Character {character_id} props must be an object.")
    normalised_props = {}
    for name, value in raw_props.items():
        prop_id = str(name).strip().casefold()
        if not CHARACTER_ID.fullmatch(prop_id) or not isinstance(value, dict):
            raise CharacterRigError(f"Character {character_id} has an invalid prop entry.")
        src = str(value.get("src") or "").strip()
        if not src:
            raise CharacterRigError(f"Character prop {prop_id} has no image source.")
        geometry = {}
        for key, default in (("x", 0), ("y", 0), ("width", 1), ("height", 1)):
            number = _finite_number(value.get(key, default), f"{character_id}.{prop_id}.{key}")
            if key in ("width", "height") and number <= 0:
                raise CharacterRigError(f"{character_id}.{prop_id}.{key} must be positive.")
            geometry[key] = number
        pivot_x = _finite_number(value.get("pivot_x", 0.5), f"{character_id}.{prop_id}.pivot_x")
        pivot_y = _finite_number(value.get("pivot_y", 0.5), f"{character_id}.{prop_id}.pivot_y")
        if not 0 <= pivot_x <= 1 or not 0 <= pivot_y <= 1:
            raise CharacterRigError(f"Character prop {prop_id} pivots must be between 0 and 1.")
        normalised_props[prop_id] = {
            **value, "src": src, **geometry,
            "pivot_x": pivot_x, "pivot_y": pivot_y,
            "z_index": int(value.get("z_index", 50)),
        }

    return {
        **character,
        "id": character_id,
        "layers": normalised_layers,
        "joints": normalised_joints,
        "expressions": normalised_expressions,
        "poses": poses,
        "gestures": gestures,
        "pose_assets": pose_assets,
        "props": normalised_props,
        "body_scope": str(character.get("body_scope") or "upper_body"),
        "scene_actions": character.get("scene_actions") or {},
        "scene_ids": character.get("scene_ids"),
    }
