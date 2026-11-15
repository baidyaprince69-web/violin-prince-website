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
import sys
from pathlib import Path
from typing import Any

import requests

from asset_resolver import (
    API_ROOT,
    AssetResolutionError,
    _license_details,
    resolve_sketchfab_asset,
)

USER_AGENT = "ViolinPrinceAutopilot/2.0 (story-specific licensed 3D asset resolver)"
MIN_FACE_COUNT = 25_000
MAX_CANDIDATES = 100
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
    # Keep search intent concrete. Search terms come from the story itself.
    subject = " ".join(subject_tokens[:7])
    return f"{subject} realistic detailed PBR 3D model"


def _model_uid(model: dict[str, Any]) -> str:
    return str(model.get("uid") or model.get("id") or "").strip()


def _face_count(model: dict[str, Any]) -> int:
    value = model.get("faceCount", model.get("face_count", 0))
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
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
    return not blocked and code in {
        "cc0", "cc0-1-0", "cc0-1.0", "cc-by", "cc-by-4.0",
        "cc-by-4-0", "by", "cc-attribution", "cc-attribution-4.0",
        "cc-attribution-4-0",
    }


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
    pbr = str(model.get("pbr_type") or "").casefold() not in {"", "none", "false"}
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
    if not isinstance(rows, list):
        raise StoryAssetError("Sketchfab returned an unexpected model-search response.")
    return [row for row in rows if isinstance(row, dict)]


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


def resolve_story_asset(
    plan: dict[str, Any],
    output_dir: str | Path,
    *,
    access_token: str | None = None,
    session: requests.Session | None = None,
    min_face_count: int = MIN_FACE_COUNT,
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
    folder = Path(output_dir).expanduser().resolve()
    folder.mkdir(parents=True, exist_ok=True)
    models = search_story_models(query, session=session)
    ranked = rank_story_models(models, query)
    ranked = [item for item in ranked if _face_count(item) >= max(MIN_FACE_COUNT, int(min_face_count))]
    if not ranked:
        raise StoryAssetError(
            "No downloadable, commercially permitted model met the story relevance "
            f"and {max(MIN_FACE_COUNT, int(min_face_count)):,}-face quality gate for query: {query!r}. "
            "The render is blocked rather than using a thumbnail or low-detail substitute."
        )

    failures = []
    for candidate in ranked[:DOWNLOAD_ATTEMPTS]:
        uid = _model_uid(candidate)
        candidate_dir = folder / uid
        try:
            record = resolve_sketchfab_asset(
                uid,
                candidate_dir,
                access_token=token,
                session=session,
                require_download=True,
            )
            model_path = Path(str(record.get("local_model_path") or ""))
            if not model_path.is_file() or model_path.suffix.casefold() not in {".glb", ".gltf"}:
                raise StoryAssetError("Official download did not produce a usable glTF/GLB model.")
            if model_path.stat().st_size < 4096:
                raise StoryAssetError("The downloaded 3D model is unexpectedly small.")
            if model_path.suffix.casefold() == ".glb" and model_path.read_bytes()[:4] != b"glTF":
                raise StoryAssetError("The GLB file header failed validation.")
            manifest_path = Path(str(record["manifest_path"]))
            record.update({
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
            failures.append({
                "model_uid": uid,
                "model_name": str(candidate.get("name") or "")[:120],
                "error": str(exc)[:500],
            })
    diagnostic = folder / "asset-resolution-diagnostic.json"
    diagnostic.write_text(
        json.dumps({
            "query": query,
            "ranked_candidates": len(ranked),
            "attempted": failures,
            "reference_fallback": False,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    raise StoryAssetError(
        "No candidate model could be downloaded and verified through the official "
        "Sketchfab Download API. Diagnostic: " + str(diagnostic) + " — "
        + json.dumps(failures, ensure_ascii=False)[:1500]
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
