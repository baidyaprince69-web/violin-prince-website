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

    joints = character.get("joints")
    if not isinstance(joints, dict):
        raise CharacterRigError(f"Character {character_id} must define its joint anchors.")
    missing_joints = sorted(REQUIRED_JOINTS - set(joints))
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

    return {
        **character,
        "id": character_id,
        "layers": normalised_layers,
        "joints": normalised_joints,
        "expressions": normalised_expressions,
        "poses": poses,
        "gestures": gestures,
        "scene_actions": character.get("scene_actions") or {},
        "scene_ids": character.get("scene_ids"),
    }
