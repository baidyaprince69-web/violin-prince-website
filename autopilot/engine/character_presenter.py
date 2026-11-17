"""Opt-in staging for the saved Violin Prince presenter character."""
from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


class PresenterIntegrationError(RuntimeError):
    """Raised when an explicitly requested presenter cannot be staged."""


def attach_violin_prince_presenter(
    plan: dict[str, Any],
    *,
    package_dir: str | Path,
    rig_bundle_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Attach the tested repository rig to a plan only when explicitly requested.

    Scene-level presenter_pose and presenter_expression fields select authored
    pose and face plates. The prebuilt rig is copied into the package so the
    existing asset factory can validate and stage every referenced file.
    """
    if plan.get("use_violin_prince_presenter") is not True:
        return plan

    bundle_dir = Path(rig_bundle_dir or (
        Path(__file__).resolve().parent / "assets" / "characters" / "violin-prince-rig"
    )).resolve()
    spec_path = bundle_dir / "character.json"
    if not spec_path.is_file():
        raise PresenterIntegrationError(
            "The Violin Prince presenter was requested, but the tested rig bundle "
            "is missing. Run Character Auto-Rig Test and save its generated bundle first."
        )
    try:
        character = json.loads(spec_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PresenterIntegrationError("The saved Violin Prince character spec is unreadable.") from exc
    if not isinstance(character, dict) or str(character.get("id") or "") != "violin-prince":
        raise PresenterIntegrationError("The saved presenter bundle has an unexpected character id.")

    package_dir = Path(package_dir).resolve()
    character_dir = package_dir / "characters" / "violin-prince"
    character_dir.mkdir(parents=True, exist_ok=True)

    def stage_asset(value: str, label: str) -> str:
        source_name = Path(str(value or "")).name
        if not source_name:
            raise PresenterIntegrationError(f"The saved presenter {label} asset has no filename.")
        source = (bundle_dir / source_name).resolve()
        if bundle_dir not in source.parents or not source.is_file():
            raise PresenterIntegrationError(f"The saved presenter {label} asset is missing: {source_name}")
        target = character_dir / source_name
        shutil.copy2(source, target)
        return str(target.resolve())

    layers = character.get("layers")
    expressions = character.get("expressions")
    pose_assets = character.get("pose_assets")
    if not isinstance(layers, list) or not isinstance(expressions, dict) or not isinstance(pose_assets, dict):
        raise PresenterIntegrationError("The saved presenter bundle lacks layers, expressions or pose assets.")

    for layer in layers:
        if not isinstance(layer, dict):
            raise PresenterIntegrationError("The saved presenter contains an invalid layer entry.")
        layer["src"] = stage_asset(layer.get("src"), "layer")
    for expression in expressions.values():
        if not isinstance(expression, dict):
            raise PresenterIntegrationError("The saved presenter contains an invalid expression entry.")
        expression["src"] = stage_asset(expression.get("src"), "expression")
    for pose in pose_assets.values():
        if not isinstance(pose, dict):
            raise PresenterIntegrationError("The saved presenter contains an invalid pose entry.")
        pose["src"] = stage_asset(pose.get("src"), "pose")

    characters = plan.get("characters") or []
    if not isinstance(characters, list):
        raise PresenterIntegrationError("The daily plan characters field must be an array.")
    if any(
        isinstance(item, dict) and str(item.get("id") or "") == "violin-prince"
        for item in characters
    ):
        raise PresenterIntegrationError(
            "The daily plan already contains a violin-prince character; remove the duplicate "
            "or disable use_violin_prince_presenter."
        )

    default_poses = ("resting_hands", "explaining_two_hands", "open_palms")
    available_poses = set(pose_assets)
    available_expressions = set(expressions)
    scenes = plan.get("scenes") or []
    if not isinstance(scenes, list):
        raise PresenterIntegrationError("The daily plan scenes field must be an array.")
    for index, scene in enumerate(scenes):
        if not isinstance(scene, dict):
            continue
        actions = scene.get("character_actions") or {}
        if not isinstance(actions, dict):
            raise PresenterIntegrationError(
                f"Scene {index + 1} character_actions must be an object."
            )
        if "violin-prince" not in actions:
            requested_pose = str(
                scene.get("presenter_pose") or default_poses[index % len(default_poses)]
            ).strip().casefold()
            requested_expression = str(
                scene.get("presenter_expression") or ("neutral" if index == 0 else "speaking")
            ).strip().casefold()
            pose_name = requested_pose if requested_pose in available_poses else "resting_hands"
            expression_name = (
                requested_expression if requested_expression in available_expressions else "neutral"
            )
            try:
                action_duration = float(scene.get("duration") or 1.2)
            except (TypeError, ValueError):
                action_duration = 1.2
            scene["character_actions"] = {
                **actions,
                "violin-prince": {
                    "pose_asset": pose_name,
                    "expression": expression_name,
                    "duration": action_duration,
                },
            }

    plan["characters"] = [*characters, character]
    plan["presenter_integration"] = {
        "enabled": True,
        "character_id": "violin-prince",
        "asset_bundle": "autopilot/engine/assets/characters/violin-prince-rig",
        "pose_selection": "scene presenter_pose or a safe three-pose default cycle",
        "expressions": "scene presenter_expression or neutral/speaking default",
    }
    return plan
