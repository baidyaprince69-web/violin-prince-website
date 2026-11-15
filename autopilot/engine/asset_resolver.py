"""Resolve licensed Sketchfab assets for use in Blender.

Downloads only through Sketchfab's authenticated Download API. If a model cannot
be downloaded, the resolver writes a source/creator/licence reference package and,
when its licence permits the intended commercial use, a provider thumbnail for
internal modelling reference. It never scrapes the viewer or bypasses access rules.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import stat
import sys
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests

API_ROOT = "https://api.sketchfab.com/v3"
DEFAULT_MODEL_URL = (
    "https://sketchfab.com/3d-models/violin-0162dea1b1044cd281c57af5e5fc2046"
)
MAX_ARCHIVE_BYTES = 300 * 1024 * 1024
MAX_EXTRACTED_BYTES = 1024 * 1024 * 1024
MAX_REFERENCE_BYTES = 20 * 1024 * 1024
UID_RE = re.compile(r"^[a-f0-9]{32}$", re.IGNORECASE)
URL_UID_RE = re.compile(r"-([a-f0-9]{32})/?$", re.IGNORECASE)

# Default to assets that can be used in a monetized Violin Prince video.
# Unknown, NonCommercial, NoDerivatives and Editorial licences require review.
COMMERCIAL_LICENSES = {
    "cc0", "cc0-1-0", "cc0-1.0", "cc-by", "cc-by-4.0", "cc-by-4-0", "by",
    "cc-attribution", "cc-attribution-4.0", "cc-attribution-4-0",
}


class AssetResolutionError(RuntimeError):
    """Raised when an asset cannot be safely resolved."""


def model_uid_from_url(value: str) -> str:
    value = str(value or "").strip()
    if UID_RE.fullmatch(value):
        return value.lower()
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or parsed.hostname not in {
        "sketchfab.com", "www.sketchfab.com"
    }:
        raise AssetResolutionError("Provide a Sketchfab model URL or 32-character model UID.")
    match = URL_UID_RE.search(parsed.path)
    if not match:
        raise AssetResolutionError("The Sketchfab URL does not contain a valid model UID.")
    return match.group(1).lower()


def _license_details(model: dict[str, Any]) -> tuple[str, str, str]:
    raw = model.get("license")
    if isinstance(raw, dict):
        code = str(raw.get("slug") or raw.get("uid") or raw.get("name") or "")
        label = str(raw.get("label") or raw.get("name") or code)
        license_url = str(raw.get("url") or model.get("licenseUrl") or "")
    else:
        code = str(raw or "")
        label = str(model.get("licenseLabel") or code)
        license_url = str(model.get("licenseUrl") or "")
    normalized = re.sub(r"[^a-z0-9]+", "-", code.casefold()).strip("-")
    normalized_label = re.sub(r"[^a-z0-9]+", "-", label.casefold()).strip("-")
    combined = f"{normalized}-{normalized_label}"
    blocked = any(term in combined for term in (
        "noncommercial", "non-commercial", "by-nc", "-nc", "editorial",
        "no-derivatives", "no-derivative", "-nd",
    ))
    allowed = not blocked and (
        normalized in COMMERCIAL_LICENSES
        or normalized_label in COMMERCIAL_LICENSES
        or combined in {"cc0-public-domain", "cc-attribution"}
        or "cc0" in combined
        or "cc-attribution-4-0" in combined
    )
    return normalized or normalized_label or "unknown", label or "Unknown", license_url


def _creator(model: dict[str, Any]) -> str:
    user = model.get("user") or {}
    if isinstance(user, dict):
        return str(user.get("username") or user.get("displayName") or user.get("name") or "Unknown creator")
    return "Unknown creator"


def _model_name(model: dict[str, Any]) -> str:
    return str(model.get("name") or model.get("title") or "Sketchfab model")


def _thumbnail_url(model: dict[str, Any]) -> str | None:
    thumbnails = model.get("thumbnails") or {}
    images = thumbnails.get("images") if isinstance(thumbnails, dict) else None
    candidates = []
    if isinstance(images, list):
        for item in images:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url") or "")
            parsed = urlparse(url)
            if parsed.scheme == "https" and parsed.hostname:
                try:
                    area = int(item.get("width") or 0) * int(item.get("height") or 0)
                except (TypeError, ValueError):
                    area = 0
                candidates.append((area, url))
    return max(candidates, default=(0, None))[1]


def _request_json(session: requests.Session, url: str, *, headers=None) -> dict[str, Any]:
    try:
        response = session.get(url, headers=headers or {}, timeout=(15, 45))
        response.raise_for_status()
        payload = response.json()
    except requests.RequestException as exc:
        raise AssetResolutionError(f"Sketchfab request failed: {str(exc)[:400]}") from exc
    except ValueError as exc:
        raise AssetResolutionError("Sketchfab returned invalid JSON.") from exc
    if not isinstance(payload, dict):
        raise AssetResolutionError("Sketchfab returned an unexpected response.")
    return payload


def fetch_model_metadata(uid: str, session: requests.Session | None = None) -> dict[str, Any]:
    client = session or requests.Session()
    return _request_json(client, f"{API_ROOT}/models/{uid}")


def _download_to_file(
    session: requests.Session, url: str, destination: Path, maximum_bytes: int
) -> int:
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise AssetResolutionError("Refusing a non-HTTPS asset URL.")
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    total = 0
    try:
        with session.get(url, stream=True, timeout=(20, 90)) as response:
            response.raise_for_status()
            declared = response.headers.get("Content-Length")
            if declared and int(declared) > maximum_bytes:
                raise AssetResolutionError("The asset exceeds the configured download-size limit.")
            with temporary.open("wb") as output:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > maximum_bytes:
                        raise AssetResolutionError("The asset exceeded the configured download-size limit.")
                    output.write(chunk)
        if total < 16:
            raise AssetResolutionError("The downloaded asset is empty or incomplete.")
        temporary.replace(destination)
        return total
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def _safe_extract_glb_or_gltf(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    extracted_total = 0
    try:
        with zipfile.ZipFile(archive) as package:
            for info in package.infolist():
                member = Path(info.filename)
                mode = info.external_attr >> 16
                if member.is_absolute() or ".." in member.parts or stat.S_ISLNK(mode):
                    raise AssetResolutionError("The model archive contains an unsafe file path.")
                if info.is_dir():
                    continue
                extracted_total += int(info.file_size)
                if extracted_total > MAX_EXTRACTED_BYTES:
                    raise AssetResolutionError("The extracted model exceeds the size limit.")
                target = (destination / member).resolve()
                if destination.resolve() not in target.parents:
                    raise AssetResolutionError("The model archive attempted to write outside its folder.")
                target.parent.mkdir(parents=True, exist_ok=True)
                with package.open(info) as source, target.open("wb") as output:
                    shutil.copyfileobj(source, output)
    except zipfile.BadZipFile as exc:
        raise AssetResolutionError("Sketchfab's glTF download was not a valid ZIP archive.") from exc

    models = sorted(destination.rglob("*.glb")) + sorted(destination.rglob("*.gltf"))
    if not models:
        raise AssetResolutionError("The downloaded archive contains neither a GLB nor a glTF model.")
    return models[0]


def _write_manifest(folder: Path, record: dict[str, Any]) -> Path:
    manifest = folder / "asset-provenance.json"
    manifest.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def resolve_sketchfab_asset(
    model_url: str,
    output_dir: str | Path,
    *,
    access_token: str | None = None,
    session: requests.Session | None = None,
    require_download: bool = False,
) -> dict[str, Any]:
    uid = model_uid_from_url(model_url)
    folder = Path(output_dir).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    client = session or requests.Session()
    model = fetch_model_metadata(uid, client)
    license_code, license_label, license_url = _license_details(model)
    license_text = (license_code + " " + license_label).casefold()
    license_blocked = any(term in license_text for term in (
        "noncommercial", "non-commercial", "by-nc", "-nc", "editorial",
        "no-derivatives", "no-derivative", "-nd",
    ))
    commercial_ok = license_code in COMMERCIAL_LICENSES and not license_blocked
    raw_downloadable = model.get("isDownloadable", model.get("is_downloadable", False))
    downloadable = raw_downloadable is True or str(raw_downloadable).strip().casefold() in {"1", "true", "yes"}
    creator = _creator(model)
    viewer_url = str(model.get("viewerUrl") or model.get("url") or model_url)
    record: dict[str, Any] = {
        "provider": "Sketchfab",
        "model_uid": uid,
        "model_name": _model_name(model),
        "source_url": model_url,
        "viewer_url": viewer_url,
        "creator": creator,
        "license_code": license_code,
        "license_label": license_label,
        "license_url": license_url,
        "is_downloadable": downloadable,
        "commercial_use_allowed": commercial_ok,
        "resolution": "reference_only",
        "local_model_path": None,
        "reference_image_path": None,
        "attribution": f"{_model_name(model)} by {creator} on Sketchfab ({license_label})",
    }

    if not commercial_ok:
        record["reason"] = (
            "The licence is NonCommercial, NoDerivatives, Editorial or unrecognized. "
            "The asset is not approved for a monetized Violin Prince production."
        )
    elif not downloadable:
        record["reason"] = "The creator has not enabled model downloads through Sketchfab."
    elif not access_token:
        record["reason"] = (
            "The model is marked downloadable, but an authenticated Sketchfab access token "
            "is required by the official Download API."
        )
    else:
        headers = {"Authorization": "Bearer " + access_token}
        download_info = _request_json(
            client, f"{API_ROOT}/models/{uid}/download", headers=headers
        )
        gltf = download_info.get("gltf") or {}
        archive_url = str(gltf.get("url") or "")
        if not archive_url:
            raise AssetResolutionError("Sketchfab did not return an authorized glTF download.")
        archive_path = folder / "model-download.zip"
        _download_to_file(client, archive_url, archive_path, MAX_ARCHIVE_BYTES)
        model_path = _safe_extract_glb_or_gltf(archive_path, folder / "model")
        archive_path.unlink(missing_ok=True)
        record.update({
            "resolution": "downloaded_model",
            "local_model_path": str(model_path),
            "reason": "Downloaded through the official authenticated Sketchfab Download API.",
        })

    # A provider thumbnail is a modelling reference only, not a substitute for
    # mesh geometry. Fetch it only when the model's licence permits commercial use.
    if record["resolution"] == "reference_only" and commercial_ok and not record["reference_image_path"]:
        thumbnail_url = _thumbnail_url(model)
        if thumbnail_url:
            parsed = urlparse(thumbnail_url)
            suffix = Path(parsed.path).suffix.lower()
            if suffix not in {".jpg", ".jpeg", ".png", ".webp"}:
                suffix = ".jpg"
            reference = folder / ("sketchfab-reference" + suffix)
            try:
                _download_to_file(client, thumbnail_url, reference, MAX_REFERENCE_BYTES)
                record["reference_image_path"] = str(reference)
            except (requests.RequestException, AssetResolutionError):
                record["reference_image_error"] = "The provider preview could not be retrieved."

    if require_download and record["resolution"] != "downloaded_model":
        raise AssetResolutionError(str(record.get("reason") or "A real model download was required."))
    record["manifest_path"] = str(_write_manifest(folder, record))
    return record


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve a properly licensed Sketchfab model or prepare its Blender reference."
    )
    parser.add_argument("--model-url", default=os.environ.get("SKETCHFAB_MODEL_URL", DEFAULT_MODEL_URL))
    parser.add_argument("--output-dir", default="work/blender-assets/violin")
    parser.add_argument("--token-env", default="SKETCHFAB_ACCESS_TOKEN")
    parser.add_argument("--require-download", action="store_true")
    args = parser.parse_args()
    try:
        result = resolve_sketchfab_asset(
            args.model_url,
            args.output_dir,
            access_token=os.environ.get(args.token_env) or None,
            require_download=args.require_download,
        )
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            with open(github_output, "a", encoding="utf-8") as output:
                output.write("downloaded=" + str(result["resolution"] == "downloaded_model").lower() + "\n")
                output.write("model_path=" + str(result.get("local_model_path") or "") + "\n")
                output.write("manifest_path=" + str(result["manifest_path"]) + "\n")
                output.write("reference_path=" + str(result.get("reference_image_path") or "") + "\n")
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except Exception as exc:
        print("Blender asset resolution failed: " + str(exc)[:1000], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
