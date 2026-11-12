"""Optional official-platform publishing adapters.

All publishing is disabled unless PUBLISH_ENABLED=true and the required
account-owner-authorised OAuth credentials are supplied as GitHub secrets.
"""
import os
import time
from pathlib import Path
from urllib.parse import urljoin

import requests

HTTP = requests.Session()
HTTP.headers["User-Agent"] = "ViolinPrinceAutopilot/0.1"


class PublishError(RuntimeError):
    pass


def require(name):
    value = os.environ.get(name, "").strip()
    if not value:
        raise PublishError("Missing configured publishing value: " + name)
    return value


def make_caption(plan):
    parts = [str(plan.get("hook") or plan.get("title") or "A violin-led visual story")]
    desc = str(plan.get("description") or "").strip()
    if desc:
        parts.append(desc)
    tags = plan.get("hashtags") or []
    if isinstance(tags, str):
        tags = tags.split()
    clean = []
    for tag in tags:
        value = str(tag).strip().replace(" ", "")
        if value:
            clean.append(value if value.startswith("#") else "#" + value)
    if clean:
        parts.append(" ".join(clean[:12]))
    sources = plan.get("sources") or []
    if sources:
        parts.append("Research references: " + " ".join(str(x) for x in sources[:3]))
    return "\n\n".join(parts)[:2100]


def youtube_upload(video_path: Path, plan: dict):
    client_id = require("YOUTUBE_CLIENT_ID")
    client_secret = require("YOUTUBE_CLIENT_SECRET")
    refresh_token = require("YOUTUBE_REFRESH_TOKEN")

    token = HTTP.post(
        "https://oauth2.googleapis.com/token",
        data={"client_id": client_id, "client_secret": client_secret,
              "refresh_token": refresh_token, "grant_type": "refresh_token"},
        timeout=30,
    )
    token.raise_for_status()
    access_token = token.json().get("access_token")
    if not access_token:
        raise PublishError("Google OAuth refresh did not return an access token.")

    title = str(plan.get("title") or "Violin Prince")[:95]
    body = {
        "snippet": {
            "title": title,
            "description": make_caption(plan),
            "tags": [str(x).lstrip("#").replace(" ", "")[:30]
                     for x in (plan.get("hashtags") or [])[:15]] if isinstance(plan.get("hashtags"), list) else [],
            "categoryId": "10",
            "defaultLanguage": "en",
        },
        "status": {
            "privacyStatus": os.environ.get("YOUTUBE_PRIVACY_STATUS", "public"),
            "selfDeclaredMadeForKids": False,
            "containsSyntheticMedia": True,
        },
    }
    publish_at = os.environ.get("YOUTUBE_PUBLISH_AT", "").strip()
    if publish_at:
        body["status"]["privacyStatus"] = "private"
        body["status"]["publishAt"] = publish_at

    size = video_path.stat().st_size
    init = HTTP.post(
        "https://www.googleapis.com/upload/youtube/v3/videos",
        params={"uploadType": "resumable", "part": "snippet,status"},
        headers={
            "Authorization": "Bearer " + access_token,
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(size),
            "X-Upload-Content-Type": "video/mp4",
        },
        json=body,
        timeout=45,
    )
    init.raise_for_status()
    upload_url = init.headers.get("Location")
    if not upload_url:
        raise PublishError("YouTube did not return a resumable upload URL.")
    with video_path.open("rb") as handle:
        uploaded = HTTP.put(
            upload_url,
            headers={"Content-Type": "video/mp4", "Content-Length": str(size)},
            data=handle,
            timeout=600,
        )
    uploaded.raise_for_status()
    video_id = uploaded.json().get("id")
    if not video_id:
        raise PublishError("YouTube upload response did not contain a video ID.")
    return {"platform": "youtube", "ok": True, "id": video_id,
            "url": "https://www.youtube.com/watch?v=" + video_id}


def instagram_publish(video_url: str, plan: dict):
    version = require("META_API_VERSION")
    user_id = require("INSTAGRAM_USER_ID")
    token = require("INSTAGRAM_ACCESS_TOKEN")
    base = "https://graph.facebook.com/" + version + "/"
    caption = make_caption(plan)

    created = HTTP.post(
        urljoin(base, user_id + "/media"),
        data={"media_type": "REELS", "video_url": video_url,
              "caption": caption, "share_to_feed": "true", "access_token": token},
        timeout=60,
    )
    created.raise_for_status()
    container_id = created.json().get("id")
    if not container_id:
        raise PublishError("Instagram did not return a media-container ID.")

    deadline = time.time() + 360
    status = "IN_PROGRESS"
    while time.time() < deadline:
        check = HTTP.get(
            urljoin(base, container_id),
            params={"fields": "status_code,status", "access_token": token},
            timeout=30,
        )
        check.raise_for_status()
        payload = check.json()
        status = payload.get("status_code", "")
        if status == "FINISHED":
            break
        if status in ("ERROR", "EXPIRED"):
            raise PublishError("Instagram media processing ended with status " + str(status))
        time.sleep(15)
    if status != "FINISHED":
        raise PublishError("Instagram media processing did not finish before timeout.")

    published = HTTP.post(
        urljoin(base, user_id + "/media_publish"),
        data={"creation_id": container_id, "access_token": token},
        timeout=60,
    )
    published.raise_for_status()
    media_id = published.json().get("id")
    return {"platform": "instagram", "ok": True, "id": media_id}


def facebook_publish(video_url: str, plan: dict):
    version = require("META_API_VERSION")
    page_id = require("FACEBOOK_PAGE_ID")
    token = require("FACEBOOK_PAGE_ACCESS_TOKEN")
    base = "https://graph.facebook.com/" + version + "/"
    title = str(plan.get("title") or "Violin Prince")[:95]
    description = make_caption(plan)

    started = HTTP.post(
        urljoin(base, page_id + "/video_reels"),
        params={"upload_phase": "start", "access_token": token},
        timeout=45,
    )
    started.raise_for_status()
    video_id = started.json().get("video_id")
    if not video_id:
        raise PublishError("Facebook did not return a Reels video ID.")

    transfer = HTTP.post(
        "https://rupload.facebook.com/video-upload/" + version + "/" + video_id,
        headers={"Authorization": "OAuth " + token, "file_url": video_url},
        timeout=300,
    )
    transfer.raise_for_status()
    if transfer.json().get("success") is not True:
        raise PublishError("Facebook did not confirm the hosted-video transfer.")

    finished = HTTP.post(
        urljoin(base, page_id + "/video_reels"),
        params={"upload_phase": "finish", "video_id": video_id,
                "video_state": "PUBLISHED", "title": title,
                "description": description, "access_token": token},
        timeout=90,
    )
    finished.raise_for_status()
    if finished.json().get("success") is not True:
        raise PublishError("Facebook did not confirm Reel publication.")
    return {"platform": "facebook", "ok": True, "id": video_id}


def publish_all(video_path: Path, media_url: str, plan: dict):
    """Publish only to explicitly selected destinations."""
    if os.environ.get("PUBLISH_ENABLED", "false").lower() != "true":
        return {"enabled": False, "results": [], "message": "Publishing is disabled; draft only."}

    destinations = [
        item.strip().lower()
        for item in os.environ.get("PUBLISH_DESTINATIONS", "youtube,instagram,facebook").split(",")
        if item.strip()
    ]
    results = []
    failures = []
    for destination in destinations:
        try:
            if destination == "youtube":
                result = youtube_upload(video_path, plan)
            elif destination == "instagram":
                result = instagram_publish(media_url, plan)
            elif destination == "facebook":
                result = facebook_publish(media_url, plan)
            else:
                raise PublishError("Unknown publishing destination: " + destination)
            results.append(result)
        except Exception as exc:
            failures.append({"platform": destination, "error": str(exc)[:500]})

    return {"enabled": True, "results": results, "failures": failures,
            "all_succeeded": bool(destinations) and not failures and len(results) == len(destinations)}
