"""Discover, rank and acquire a story-specific licensed 3D asset.

This resolver never substitutes a thumbnail, preview image, or procedural stand-in.
It uses public Sketchfab model search and the official authenticated Download API.
Every selected file must pass licence, geometry-quality and archive validation.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import struct
import sys
from pathlib import Path
from typing import Any

import requests

from asset_resolver import (
    API_ROOT,
    AssetResolutionError,
    _license_details,
    fetch_model_metadata,
    model_uid_from_url,
    resolve_sketchfab_asset,
)

USER_AGENT = "ViolinPrinceAutopilot/2.0 (story-specific licensed 3D asset resolver)"
MIN_FACE_COUNT = 80_000
MAX_CANDIDATES = 24
DOWNLOAD_ATTEMPTS = 8
STOP_WORDS = {
    "a", "an", "and", "are", "as", "at", "by", "can", "does", "for",
    "from", "how", "in", "into", "is", "it", "its", "of", "on", "or",
    "the", "their", "this", "to", "what", "when", "why", "with", "within",
    "prince", "story", "explained", "short", "video", "music",
    "realistic", "detailed", "high", "quality", "model", "pbr", "3d",
}


class StoryAssetError(RuntimeError):
    """Raised when no genuine, commercially permitted 3D asset can be acquired."""


def _tokens(value: str) -> list[str]:
    output = []
    for token in re.findall(r"[a-z0-9]{3,}", str(value or "").casefold()):
        if token not in STOP_WORDS and token not in output:
            output.append(token)
    return output


def derive_story_query(plan: dict[str, Any]) -> str:
    """Derive a model search query from this story, not a fixed instrument."""
    if not isinstance(plan, dict):
        raise StoryAssetError("The story plan must be a JSON object.")
    explicit = str(
        plan.get("model_query") or plan.get("visual_asset_query")
        or plan.get("asset_subject") or ""
    ).strip()
    if explicit:
        subject_tokens = _tokens(explicit)
    else:
        sources = [
            plan.get("topic", ""),
            plan.get("core_claim", ""),
            plan.get("title", ""),
        ]
        for scene in plan.get("scenes", []) if isinstance(plan.get("scenes"), list) else []:
            if isinstance(scene, dict):
                sources.extend((
                    scene.get("graphic_label", ""),
                    scene.get("caption", ""),
                    scene.get("graphic_detail", ""),
                    scene.get("image_prompt", ""),
                ))
        subject_tokens = _tokens(" ".join(str(item or "") for item in sources))
    if not subject_tokens:
        raise StoryAssetError(
            "The plan does not identify a physical subject for 3D model discovery. "
            "Add model_query or a specific topic/title."
        )
    # A violin-performance asset must include genuine bow and string geometry.
    # These search terms are story-specific and are not applied to unrelated topics.
    if "violin" in subject_tokens:
        for required_part in ("bow", "strings"):
            if required_part not in subject_tokens:
                subject_tokens.append(required_part)
    # Keep search intent concrete. Search terms come from the story itself.
    subject = " ".join(subject_tokens[:9])
    return f"{subject} realistic detailed PBR 3D model"


def _model_uid(model: dict[str, Any]) -> str:
    return str(model.get("uid") or model.get("id") or "").strip()


def inspect_named_model_parts(model_path: str | Path) -> dict[str, list[str]]:
    """Read semantic mesh names from glTF/GLB nodes without rendering the model."""
    path = Path(model_path)
    payload = path.read_bytes()
    if path.suffix.casefold() == ".glb":
        if len(payload) < 20 or payload[:4] != b"glTF":
            raise StoryAssetError("The downloaded GLB has an invalid header.")
        offset = 12
        document = None
        while offset + 8 <= len(payload):
            chunk_size, chunk_type = struct.unpack_from("<II", payload, offset)
            offset += 8
            end = offset + chunk_size
            if end > len(payload):
                raise StoryAssetError("The downloaded GLB contains a truncated chunk.")
            if chunk_type == 0x4E4F534A:
                document = json.loads(payload[offset:end].decode("utf-8").rstrip(" \\t\\r\\n\\x00"))
                break
            offset = end
        if not isinstance(document, dict):
            raise StoryAssetError("The GLB does not contain a valid glTF JSON chunk.")
    else:
        try:
            document = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise StoryAssetError("The downloaded glTF document is invalid.") from exc

    nodes = document.get("nodes") or []
    meshes = document.get("meshes") or []
    scenes = document.get("scenes") or []
    result: dict[str, list[str]] = {"bow": [], "strings": [], "mesh_nodes": []}
    visited: set[int] = set()

    def walk(index: int, inherited_names: list[str]) -> None:
        if index in visited or not isinstance(index, int) or index < 0 or index >= len(nodes):
            return
        visited.add(index)
        node = nodes[index]
        if not isinstance(node, dict):
            return
        name = str(node.get("name") or f"node_{index}")
        chain = inherited_names + [name]
        tokens = set(re.findall(r"[a-z0-9]+", " ".join(chain).casefold()))
        has_bow = bool(tokens.intersection({"bow", "bowstick", "bowhair", "bowfrog", "horsehair"}))
        has_strings = any("string" in token for token in tokens)
        mesh_index = node.get("mesh")
        if isinstance(mesh_index, int) and 0 <= mesh_index < len(meshes):
            label = " / ".join(chain)
            result["mesh_nodes"].append(label)
            if has_bow:
                result["bow"].append(label)
            if has_strings:
                result["strings"].append(label)
        for child in node.get("children") or []:
            walk(child, chain)

    roots = []
    for scene in scenes:
        if isinstance(scene, dict):
            roots.extend(index for index in scene.get("nodes") or [] if isinstance(index, int))
    if not roots:
        child_indices = {
            child
            for node in nodes if isinstance(node, dict)
            for child in node.get("children") or [] if isinstance(child, int)
        }
        roots = [index for index in range(len(nodes)) if index not in child_indices]
    for index in roots:
        walk(index, [])
    for index in range(len(nodes)):
        walk(index, [])
    return result


def _face_count(model: dict[str, Any]) -> int:
    values = [model.get("faceCount", model.get("face_count", 0))]
    archives = model.get("archives") or {}
    if isinstance(archives, dict):
        for archive in archives.values():
            if isinstance(archive, dict):
                values.append(archive.get("faceCount", archive.get("face_count", 0)))
    for value in values:
        try:
            parsed = max(0, int(value or 0))
            if parsed:
                return parsed
        except (TypeError, ValueError):
            continue
    return 0


def _creator_name(model: dict[str, Any]) -> str:
    user = model.get("user") or {}
    if isinstance(user, dict):
        return str(user.get("username") or user.get("displayName") or "Unknown creator")
    return "Unknown creator"


def _license_allowed(model: dict[str, Any]) -> bool:
    code, label, _url = _license_details(model)
    blocked = any(
        term in (code + " " + label).casefold()
        for term in ("noncommercial", "non-commercial", "by-nc", "-nc", "editorial", "no-derivatives", "no-derivative", "-nd")
    )
    accepted = (
        code in {"cc0", "cc0-1-0", "cc0-1.0", "cc-by", "cc-by-4.0",
                 "cc-by-4-0", "by", "cc-attribution", "cc-attribution-4.0",
                 "cc-attribution-4-0"}
        or "cc0" in code
        or "cc-by-4-0" in code
        or "cc-attribution-4-0" in code
    )
    return not blocked and accepted


def _is_downloadable(model: dict[str, Any]) -> bool:
    value = model.get("isDownloadable", model.get("is_downloadable", False))
    return value is True or str(value).strip().casefold() in {"1", "true", "yes"}


def _likes(model: dict[str, Any]) -> int:
    try:
        return max(0, int(model.get("likeCount") or model.get("like_count") or 0))
    except (TypeError, ValueError):
        return 0


def _search_result_terms(model: dict[str, Any]) -> set[str]:
    parts = [str(model.get("name") or ""), str(model.get("description") or "")]
    tags = model.get("tags") or []
    for tag in tags:
        if isinstance(tag, dict):
            parts.append(str(tag.get("name") or ""))
        else:
            parts.append(str(tag))
    return set(_tokens(" ".join(parts)))


def score_candidate(model: dict[str, Any], query: str) -> float:
    """Prioritise topic match, substantial geometry, PBR and community vetting."""
    face_count = _face_count(model)
    if face_count < MIN_FACE_COUNT or not _license_allowed(model) or not _is_downloadable(model):
        return float("-inf")
    query_terms = set(_tokens(query))
    overlap = len(query_terms.intersection(_search_result_terms(model)))
    relevance = overlap / max(1, len(query_terms))
    geometry = min(1.0, max(0.0, (face_count - MIN_FACE_COUNT) / 400_000))
    pbr = str(model.get("pbr_type") or model.get("pbrType") or "").casefold() not in {"", "none", "false"}
    try:
        likes = max(0, int(model.get("likeCount") or model.get("like_count") or 0))
    except (TypeError, ValueError):
        likes = 0
    community = min(1.0, likes / 250.0)
    return 100.0 * relevance + 22.0 * geometry + (12.0 if pbr else 0.0) + 5.0 * community


def search_story_models(
    query: str,
    *,
    session: requests.Session | None = None,
    count: int = MAX_CANDIDATES,
) -> list[dict[str, Any]]:
    """Use the public Sketchfab Data API to discover this story's candidate models."""
    query = str(query or "").strip()
    if len(query) < 3:
        raise StoryAssetError("The story-specific model query is too short.")
    client = session or requests.Session()
    client.headers.update({"User-Agent": USER_AGENT, "Accept": "application/json"})
    try:
        response = client.get(
            f"{API_ROOT}/search",
            params={
                "type": "models",
                "q": query,
                "downloadable": "true",
                "count": max(1, min(int(count), MAX_CANDIDATES)),
                "sort_by": "-likeCount",
            },
            timeout=(15, 45),
        )
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise StoryAssetError("Sketchfab public model search failed: " + str(exc)[:400]) from exc
    rows = payload.get("results") if isinstance(payload, dict) else None
    if isinstance(rows, dict):
        rows = rows.get("models")
    if not isinstance(rows, list):
        raise StoryAssetError("Sketchfab returned an unexpected model-search response.")
    enriched = []
    # Search results can omit geometry fields. Fetch official public model
    # metadata for each candidate so the detail/licence gate uses real counts,
    # rather than guessing from a thumbnail or accepting an unknown value.
    for row in rows:
        if not isinstance(row, dict):
            continue
        details = row
        uid = _model_uid(row)
        if uid and not _face_count(row):
            try:
                metadata = fetch_model_metadata(uid, client)
                if isinstance(metadata, dict):
                    details = {**row, **metadata}
            except (requests.RequestException, AssetResolutionError, ValueError):
                # Keep the original result; the quality gate will reject if
                # geometry metadata remains unavailable.
                pass
        enriched.append(details)
    return enriched


def rank_story_models(models: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    ranked = []
    seen = set()
    for model in models:
        uid = _model_uid(model)
        score = score_candidate(model, query)
        if not uid or uid in seen or score == float("-inf"):
            continue
        seen.add(uid)
        ranked.append((score, model))
    ranked.sort(
        key=lambda item: (
            item[0],
            _face_count(item[1]),
            _likes(item[1]),
        ),
        reverse=True,
    )
    return [
        {**model, "violin_prince_asset_score": round(score, 3)}
        for score, model in ranked
    ]


def _preferred_model_entries(plan: dict[str, Any]) -> list[tuple[str, str]]:
    """Validate and preserve plan-ordered Sketchfab URLs selected for this story."""
    raw = plan.get("preferred_model_urls") or []
    if isinstance(raw, str):
        raw = [raw]
    if not isinstance(raw, list):
        raise StoryAssetError("preferred_model_urls must be a list of Sketchfab model URLs.")
    entries: list[tuple[str, str]] = []
    seen: set[str] = set()
    for value in raw:
        source_url = str(value or "").strip()
        if not source_url:
            continue
        try:
            uid = model_uid_from_url(source_url)
        except AssetResolutionError as exc:
            raise StoryAssetError("Invalid preferred Sketchfab model URL: " + source_url) from exc
        if uid not in seen:
            seen.add(uid)
            entries.append((source_url, uid))
    return entries


def load_preferred_story_models(
    plan: dict[str, Any],
    *,
    session: requests.Session | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    """Fetch public metadata for explicitly selected models before broad discovery."""
    client = session or requests.Session()
    loaded: list[dict[str, Any]] = []
    failures: list[dict[str, str]] = []
    for source_url, uid in _preferred_model_entries(plan):
        try:
            metadata = fetch_model_metadata(uid, client)
            if not isinstance(metadata, dict):
                raise StoryAssetError("Sketchfab returned invalid metadata for " + uid)
            loaded.append({
                **metadata,
                "uid": uid,
                "_violin_prince_source_url": source_url,
            })
        except (requests.RequestException, AssetResolutionError, ValueError, StoryAssetError) as exc:
            failures.append({
                "model_uid": uid,
                "source_url": source_url,
                "error": str(exc)[:400],
            })
    return loaded, failures


def resolve_story_asset(
    plan: dict[str, Any],
    output_dir: str | Path,
    *,
    access_token: str | None = None,
    session: requests.Session | None = None,
    min_face_count: int = MIN_FACE_COUNT,
    require_violin_parts: bool | None = None,
) -> dict[str, Any]:
    """Search, rank, download and verify one real model selected for a story."""
    token = str(access_token or os.environ.get("SKETCHFAB_ACCESS_TOKEN") or "").strip()
    if not token:
        raise StoryAssetError(
            "A real story-specific 3D model is required, but SKETCHFAB_ACCESS_TOKEN "
            "is not configured. Add a valid Sketchfab access token as a repository "
            "Actions secret. No reference image or placeholder model will be used."
        )
    query = derive_story_query(plan)
    if require_violin_parts is None:
        requested_kind = str(plan.get("asset_kind") or "").casefold()
        require_violin_parts = requested_kind in {"violin", "stringed_instrument"} or "violin" in _tokens(query)
    folder = Path(output_dir).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    client = session or requests.Session()
    preferred_entries = _preferred_model_entries(plan)
    preferred_models, preferred_errors = load_preferred_story_models(plan, session=client)

    search_error = ""
    try:
        discovered_models = search_story_models(query, session=client)
    except StoryAssetError as exc:
        # An explicitly selected valid model must remain usable even if broad
        # discovery is temporarily unavailable. Discovery is only a fallback.
        if not preferred_models:
            raise
        search_error = str(exc)[:500]
        discovered_models = []

    preferred_model_diagnostics = []
    minimum_faces = max(MIN_FACE_COUNT, int(min_face_count))
    for item in preferred_models:
        uid = _model_uid(item)
        face_count = _face_count(item)
        license_code, license_label, _license_url = _license_details(item)
        reasons = []
        if face_count < minimum_faces:
            reasons.append(f"face_count {face_count} is below {minimum_faces}")
        if not _license_allowed(item):
            reasons.append("licence is not CC0/CC-BY")
        if not _is_downloadable(item):
            reasons.append("model is not marked downloadable")
        preferred_model_diagnostics.append({
            "model_uid": uid,
            "model_name": str(item.get("name") or item.get("title") or "")[:160],
            "face_count": face_count,
            "vertex_count": item.get("vertexCount", item.get("vertex_count")),
            "downloadable": _is_downloadable(item),
            "license_code": license_code,
            "license_label": license_label,
            "pbr_type": item.get("pbrType", item.get("pbr_type")),
            "tags": [
                tag.get("name") if isinstance(tag, dict) else str(tag)
                for tag in (item.get("tags") or [])[:20]
            ],
            "eligible": not reasons,
            "rejection_reasons": reasons,
        })
    preferred_ranked = {
        _model_uid(item): item
        for item in rank_story_models(preferred_models, query)
    }
    preferred_uids = {uid for _url, uid in preferred_entries}
    ranked = [
        preferred_ranked[uid]
        for _url, uid in preferred_entries
        if uid in preferred_ranked
    ]
    ranked.extend(
        item for item in rank_story_models(discovered_models, query)
        if _model_uid(item) not in preferred_uids
    )
    ranked = [
        item for item in ranked
        if _face_count(item) >= max(MIN_FACE_COUNT, int(min_face_count))
    ]
    if not ranked:
        diagnostic = {
            "query": query,
            "preferred_model_urls": [url for url, _uid in preferred_entries],
            "preferred_model_errors": preferred_errors,
            "preferred_model_diagnostics": preferred_model_diagnostics,
            "search_error": search_error,
            "ranked_candidates": 0,
            "reference_fallback": False,
        }
        raise StoryAssetError(
            "No explicitly selected or discovered model met the licence, download and "
            f"{max(MIN_FACE_COUNT, int(min_face_count)):,}-face quality gates for query: {query!r}. "
            "The render remains blocked; no preview image or low-detail substitute will be used. "
            "Selection diagnostics: " + json.dumps(diagnostic, ensure_ascii=False)[:1200]
        )

    failures = []
    for candidate in ranked[:DOWNLOAD_ATTEMPTS]:
        uid = _model_uid(candidate)
        candidate_dir = folder / uid
        try:
            source_url = str(
                candidate.get("_violin_prince_source_url")
                or candidate.get("viewerUrl")
                or candidate.get("url")
                or f"https://sketchfab.com/models/{uid}"
            )
            record = resolve_sketchfab_asset(
                source_url,
                candidate_dir,
                access_token=token,
                session=client,
                require_download=True,
            )
            model_path = Path(str(record.get("local_model_path") or ""))
            if not model_path.is_file() or model_path.suffix.casefold() not in {".glb", ".gltf"}:
                raise StoryAssetError("Official download did not produce a usable glTF/GLB model.")
            if model_path.stat().st_size < 4096:
                raise StoryAssetError("The downloaded 3D model is unexpectedly small.")
            if model_path.suffix.casefold() == ".glb" and model_path.read_bytes()[:4] != b"glTF":
                raise StoryAssetError("The GLB file header failed validation.")
            model_parts = inspect_named_model_parts(model_path)
            if require_violin_parts and (not model_parts["bow"] or not model_parts["strings"]):
                raise StoryAssetError(
                    "The imported violin candidate failed the separate-part gate: "
                    + f"bow_nodes={len(model_parts['bow'])}, "
                    + f"string_nodes={len(model_parts['strings'])}, "
                    + "mesh_nodes=" + json.dumps(model_parts.get("mesh_nodes", [])[:80], ensure_ascii=False)
                    + ". No synthetic bow or unverified strings will be added."
                )
            manifest_path = Path(str(record["manifest_path"]))
            record.update({
                "model_parts": model_parts,
                "source_url": source_url,
                "bow_rig_required": bool(require_violin_parts),
                "selection_query": query,
                "selection_score": candidate["violin_prince_asset_score"],
                "face_count": _face_count(candidate),
                "vertex_count": candidate.get("vertexCount"),
                "like_count": candidate.get("likeCount"),
                "pbr_type": candidate.get("pbr_type"),
                "creator": _creator_name(candidate),
                "candidate_count": len(ranked),
                "asset_selection_policy": (
                    "story-specific public model search; CC0/CC-BY only; "
                    "downloadable; minimum geometry gate; highest ranked viable official download"
                ),
            })
            manifest_path.write_text(
                json.dumps(record, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            return record
        except Exception as exc:
            license_code, license_label, _license_url = _license_details(candidate)
            failures.append({
                "model_uid": uid,
                "model_name": str(candidate.get("name") or "")[:120],
                "face_count": _face_count(candidate),
                "vertex_count": candidate.get("vertexCount", candidate.get("vertex_count")),
                "is_downloadable": _is_downloadable(candidate),
                "license_code": license_code,
                "license_label": license_label,
                "error": str(exc)[:3500],
            })
    diagnostic = folder / "asset-resolution-diagnostic.json"
    diagnostic.write_text(
        json.dumps({
            "query": query,
            "preferred_model_urls": [url for url, _uid in preferred_entries],
            "preferred_model_errors": preferred_errors,
            "preferred_model_diagnostics": preferred_model_diagnostics,
            "search_error": search_error,
            "ranked_candidates": len(ranked),
            "attempted": failures,
            "reference_fallback": False,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    raise StoryAssetError(
        "No candidate model could be downloaded and verified through the official "
        "Sketchfab Download API. Diagnostic: " + str(diagnostic) + " — "
        + json.dumps({
            "preferred_model_errors": preferred_errors,
            "preferred_model_diagnostics": preferred_model_diagnostics,
            "search_error": search_error,
            "candidate_failures": failures,
        }, ensure_ascii=False)[:7500]
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", help="Story plan JSON from the daily producer.")
    parser.add_argument("--query", help="Explicit subject query for a controlled proof.")
    parser.add_argument("--output-dir", default="work/story-assets")
    parser.add_argument("--token-env", default="SKETCHFAB_ACCESS_TOKEN")
    parser.add_argument("--min-face-count", type=int, default=MIN_FACE_COUNT)
    args = parser.parse_args()
    try:
        plan = json.loads(Path(args.plan).read_text(encoding="utf-8")) if args.plan else {}
        if args.query:
            plan["model_query"] = args.query
        result = resolve_story_asset(
            plan,
            args.output_dir,
            access_token=os.environ.get(args.token_env),
            min_face_count=args.min_face_count,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        github_output = os.environ.get("GITHUB_OUTPUT")
        if github_output:
            with open(github_output, "a", encoding="utf-8") as output:
                output.write("model_path=" + str(result["local_model_path"]) + "\n")
                output.write("manifest_path=" + str(result["manifest_path"]) + "\n")
                output.write("model_uid=" + str(result["model_uid"]) + "\n")
        return 0
    except Exception as exc:
        print("Story-specific asset resolution failed: " + str(exc)[:1800], file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
