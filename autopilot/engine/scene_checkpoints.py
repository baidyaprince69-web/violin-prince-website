"""Content-addressed scene-render checkpoints and bounded transient retries."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any, Callable


def sha256_file(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def fingerprint_payload(payload: Any) -> str:
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def scene_fingerprint(
    scene: dict[str, Any],
    image_path: str | Path,
    *,
    renderer_version: str,
    render_settings: dict[str, Any] | None = None,
    character_asset_paths: list[str | Path] | None = None,
) -> str:
    assets = []
    for item in character_asset_paths or []:
        asset = Path(item)
        assets.append({"name": asset.name, "sha256": sha256_file(asset) if asset.is_file() else "missing"})
    return fingerprint_payload({
        "scene": scene,
        "image_sha256": sha256_file(image_path),
        "character_assets": assets,
        "renderer_version": str(renderer_version),
        "render_settings": render_settings or {},
    })


def checkpoint_paths(cache_dir: str | Path, scene_id: str) -> tuple[Path, Path]:
    root = Path(cache_dir)
    safe = "".join(char for char in str(scene_id).casefold() if char.isalnum() or char in "-_")
    if not safe:
        raise ValueError("Scene checkpoint id must contain letters or numbers.")
    return root / f"{safe}.mp4", root / f"{safe}.json"


def load_valid_checkpoint(cache_dir: str | Path, scene_id: str, fingerprint: str) -> Path | None:
    video_path, metadata_path = checkpoint_paths(cache_dir, scene_id)
    if not video_path.is_file() or not metadata_path.is_file():
        return None
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("status") != "complete" or metadata.get("fingerprint") != fingerprint:
            return None
        if video_path.stat().st_size < 4096:
            return None
        if metadata.get("output_sha256") != sha256_file(video_path):
            return None
    except (OSError, ValueError, TypeError):
        return None
    return video_path


def save_checkpoint(
    cache_dir: str | Path,
    scene_id: str,
    fingerprint: str,
    rendered_video: str | Path,
    *,
    qa_report: dict[str, Any] | None = None,
) -> Path:
    root = Path(cache_dir)
    root.mkdir(parents=True, exist_ok=True)
    video_path, metadata_path = checkpoint_paths(root, scene_id)
    source = Path(rendered_video)
    if not source.is_file() or source.stat().st_size < 4096:
        raise ValueError("Cannot checkpoint a missing or unexpectedly small scene render.")
    temporary_video = video_path.with_suffix(".mp4.tmp")
    temporary_metadata = metadata_path.with_suffix(".json.tmp")
    shutil.copy2(source, temporary_video)
    output_sha = sha256_file(temporary_video)
    payload = {
        "schema_version": 1,
        "scene_id": str(scene_id),
        "status": "complete",
        "fingerprint": str(fingerprint),
        "output_sha256": output_sha,
        "file_size_bytes": temporary_video.stat().st_size,
        "qa_report": qa_report or {},
    }
    temporary_metadata.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary_video, video_path)
    os.replace(temporary_metadata, metadata_path)
    return video_path


def is_transient_render_error(error: BaseException) -> bool:
    if isinstance(error, (TimeoutError, ConnectionError, subprocess.TimeoutExpired)):
        return True
    name = type(error).__name__.casefold()
    message = str(error).casefold()
    return name in {"timeout", "connectionerror", "connecttimeout", "readtimeout"} or any(
        token in message for token in ("temporary network", "connection reset", "timed out", "temporarily unavailable")
    )


def retry_transient(
    operation: Callable[[], Any],
    *,
    attempts: int = 3,
    sleep: Callable[[float], None] = time.sleep,
) -> Any:
    """Retry only transient failures; deterministic validation/render errors fail immediately."""
    limit = max(1, min(int(attempts), 4))
    for attempt in range(limit):
        try:
            return operation()
        except Exception as exc:
            if attempt + 1 >= limit or not is_transient_render_error(exc):
                raise
            sleep(float(2 ** attempt))
    raise RuntimeError("unreachable")
