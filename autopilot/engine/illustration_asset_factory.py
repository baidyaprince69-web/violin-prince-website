"""Stage original, separated illustration layers for the Motion character rig."""
from __future__ import annotations

import json
import re
import shutil
from pathlib import Path
from typing import Any

from PIL import Image

from character_rig import CharacterRigError, validate_character_spec


class IllustrationAssetError(RuntimeError):
    """Raised when a character illustration bundle is incomplete or unsafe."""


def _resolve_source(value: str, source_root: Path, work_root: Path) -> Path:
    raw = Path(value).expanduser()
    candidates = [raw] if raw.is_absolute() else [source_root / raw, work_root / raw]
    allowed = [source_root.resolve(), work_root.resolve()]
    for candidate in candidates:
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if not any(resolved == root or root in resolved.parents for root in allowed):
            continue
        if resolved.is_file():
            return resolved
    raise IllustrationAssetError(
        f"Illustration layer does not exist in the production workspace: {value}"
    )


def _copy_image(value: str, destination: Path, source_root: Path, work_root: Path) -> str:
    source = _resolve_source(value, source_root, work_root)
    if source.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"}:
        raise IllustrationAssetError(f"Unsupported character layer format: {source.suffix}")
    try:
        with Image.open(source) as image:
            image.verify()
        with Image.open(source) as image:
            if image.width < 8 or image.height < 8:
                raise IllustrationAssetError(f"Character image is too small: {source.name}")
    except IllustrationAssetError:
        raise
    except Exception as exc:
        raise IllustrationAssetError(
            f"Character image is not a readable image: {source.name}"
        ) from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination.as_posix()


def prepare_character_assets(
    plan: dict[str, Any],
    *,
    source_root: str | Path,
    destination_root: str | Path,
) -> list[dict[str, Any]]:
    """Validate and stage separated character body parts and facial-expression plates.

    The factory deliberately refuses to invent geometric body placeholders when
    a required original illustration layer is missing.
    """
    source_root = Path(source_root).resolve()
    work_root = Path("work").resolve()
    destination_root = Path(destination_root).resolve()
    destination_root.mkdir(parents=True, exist_ok=True)
    raw_characters = plan.get("characters") or []
    if not isinstance(raw_characters, list):
        raise IllustrationAssetError("characters must be an array.")
    if not raw_characters:
        (destination_root / "manifest.json").write_text(
            json.dumps({"schema_version": 1, "characters": []}, indent=2) + "\n",
            encoding="utf-8",
        )
        return []

    staged, seen = [], set()
    for raw_character in raw_characters:
        try:
            character = validate_character_spec(raw_character)
        except CharacterRigError as exc:
            raise IllustrationAssetError(str(exc)) from exc
        character_id = character["id"]
        if character_id in seen:
            raise IllustrationAssetError(f"Duplicate character id: {character_id}")
        seen.add(character_id)
        character_folder = destination_root / character_id
        layers = []
        for layer in character["layers"]:
            extension = Path(layer["src"]).suffix.lower()
            file_name = re.sub(r"[^a-z0-9_-]+", "-", layer["id"]) + extension
            target = character_folder / file_name
            layers.append({
                **layer,
                "src": _copy_image(layer["src"], target, source_root, work_root),
            })

        face_layer = next(item for item in layers if item["role"] == "face")
        expressions = {}
        for name, expression in character["expressions"].items():
            src = expression["src"]
            target = character_folder / ("expression-" + name + Path(src).suffix.lower())
            expressions[name] = {
                "src": _copy_image(src, target, source_root, work_root),
                "x": face_layer["x"], "y": face_layer["y"],
                "width": face_layer["width"], "height": face_layer["height"],
            }

        pose_assets = {}
        for name, pose in character.get("pose_assets", {}).items():
            src = pose["src"]
            target = character_folder / ("pose-" + name + Path(src).suffix.lower())
            pose_assets[name] = {
                "src": _copy_image(src, target, source_root, work_root),
            }

        scene_actions = character.get("scene_actions") or {}
        if not isinstance(scene_actions, dict):
            raise IllustrationAssetError(
                f"Character {character_id} scene_actions must be an object."
            )
        staged.append({
            "id": character_id,
            "name": str(character.get("name") or character_id),
            "canvas": character.get("canvas"),
            "layers": layers,
            "joints": character["joints"],
            "expressions": expressions,
            "pose_assets": pose_assets,
            "props": props,
            "body_scope": character.get("body_scope", "upper_body"),
            "poses": character["poses"],
            "gestures": character["gestures"],
            "scene_actions": scene_actions,
            "scene_ids": character.get("scene_ids"),
        })

    (destination_root / "manifest.json").write_text(
        json.dumps({"schema_version": 1, "characters": staged}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return staged
