"""Opt-in staging for the saved Violin Prince presenter character."""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any


class PresenterIntegrationError(RuntimeError):
    """Raised when an explicitly requested presenter cannot be staged."""


def enable_presenter_from_environment(
    plan: dict[str, Any],
    value: str | None = None,
) -> dict[str, Any]:
    """Apply the daily workflow's explicit presenter-enable switch.

    An explicit plan-level true value remains valid. The environment setting
    enables the presenter for every daily plan only when the workflow opts in.
    """
    setting = os.environ.get("VIOLIN_PRINCE_PRESENTER_ENABLED", "false") if value is None else value
    if str(setting).strip().casefold() in {"1", "true", "yes", "on"}:
        plan["use_violin_prince_presenter"] = True
    return plan


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
    props = character.get("props") or {}
    if (not isinstance(layers, list) or not isinstance(expressions, dict)
            or not isinstance(pose_assets, dict) or not isinstance(props, dict)):
        raise PresenterIntegrationError("The saved presenter bundle lacks layers, expressions, pose assets or valid props.")

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
    for prop in props.values():
        if not isinstance(prop, dict):
            raise PresenterIntegrationError("The saved presenter contains an invalid instrument prop entry.")
        prop["src"] = stage_asset(prop.get("src"), "instrument prop")

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
        # Do not place a static full-body pose on every image. The scene
        # director decides visibility and placement; gestures animate the
        # separated rig unless a plan explicitly requests a pose plate.
        if "violin-prince" in actions:
            action = actions["violin-prince"]
            if not isinstance(action, dict):
                raise PresenterIntegrationError(
                    f"Scene {index + 1} violin-prince action must be an object."
                )
            if action.get("visible") is True and not action.get("pose_asset"):
                action.setdefault("gesture", "explain")
                action.setdefault("expression", "speaking")
            actions["violin-prince"] = action
            scene["character_actions"] = actions

    plan["characters"] = [*characters, character]
    plan["presenter_integration"] = {
        "enabled": True,
        "character_id": "violin-prince",
        "asset_bundle": "autopilot/engine/assets/characters/violin-prince-rig",
        "visibility_and_placement": "narration-aware scene director",
        "animation": "articulated rig gestures; static pose plates only when explicitly requested",
    }
    return plan
