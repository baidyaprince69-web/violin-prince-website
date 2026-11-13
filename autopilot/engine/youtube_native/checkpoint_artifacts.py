"""Restore the latest encrypted YouTube upload checkpoint from GitHub Actions artifacts.

The file inside the artifact is already AES-256-GCM encrypted by EncryptedCheckpointStore.
This helper copies the ciphertext only; it never decrypts or logs resumable session URLs.
"""
from __future__ import annotations

import argparse
import io
import json
import os
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import requests


API_ROOT = "https://api.github.com"
DEFAULT_ARTIFACT_NAME = "youtube-native-upload-state"
USER_AGENT = "ViolinPrinceAutopilot/YouTubeCheckpointRestore"


class CheckpointArtifactError(RuntimeError):
    """Unable to safely restore an encrypted upload checkpoint."""


def restore_latest_checkpoint(
    repository: str,
    token: str,
    destination: str | Path,
    *,
    artifact_name: str = DEFAULT_ARTIFACT_NAME,
    current_run_id: str = "",
    session: requests.Session | None = None,
) -> dict[str, Any]:
    repo = str(repository or "").strip()
    if not repo or "/" not in repo:
        raise CheckpointArtifactError("GITHUB_REPOSITORY must be set as owner/repository.")
    if not str(token or "").strip():
        raise CheckpointArtifactError("GITHUB_TOKEN is required to read previous Actions artifacts.")
    if not artifact_name:
        raise CheckpointArtifactError("An artifact name is required.")

    client = session or requests.Session()
    headers = {
        "Authorization": "Bearer " + token,
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": USER_AGENT,
    }
    url = f"{API_ROOT}/repos/{repo}/actions/artifacts"
    listing = client.get(
        url,
        headers=headers,
        params={"name": artifact_name, "per_page": 100},
        timeout=30,
    )
    listing.raise_for_status()
    artifacts = listing.json().get("artifacts", [])
    eligible = [
        item for item in artifacts
        if item.get("name") == artifact_name
        and item.get("expired") is not True
        and str((item.get("workflow_run") or {}).get("id") or "") != str(current_run_id)
        and item.get("archive_download_url")
    ]
    if not eligible:
        return {"restored": False, "reason": "no_previous_checkpoint"}

    def created_key(item: dict[str, Any]) -> str:
        return str(item.get("created_at") or "")

    chosen = max(eligible, key=created_key)
    archive = client.get(chosen["archive_download_url"], headers=headers, timeout=60)
    archive.raise_for_status()
    try:
        with zipfile.ZipFile(io.BytesIO(archive.content)) as package:
            members = [
                name for name in package.namelist()
                if Path(name).name == "youtube-upload-state.enc"
            ]
            if len(members) != 1:
                raise CheckpointArtifactError("The latest checkpoint artifact does not contain exactly one encrypted state file.")
            info = package.getinfo(members[0])
            if info.file_size <= 0 or info.file_size > 2 * 1024 * 1024:
                raise CheckpointArtifactError("The encrypted checkpoint file has an invalid size.")
            content = package.read(info)
    except zipfile.BadZipFile as exc:
        raise CheckpointArtifactError("The latest checkpoint artifact is not a valid ZIP archive.") from exc

    path = Path(destination)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(content)
    os.replace(temporary, path)
    return {
        "restored": True,
        "artifact_id": chosen.get("id"),
        "source_run_id": (chosen.get("workflow_run") or {}).get("id"),
        "created_at": chosen.get("created_at"),
        "destination": str(path),
        "encrypted_bytes": len(content),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", ""))
    parser.add_argument("--token", default=os.environ.get("GH_TOKEN", ""))
    parser.add_argument("--artifact-name", default=DEFAULT_ARTIFACT_NAME)
    parser.add_argument("--destination", default=os.environ.get("YOUTUBE_UPLOAD_STATE_PATH", "work/youtube-upload-state.enc"))
    parser.add_argument("--current-run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    args = parser.parse_args()
    result = restore_latest_checkpoint(
        args.repository,
        args.token,
        args.destination,
        artifact_name=args.artifact_name,
        current_run_id=args.current_run_id,
    )
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
