"""Native YouTube publishing engine for Violin Prince Autopilot.

The module is safe by default: no upload or visibility change occurs unless the
corresponding explicit environment gates are enabled. Resumable session URLs are
stored only inside an AES-GCM encrypted checkpoint.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from statistics import median
from typing import Any

import requests
from cryptography.hazmat.primitives.ciphers.aead import AESGCM


API_ROOT = "https://www.googleapis.com/youtube/v3"
UPLOAD_ROOT = "https://www.googleapis.com/upload/youtube/v3/videos"
TOKEN_URL = "https://oauth2.googleapis.com/token"
USER_AGENT = "ViolinPrinceAutopilot/Phase4"
ALLOWED_PRIVACY = {"private", "unlisted", "public"}
MAX_TITLE_CHARS = 100
MAX_DESCRIPTION_BYTES = 5000
MAX_TAGS_CHARS = 500
MAX_HASHTAGS = 60
DEFAULT_CHUNK_SIZE = 8 * 1024 * 1024  # 8 MiB; a multiple of YouTube's 256 KiB chunk unit.


class YouTubeEngineError(RuntimeError):
    """Base error for YouTube engine failures."""


class PublishingDisabled(YouTubeEngineError):
    """Raised when a live action is attempted while its safety gate is off."""


class MetadataError(YouTubeEngineError):
    """Raised when metadata is incomplete, misleadingly formed, or too long."""


class UploadSessionExpired(YouTubeEngineError):
    """Raised when YouTube no longer accepts the saved resumable session."""


class CheckpointError(YouTubeEngineError):
    """Raised when encrypted upload state is unavailable or cannot be trusted."""


def _enabled(env: dict[str, str], key: str) -> bool:
    return str(env.get(key, "false")).strip().lower() in {"1", "true", "yes", "on"}


def _normalise_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        values = re.split(r"[,\n]", value)
    elif isinstance(value, (tuple, list)):
        values = list(value)
    else:
        raise MetadataError("Expected a list of strings for tags or hashtags.")
    result: list[str] = []
    for item in values:
        text = re.sub(r"\s+", " ", str(item)).strip()
        if text and text not in result:
            result.append(text)
    return result


def _normalise_hashtags(value: Any) -> list[str]:
    tags = _normalise_list(value)
    result: list[str] = []
    seen: set[str] = set()
    for tag in tags:
        token = tag.lstrip("#").replace(" ", "")
        token = re.sub(r"[^\w]", "", token, flags=re.UNICODE)
        if not token:
            continue
        normalised = "#" + token
        if normalised.casefold() not in seen:
            result.append(normalised)
            seen.add(normalised.casefold())
    if len(result) > MAX_HASHTAGS:
        raise MetadataError("YouTube ignores all hashtags when a video has more than 60.")
    if len(result) > 3:
        raise MetadataError("Keep the approved hashtag set to three precise hashtags or fewer.")
    return result


def _validate_text(value: str, field: str) -> None:
    if not value.strip():
        raise MetadataError(f"{field} cannot be empty.")
    if "<" in value or ">" in value:
        raise MetadataError(f"{field} contains a character not accepted by the YouTube API.")
    if any(ord(ch) < 32 and ch not in "\n\t\r" for ch in value):
        raise MetadataError(f"{field} contains unsupported control characters.")


def _title_candidates(primary_keyword: str, title: str, hook: str) -> list[str]:
    candidates = [title]
    if primary_keyword and hook:
        candidates.extend([
            f"{primary_keyword}: {hook}",
            f"{hook} | {primary_keyword}",
        ])
    result: list[str] = []
    for candidate in candidates:
        value = re.sub(r"\s+", " ", candidate).strip()
        if value and len(value) <= MAX_TITLE_CHARS and value not in result:
            result.append(value)
    return result


def build_metadata(
    plan: dict[str, Any],
    *,
    privacy_status: str = "private",
    allow_public: bool = False,
) -> dict[str, Any]:
    """Create an API-ready metadata payload and a separate review/audit block.

    Keyword tags and hashtags are deliberately separate. Hashtags are placed in
    the description, while snippet.tags contains only ordinary descriptive tags.
    """
    if not isinstance(plan, dict):
        raise MetadataError("Creative plan must be a JSON object.")

    title = str(plan.get("seo_title") or plan.get("title") or "").strip()
    topic = str(plan.get("topic") or "").strip()
    hook = str(plan.get("hook") or "").strip()
    primary = str(plan.get("primary_keyword") or topic or title).strip()
    if not title:
        title = primary
    _validate_text(title, "Title")
    if len(title) > MAX_TITLE_CHARS:
        raise MetadataError(f"Title is {len(title)} characters; the limit is 100. Do not silently truncate it.")

    description = str(plan.get("seo_description") or plan.get("description") or "").strip()
    if not description:
        if not topic:
            raise MetadataError("Add a topic or a reviewed description before preparing metadata.")
        description = topic + (("\n\n" + hook) if hook else "")

    sources = plan.get("sources") or []
    if isinstance(sources, str):
        sources = [sources]
    source_values = []
    for source in sources:
        if isinstance(source, dict):
            source = source.get("url") or source.get("source_url") or ""
        source = str(source).strip()
        if source.startswith(("https://", "http://")) and source not in source_values:
            source_values.append(source)
    if source_values and plan.get("include_sources_in_description", True):
        description += "\n\nSources:\n" + "\n".join(source_values[:5])

    hashtags = _normalise_hashtags(plan.get("seo_hashtags", plan.get("hashtags", [])))
    if hashtags:
        already_present = {x.casefold() for x in re.findall(r"#[\w]+", description, flags=re.UNICODE)}
        missing = [x for x in hashtags if x.casefold() not in already_present]
        if missing:
            description = description.rstrip() + "\n\n" + " ".join(missing)

    _validate_text(description, "Description")
    description_bytes = len(description.encode("utf-8"))
    if description_bytes > MAX_DESCRIPTION_BYTES:
        raise MetadataError(
            f"Description is {description_bytes} UTF-8 bytes; the API limit is 5,000 bytes."
        )

    tags = _normalise_list(plan.get("seo_tags", plan.get("tags", [])))
    tags = [tag.lstrip("#").strip() for tag in tags if tag.strip()]
    tags = list(dict.fromkeys(tags))
    tag_char_count = len(",".join(tags))
    if tag_char_count > MAX_TAGS_CHARS:
        raise MetadataError(
            f"Keyword tags use {tag_char_count} characters; the API limit is 500 including separators."
        )

    if privacy_status not in ALLOWED_PRIVACY:
        raise MetadataError("Privacy must be private, unlisted, or public.")
    if privacy_status == "public" and not allow_public:
        raise PublishingDisabled("Public visibility is blocked until a separate publication approval is enabled.")

    category_id = str(plan.get("youtube_category_id") or "").strip()
    language = str(plan.get("language") or plan.get("default_language") or "en").strip() or "en"
    status: dict[str, Any] = {"privacyStatus": privacy_status}

    made_for_kids = plan.get("made_for_kids")
    if isinstance(made_for_kids, bool):
        status["selfDeclaredMadeForKids"] = made_for_kids

    synthetic = plan.get("contains_synthetic_media")
    if synthetic is None:
        synthetic = plan.get("containsSyntheticMedia")
    if isinstance(synthetic, bool):
        status["containsSyntheticMedia"] = synthetic

    publish_at = str(plan.get("publish_at") or "").strip()
    if publish_at:
        try:
            scheduled = datetime.fromisoformat(publish_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise MetadataError("publish_at must be a valid ISO-8601 datetime with a timezone.") from exc
        if scheduled.tzinfo is None:
            raise MetadataError("publish_at must include a timezone.")
        if scheduled <= datetime.now(timezone.utc):
            raise MetadataError("publish_at must be a future datetime.")
        if privacy_status != "private":
            raise MetadataError("YouTube scheduling requires privacyStatus=private.")
        status["publishAt"] = scheduled.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")

    snippet: dict[str, Any] = {
        "title": title,
        "description": description,
        "tags": tags,
        "defaultLanguage": language,
    }
    if category_id:
        if not category_id.isdigit():
            raise MetadataError("youtube_category_id must be a numeric YouTube category ID.")
        snippet["categoryId"] = category_id

    audit = {
        "primary_keyword": primary,
        "title_candidates_for_review": _title_candidates(primary, title, hook),
        "title_characters": len(title),
        "description_utf8_bytes": description_bytes,
        "tag_characters_including_separators": tag_char_count,
        "hashtags": hashtags,
        "hashtag_count": len(hashtags),
        "metadata_approved": plan.get("seo_metadata_approved") is True,
        "made_for_kids_decision_present": isinstance(made_for_kids, bool),
        "synthetic_media_decision_present": isinstance(synthetic, bool),
        "privacy_status": privacy_status,
        "search_volume_claim": None,
        "search_volume_note": "YouTube Data API search results do not provide keyword search-volume figures.",
    }
    return {"body": {"snippet": snippet, "status": status}, "audit": audit}


def research_keywords(
    candidates: list[str],
    *,
    api_key: str,
    session: requests.Session | None = None,
    region_code: str = "IN",
    language: str = "en",
    max_results: int = 10,
) -> dict[str, Any]:
    """Sample YouTube search results and public video stats for up to five phrases.

    This reports observed result samples and median views-per-day. It does not
    invent search volume or claim that public result counts equal search demand.
    """
    if not api_key:
        raise YouTubeEngineError("YOUTUBE_API_KEY is required for live keyword research.")
    phrases = list(dict.fromkeys(re.sub(r"\s+", " ", str(x)).strip() for x in candidates if str(x).strip()))
    phrases = phrases[:5]
    if not phrases:
        raise YouTubeEngineError("Provide at least one concrete keyword phrase to research.")
    client = session or requests.Session()
    client.headers.update({"User-Agent": USER_AGENT})
    sampled: list[dict[str, Any]] = []
    now = datetime.now(timezone.utc)

    for phrase in phrases:
        search_response = client.get(
            API_ROOT + "/search",
            params={
                "part": "snippet",
                "type": "video",
                "q": phrase,
                "regionCode": region_code,
                "relevanceLanguage": language,
                "safeSearch": "strict",
                "order": "relevance",
                "maxResults": max(1, min(int(max_results), 50)),
                "key": api_key,
            },
            timeout=30,
        )
        search_response.raise_for_status()
        search_items = search_response.json().get("items", [])
        video_ids = [
            item.get("id", {}).get("videoId")
            for item in search_items
            if item.get("id", {}).get("videoId")
        ]
        stats_by_id: dict[str, dict[str, Any]] = {}
        if video_ids:
            stats_response = client.get(
                API_ROOT + "/videos",
                params={
                    "part": "snippet,statistics",
                    "id": ",".join(video_ids[:50]),
                    "key": api_key,
                },
                timeout=30,
            )
            stats_response.raise_for_status()
            stats_by_id = {x.get("id"): x for x in stats_response.json().get("items", [])}

        results = []
        views_per_day = []
        views = []
        for item in search_items:
            video_id = item.get("id", {}).get("videoId")
            video = stats_by_id.get(video_id, {})
            snippet = video.get("snippet") or item.get("snippet") or {}
            statistics = video.get("statistics") or {}
            try:
                view_count = int(statistics.get("viewCount", 0))
            except (TypeError, ValueError):
                view_count = 0
            published = snippet.get("publishedAt")
            per_day = None
            if published and view_count:
                try:
                    published_at = datetime.fromisoformat(published.replace("Z", "+00:00"))
                    age_days = max((now - published_at).total_seconds() / 86400, 1.0)
                    per_day = round(view_count / age_days, 2)
                    views_per_day.append(per_day)
                except (ValueError, TypeError):
                    per_day = None
            if view_count:
                views.append(view_count)
            results.append({
                "video_id": video_id,
                "title": snippet.get("title", ""),
                "channel_title": snippet.get("channelTitle", ""),
                "published_at": published,
                "view_count": view_count,
                "views_per_day_estimate": per_day,
            })

        sampled.append({
            "query": phrase,
            "results_returned": len(search_items),
            "videos_with_public_view_counts": len(views),
            "median_views": int(median(views)) if views else None,
            "median_views_per_day_estimate": round(median(views_per_day), 2) if views_per_day else None,
            "top_results": results[:10],
        })

    return {
        "region_code": region_code,
        "language_hint": language,
        "queries_sampled": len(sampled),
        "search_volume": None,
        "search_volume_note": "Not exposed by YouTube Data API; result samples are not search-volume measurements.",
        "candidates": sampled,
    }


class EncryptedCheckpointStore:
    """AES-256-GCM encrypted state file; upload session URLs never sit in plaintext artifacts."""

    def __init__(self, path: str | Path, key_b64: str):
        self.path = Path(path)
        try:
            self.key = base64.urlsafe_b64decode(key_b64.encode("ascii"))
        except Exception as exc:
            raise CheckpointError("YOUTUBE_STATE_ENCRYPTION_KEY must be URL-safe base64 for 32 random bytes.") from exc
        if len(self.key) != 32:
            raise CheckpointError("YOUTUBE_STATE_ENCRYPTION_KEY must decode to exactly 32 bytes.")

    def load(self) -> dict[str, Any]:
        if not self.path.exists():
            return {"version": 1, "releases": {}}
        try:
            envelope = json.loads(self.path.read_text(encoding="utf-8"))
            nonce = base64.b64decode(envelope["nonce"])
            ciphertext = base64.b64decode(envelope["ciphertext"])
            plaintext = AESGCM(self.key).decrypt(nonce, ciphertext, b"violin-prince-youtube-state-v1")
            state = json.loads(plaintext.decode("utf-8"))
            if state.get("version") != 1 or not isinstance(state.get("releases"), dict):
                raise ValueError("Unsupported upload-state schema.")
            return state
        except Exception as exc:
            raise CheckpointError("Encrypted YouTube checkpoint is corrupt or the encryption key is incorrect.") from exc

    def save(self, state: dict[str, Any]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        nonce = os.urandom(12)
        plaintext = json.dumps(state, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ciphertext = AESGCM(self.key).encrypt(nonce, plaintext, b"violin-prince-youtube-state-v1")
        envelope = {
            "version": 1,
            "nonce": base64.b64encode(nonce).decode("ascii"),
            "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
        }
        temporary = self.path.with_suffix(self.path.suffix + ".tmp")
        temporary.write_text(json.dumps(envelope), encoding="utf-8")
        os.replace(temporary, self.path)


class YouTubeNativeClient:
    """OAuth-backed YouTube API client with encrypted resumable-upload recovery."""

    def __init__(
        self,
        *,
        env: dict[str, str] | None = None,
        session: requests.Session | None = None,
        sleep=time.sleep,
        chunk_size: int = DEFAULT_CHUNK_SIZE,
    ):
        self.env = dict(os.environ if env is None else env)
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": USER_AGENT})
        self.sleep = sleep
        if chunk_size < 256 * 1024 or chunk_size % (256 * 1024):
            raise ValueError("chunk_size must be a positive multiple of 256 KiB.")
        self.chunk_size = chunk_size

    def _required(self, key: str) -> str:
        value = str(self.env.get(key, "")).strip()
        if not value:
            raise YouTubeEngineError("Missing required GitHub secret or variable: " + key)
        return value

    def refresh_access_token(self) -> str:
        response = self.session.post(
            TOKEN_URL,
            data={
                "client_id": self._required("YOUTUBE_CLIENT_ID"),
                "client_secret": self._required("YOUTUBE_CLIENT_SECRET"),
                "refresh_token": self._required("YOUTUBE_REFRESH_TOKEN"),
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        response.raise_for_status()
        token = response.json().get("access_token")
        if not token:
            raise YouTubeEngineError("Google OAuth refresh returned no access token.")
        return token

    @staticmethod
    def _auth(access_token: str) -> dict[str, str]:
        return {"Authorization": "Bearer " + access_token}

    def verify_target_channel(self, access_token: str) -> str:
        expected = self._required("YOUTUBE_EXPECTED_CHANNEL_ID")
        response = self.session.get(
            API_ROOT + "/channels",
            params={"part": "snippet", "mine": "true"},
            headers=self._auth(access_token),
            timeout=30,
        )
        response.raise_for_status()
        channels = response.json().get("items", [])
        matching = [x for x in channels if x.get("id") == expected]
        if not matching:
            raise YouTubeEngineError(
                "The authorized Google account did not return the configured target channel ID. "
                "No upload was started."
            )
        return expected

    def _store(self) -> EncryptedCheckpointStore:
        key = self._required("YOUTUBE_STATE_ENCRYPTION_KEY")
        path = self.env.get("YOUTUBE_UPLOAD_STATE_PATH", "work/youtube-upload-state.enc")
        return EncryptedCheckpointStore(path, key)

    @staticmethod
    def _file_sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as source:
            for block in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(block)
        return digest.hexdigest()

    @staticmethod
    def _offset_from_range(value: str | None) -> int:
        if not value:
            return 0
        match = re.search(r"bytes=0-(\d+)", value)
        if not match:
            raise YouTubeEngineError("YouTube returned an unrecognised resumable-upload Range header.")
        return int(match.group(1)) + 1

    @staticmethod
    def _video_id(response: requests.Response) -> str:
        try:
            video_id = response.json().get("id")
        except Exception as exc:
            raise YouTubeEngineError("YouTube completed the upload without a readable video ID.") from exc
        if not video_id:
            raise YouTubeEngineError("YouTube completed the upload without a video ID.")
        return str(video_id)

    def _check_session(self, upload_url: str, access_token: str, size: int) -> tuple[int, str | None]:
        response = self.session.put(
            upload_url,
            headers={
                **self._auth(access_token),
                "Content-Length": "0",
                "Content-Range": f"bytes */{size}",
            },
            data=b"",
            timeout=60,
        )
        if response.status_code == 308:
            return self._offset_from_range(response.headers.get("Range")), None
        if response.status_code in (200, 201):
            return size, self._video_id(response)
        if response.status_code == 404:
            raise UploadSessionExpired(
                "The saved YouTube upload session expired. The engine stopped instead of creating a possible duplicate."
            )
        response.raise_for_status()
        raise YouTubeEngineError(f"Unexpected upload-session status response: {response.status_code}")

    def upload_video(
        self,
        video_path: str | Path,
        plan: dict[str, Any],
        *,
        release_id: str,
    ) -> dict[str, Any]:
        if not _enabled(self.env, "PUBLISH_ENABLED"):
            raise PublishingDisabled("PUBLISH_ENABLED is false; no YouTube API request was made.")
        if not _enabled(self.env, "YOUTUBE_UPLOAD_APPROVED"):
            raise PublishingDisabled("YOUTUBE_UPLOAD_APPROVED is false; owner approval is required before upload.")
        if plan.get("seo_metadata_approved") is not True:
            raise MetadataError("The SEO title, description, tags and hashtags have not been approved.")
        if not isinstance(plan.get("made_for_kids"), bool):
            raise MetadataError("The made-for-kids setting must be explicitly reviewed as true or false.")
        synthetic = plan.get("contains_synthetic_media", plan.get("containsSyntheticMedia"))
        if not isinstance(synthetic, bool):
            raise MetadataError("The altered/synthetic-media disclosure decision must be explicitly reviewed.")
        privacy = str(self.env.get("YOUTUBE_PRIVACY_STATUS", "private")).strip().lower()
        allow_public = _enabled(self.env, "YOUTUBE_PUBLICATION_APPROVED")
        metadata = build_metadata(plan, privacy_status=privacy, allow_public=allow_public)

        path = Path(video_path)
        if not path.is_file() or path.stat().st_size <= 0:
            raise YouTubeEngineError("The approved MP4 is missing or empty.")
        release_id = str(release_id).strip()
        if not release_id:
            raise YouTubeEngineError("A Phase 3 release ID is required for duplicate protection.")

        access_token = self.refresh_access_token()
        channel_id = self.verify_target_channel(access_token)
        file_size = path.stat().st_size
        file_sha = self._file_sha256(path)
        metadata_sha = hashlib.sha256(
            json.dumps(metadata["body"], sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        store = self._store()
        state = store.load()
        record = state["releases"].get(release_id)

        if record:
            if record.get("file_sha256") != file_sha or record.get("metadata_sha256") != metadata_sha:
                raise YouTubeEngineError("This Phase 3 release ID is already bound to a different MP4 or metadata.")
            if record.get("video_id"):
                return {
                    "platform": "youtube",
                    "video_id": record["video_id"],
                    "url": "https://www.youtube.com/watch?v=" + record["video_id"],
                    "already_uploaded": True,
                    "processing": self.get_video_status(record["video_id"], access_token),
                }
        else:
            record = {
                "release_id": release_id,
                "channel_id": channel_id,
                "file_sha256": file_sha,
                "metadata_sha256": metadata_sha,
                "file_size": file_size,
                "upload_url": None,
                "next_offset": 0,
                "video_id": None,
                "state": "prepared",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            state["releases"][release_id] = record
            store.save(state)

        upload_url = record.get("upload_url")
        offset = int(record.get("next_offset", 0))
        video_id = None
        if upload_url:
            offset, video_id = self._check_session(upload_url, access_token, file_size)

        if not upload_url:
            init = self.session.post(
                UPLOAD_ROOT,
                params={"uploadType": "resumable", "part": "snippet,status"},
                headers={
                    **self._auth(access_token),
                    "Content-Type": "application/json; charset=UTF-8",
                    "X-Upload-Content-Length": str(file_size),
                    "X-Upload-Content-Type": "video/mp4",
                },
                json=metadata["body"],
                timeout=60,
            )
            init.raise_for_status()
            upload_url = init.headers.get("Location")
            if not upload_url:
                raise YouTubeEngineError("YouTube did not return a resumable session URI.")
            record.update({"upload_url": upload_url, "next_offset": 0, "state": "uploading"})
            store.save(state)
            offset = 0

        retries = 0
        with path.open("rb") as source:
            while video_id is None and offset < file_size:
                source.seek(offset)
                chunk = source.read(min(self.chunk_size, file_size - offset))
                if not chunk:
                    raise YouTubeEngineError("Could not read the next MP4 upload chunk.")
                end = offset + len(chunk) - 1
                try:
                    response = self.session.put(
                        upload_url,
                        headers={
                            **self._auth(access_token),
                            "Content-Type": "video/mp4",
                            "Content-Length": str(len(chunk)),
                            "Content-Range": f"bytes {offset}-{end}/{file_size}",
                        },
                        data=chunk,
                        timeout=180,
                    )
                except requests.RequestException:
                    offset, video_id = self._check_session(upload_url, access_token, file_size)
                    if video_id:
                        break
                    retries += 1
                    if retries > 5:
                        raise YouTubeEngineError("Upload interrupted repeatedly; encrypted recovery state was saved.")
                    record.update({"next_offset": offset, "state": "uploading"})
                    store.save(state)
                    self.sleep(min(2 ** retries, 30))
                    continue

                if response.status_code == 308:
                    new_offset = self._offset_from_range(response.headers.get("Range"))
                    if new_offset <= offset:
                        retries += 1
                        if retries > 5:
                            raise YouTubeEngineError("YouTube made no upload progress after five attempts.")
                        self.sleep(min(2 ** retries, 30))
                    else:
                        offset = new_offset
                        retries = 0
                    record.update({"next_offset": offset, "state": "uploading"})
                    store.save(state)
                    continue

                if response.status_code in (200, 201):
                    video_id = self._video_id(response)
                    break

                if response.status_code == 404:
                    raise UploadSessionExpired(
                        "The upload session expired. The engine preserved the checkpoint and did not create a replacement."
                    )
                if response.status_code in (408, 429, 500, 502, 503, 504):
                    offset, video_id = self._check_session(upload_url, access_token, file_size)
                    retries += 1
                    if not video_id and retries <= 5:
                        record.update({"next_offset": offset, "state": "uploading"})
                        store.save(state)
                        self.sleep(min(2 ** retries, 30))
                        continue
                    if not video_id:
                        raise YouTubeEngineError("YouTube upload service remained unavailable after retries.")
                    break
                response.raise_for_status()
                raise YouTubeEngineError(f"Unexpected upload response: {response.status_code}")

        if not video_id:
            offset, video_id = self._check_session(upload_url, access_token, file_size)
        if not video_id:
            raise YouTubeEngineError("The upload did not reach a confirmed completion response.")

        record.update({
            "video_id": video_id,
            "next_offset": file_size,
            "state": "uploaded",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        })
        store.save(state)
        return {
            "platform": "youtube",
            "video_id": video_id,
            "url": "https://www.youtube.com/watch?v=" + video_id,
            "already_uploaded": False,
            "processing": None,
        }

    def get_video_status(self, video_id: str, access_token: str | None = None) -> dict[str, Any]:
        token = access_token or self.refresh_access_token()
        response = self.session.get(
            API_ROOT + "/videos",
            params={"part": "status,processingDetails,snippet", "id": video_id},
            headers=self._auth(token),
            timeout=30,
        )
        response.raise_for_status()
        items = response.json().get("items", [])
        if not items:
            raise YouTubeEngineError("YouTube did not return the uploaded video for status verification.")
        item = items[0]
        return {
            "video_id": item.get("id", video_id),
            "title": (item.get("snippet") or {}).get("title"),
            "privacy_status": (item.get("status") or {}).get("privacyStatus"),
            "upload_status": (item.get("status") or {}).get("uploadStatus"),
            "processing_status": (item.get("processingDetails") or {}).get("processingStatus"),
            "processing_failure_reason": (item.get("processingDetails") or {}).get("processingFailureReason"),
        }

    def wait_for_processing(
        self,
        video_id: str,
        *,
        timeout_seconds: int = 3600,
        interval_seconds: int = 30,
    ) -> dict[str, Any]:
        access_token = self.refresh_access_token()
        deadline = time.monotonic() + timeout_seconds
        while True:
            status = self.get_video_status(video_id, access_token)
            processing = status.get("processing_status")
            upload = status.get("upload_status")
            if processing == "succeeded" or upload == "processed":
                return status
            if processing in {"failed", "terminated"} or upload in {"failed", "rejected", "deleted"}:
                raise YouTubeEngineError(
                    "YouTube could not finish processing this video: " +
                    str(status.get("processing_failure_reason") or processing or upload)
                )
            if time.monotonic() >= deadline:
                raise YouTubeEngineError("YouTube processing is still pending; keep the MP4 and resume status checks.")
            self.sleep(interval_seconds)

    def set_visibility(
        self,
        video_id: str,
        privacy_status: str,
        *,
        publish_at: str | None = None,
    ) -> dict[str, Any]:
        if not _enabled(self.env, "PUBLISH_ENABLED"):
            raise PublishingDisabled("PUBLISH_ENABLED is false; visibility was not changed.")
        if privacy_status not in ALLOWED_PRIVACY:
            raise MetadataError("Privacy must be private, unlisted, or public.")
        if privacy_status == "public" and not _enabled(self.env, "YOUTUBE_PUBLICATION_APPROVED"):
            raise PublishingDisabled("Public publication requires a separate explicit approval.")
        if publish_at and privacy_status != "private":
            raise MetadataError("Scheduled publication must remain private until YouTube's scheduled time.")

        access_token = self.refresh_access_token()
        current = self.session.get(
            API_ROOT + "/videos",
            params={"part": "status", "id": video_id},
            headers=self._auth(access_token),
            timeout=30,
        )
        current.raise_for_status()
        items = current.json().get("items", [])
        if not items:
            raise YouTubeEngineError("Cannot change privacy: the video ID was not found.")
        old = items[0].get("status") or {}
        preserved = {}
        for field in (
            "license", "embeddable", "publicStatsViewable",
            "selfDeclaredMadeForKids", "containsSyntheticMedia",
        ):
            if field in old:
                preserved[field] = old[field]
        status = {**preserved, "privacyStatus": privacy_status}
        if publish_at:
            status["publishAt"] = publish_at
        response = self.session.put(
            API_ROOT + "/videos",
            params={"part": "status"},
            headers={**self._auth(access_token), "Content-Type": "application/json; charset=UTF-8"},
            json={"id": video_id, "status": status},
            timeout=45,
        )
        response.raise_for_status()
        return response.json()


def metadata_candidates_from_plan(plan: dict[str, Any]) -> list[str]:
    """Build conservative query seeds; callers can edit/approve them before searching."""
    topic = str(plan.get("topic") or "").strip()
    primary = str(plan.get("primary_keyword") or topic).strip()
    title = str(plan.get("title") or "").strip()
    hook = str(plan.get("hook") or "").strip()
    candidates = [primary, topic, title, hook]
    clean = []
    for candidate in candidates:
        value = re.sub(r"\s+", " ", candidate).strip()
        if value and value.casefold() not in {x.casefold() for x in clean}:
            clean.append(value)
    return clean[:5]
