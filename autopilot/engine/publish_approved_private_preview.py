#!/usr/bin/env python3
"""Fail-closed one-time publisher for a creator-approved private preview."""
from __future__ import annotations
import hashlib, json, os, re, subprocess, sys, zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path
from zoneinfo import ZoneInfo
import av
import requests

ROOT = Path(__file__).resolve().parents[2]
PUBLIC_REPO = "baidyaprince69-web/violin-prince-website"
PRIVATE_REPO = "baidyaprince69-web/violin-prince-private-voice"
YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
HTTP = requests.Session()
HTTP.headers["User-Agent"] = "ViolinPrinceApprovedPreviewPublisher/1.0"

class PublishBlocked(RuntimeError):
    pass

def require_env(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise PublishBlocked("Required Actions secret/environment value is missing: " + name)
    return value

def github_json(url: str, token: str):
    response = HTTP.get(url, headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"}, timeout=45)
    response.raise_for_status()
    return response.json()

def marker_json(log_text: str, marker: str) -> dict:
    for line in log_text.splitlines():
        offset = line.find(marker)
        if offset >= 0:
            try:
                result, _ = json.JSONDecoder().raw_decode(line[offset + len(marker):].strip())
            except json.JSONDecodeError as exc:
                raise PublishBlocked("Could not parse " + marker + " from the original production logs.") from exc
            if isinstance(result, dict):
                return result
    raise PublishBlocked("The original production logs do not contain " + marker)

def extract_job_log(token: str, job_id: int) -> str:
    response = HTTP.get(
        f"https://api.github.com/repos/{PUBLIC_REPO}/actions/jobs/{job_id}/logs",
        headers={"Authorization": "Bearer " + token, "Accept": "application/vnd.github+json"},
        timeout=90,
    )
    response.raise_for_status()
    payload = response.content
    if payload[:2] == b"PK":
        try:
            with zipfile.ZipFile(BytesIO(payload)) as archive:
                return "\n".join(archive.read(n).decode("utf-8", errors="replace") for n in archive.namelist() if n.lower().endswith(".txt"))
        except zipfile.BadZipFile as exc:
            raise PublishBlocked("GitHub returned an unreadable workflow-log archive.") from exc
    return payload.decode("utf-8", errors="replace")

def validate_runs(request: dict, public_token: str, private_token: str) -> dict:
    source_id = str(request["source_workflow_run_id"])
    voice_id = str(request["voice_workflow_run_id"])
    run = github_json(f"https://api.github.com/repos/{PUBLIC_REPO}/actions/runs/{source_id}", public_token)
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise PublishBlocked("The original full production run is not successfully completed.")
    run_date = datetime.fromisoformat(run["created_at"].replace("Z", "+00:00")).astimezone(ZoneInfo("Asia/Kolkata")).date().isoformat()
    jobs_data = github_json(f"https://api.github.com/repos/{PUBLIC_REPO}/actions/runs/{source_id}/jobs?per_page=100", public_token)
    jobs = [j for j in jobs_data.get("jobs", []) if j.get("name") == "produce" and j.get("conclusion") == "success"]
    if len(jobs) != 1:
        raise PublishBlocked("Could not identify exactly one successful production job.")
    logs = extract_job_log(public_token, int(jobs[0]["id"]))
    preflight = marker_json(logs, "PUBLISHER_PREFLIGHT=")
    result = marker_json(logs, "DAILY_PRODUCTION_RESULT=")
    if preflight.get("status") != "ready" or preflight.get("blockers"):
        raise PublishBlocked("The original production publisher preflight was not ready.")
    if result.get("status") != "rendered" or str(result.get("run_id")) != source_id or result.get("publish_ready") is not True:
        raise PublishBlocked("The original production result does not confirm publish_ready=true.")
    quality = result.get("quality") or {}
    media = quality.get("media_verification") or {}
    expected_sha = str(request["expected_sha256"]).lower()
    expected_size = int(request["expected_size_bytes"])
    if media.get("status") != "passed" or quality.get("duration_seconds") != 24.0:
        raise PublishBlocked("The original production media-quality report did not pass.")
    if quality.get("width") != 720 or quality.get("height") != 1280 or quality.get("video_codec") != "h264":
        raise PublishBlocked("The original production media does not match the verified Shorts format.")
    if media.get("black_interval_count") != 0 or media.get("freeze_interval_count") != 0:
        raise PublishBlocked("The original media report contains a black or freeze interval.")
    if f"MP4 SHA-256: {expected_sha}" not in logs or int(quality.get("file_size_bytes") or 0) != expected_size:
        raise PublishBlocked("The source log does not prove the exact expected MP4 hash and size.")
    if run_date != str(request["production_date"]):
        raise PublishBlocked("The production date does not match the approved plan date.")

    voice_run = github_json(f"https://api.github.com/repos/{PRIVATE_REPO}/actions/runs/{voice_id}", private_token)
    if voice_run.get("status") != "completed" or voice_run.get("conclusion") != "success":
        raise PublishBlocked("The private Qwen3 narration run is not successfully completed.")
    voice_jobs_data = github_json(f"https://api.github.com/repos/{PRIVATE_REPO}/actions/runs/{voice_id}/jobs?per_page=100", private_token)
    voice_jobs = [j for j in voice_jobs_data.get("jobs", []) if j.get("name") == "generate-private-narration" and j.get("conclusion") == "success"]
    if len(voice_jobs) != 1:
        raise PublishBlocked("The private Qwen3 narration job did not pass.")
    return {
        "source_run_id": source_id, "source_run_date": run_date, "source_job_id": int(jobs[0]["id"]),
        "voice_run_id": voice_id, "voice_job_id": int(voice_jobs[0]["id"]),
        "sha256": expected_sha, "size_bytes": expected_size, "media_verification": media,
        "publisher_preflight": preflight,
    }

def download_asset(request: dict, token: str, audit: dict, workdir: Path) -> Path:
    releases = github_json(f"https://api.github.com/repos/{PRIVATE_REPO}/releases?per_page=100", token)
    matches = [r for r in releases if r.get("tag_name") == request["private_release_tag"] and r.get("draft") is True]
    if len(matches) != 1:
        raise PublishBlocked("The exact private draft release for this production run was not found.")
    assets = [a for a in matches[0].get("assets", []) if int(a.get("id") or 0) == int(request["private_release_asset_id"]) and a.get("name") == "violin-prince-short.mp4"]
    if len(assets) != 1:
        raise PublishBlocked("The private release does not contain exactly the requested MP4 asset.")
    asset = assets[0]
    if int(asset.get("size") or 0) != audit["size_bytes"] or asset.get("digest") != "sha256:" + audit["sha256"]:
        raise PublishBlocked("Private release asset metadata differs from the verified production output.")
    response = HTTP.get(
        f"https://api.github.com/repos/{PRIVATE_REPO}/releases/assets/{asset['id']}",
        headers={"Authorization": "Bearer " + token, "Accept": "application/octet-stream"},
        timeout=180,
    )
    response.raise_for_status()
    if len(response.content) != audit["size_bytes"] or hashlib.sha256(response.content).hexdigest() != audit["sha256"]:
        raise PublishBlocked("Downloaded private MP4 does not match the verified SHA-256 and size.")
    workdir.mkdir(parents=True, exist_ok=True)
    target = workdir / "violin-prince-short.mp4"
    target.write_bytes(response.content)
    return target

def validate_media(path: Path):
    try:
        with av.open(str(path)) as container:
            video = next((stream for stream in container.streams if stream.type == "video"), None)
            audio = next((stream for stream in container.streams if stream.type == "audio"), None)
            duration = float(container.duration or 0) / float(av.time_base)
            video_codec = video.codec_context.name if video else None
            video_width = int(video.width or 0) if video else 0
            video_height = int(video.height or 0) if video else 0
            audio_sample_rate = int(audio.codec_context.sample_rate or 0) if audio else 0
    except Exception as exc:
        raise PublishBlocked("PyAV could not independently inspect the private MP4.") from exc
    if not video or not audio or video_codec != "h264" or video_width != 720 or video_height != 1280 or not 20 <= duration <= 25:
        raise PublishBlocked("Independent MP4 inspection failed the 20–25 second vertical Shorts contract.")
    if audio_sample_rate != 48000:
        raise PublishBlocked("Independent MP4 inspection found an unexpected audio sample rate.")

def validate_plan(plan: dict, request: dict) -> dict:
    if plan.get("title") != request["title"]:
        raise PublishBlocked("Approved title and original production plan do not match.")
    script = re.sub(r"\s+", " ", str(plan.get("narration_script") or "")).strip()
    words = re.findall(r"\b[\w’'-]+\b", script)
    sentences = re.findall(r"[^.!?]+[.!?]+(?=\s|$)", script)
    if len(words) != 35 or len(sentences) != 4:
        raise PublishBlocked("The original plan no longer matches the 35-word/four-sentence narration contract.")
    sources = plan.get("sources") or []
    evidence = plan.get("narration_evidence") or []
    if len(sources) < 2 or len(evidence) < 3 or {int(x.get("sentence_number") or 0) for x in evidence} != {2, 3, 4}:
        raise PublishBlocked("The plan does not contain the verified two-source, three-claim research record.")
    if request.get("creator_approved_publication") is not True or str(request.get("approval_statement") or "").strip().casefold() != "everything is approved":
        raise PublishBlocked("The explicit creator publication approval is missing.")
    hashtags = " ".join(str(x) for x in (plan.get("hashtags") or [])[:12])
    urls = [str(x.get("url") or "").strip() for x in sources[:3] if isinstance(x, dict) and str(x.get("url") or "").startswith("https://")]
    description = "\n\n".join(p for p in (
        str(plan.get("hook") or plan["title"]).strip(), str(plan.get("description") or "").strip(),
        hashtags, "Research references: " + " ".join(urls) if urls else "",
    ) if p)[:2100]
    plan["contains_synthetic_media"] = True
    plan["made_for_kids"] = False
    plan["publish_metadata"] = {
        "title": str(plan["title"])[:100], "description": description,
        "tags": plan.get("tags") or plan.get("hashtags") or [], "category_id": "10",
        "default_language": "en", "made_for_kids": False, "privacy_status": "public",
        "contains_synthetic_media": True,
    }
    return plan

def youtube_token() -> str:
    response = HTTP.post("https://oauth2.googleapis.com/token", data={
        "client_id": require_env("YOUTUBE_CLIENT_ID"), "client_secret": require_env("YOUTUBE_CLIENT_SECRET"),
        "refresh_token": require_env("YOUTUBE_REFRESH_TOKEN"), "grant_type": "refresh_token",
    }, timeout=45)
    response.raise_for_status()
    token = response.json().get("access_token")
    if not token:
        raise PublishBlocked("Google OAuth refresh did not return an access token.")
    return token

def verify_channel_no_duplicate(token: str, expected_channel: str) -> dict:
    headers = {"Authorization": "Bearer " + token}
    response = HTTP.get(YOUTUBE_API + "/channels", params={"part": "id,contentDetails", "mine": "true"}, headers=headers, timeout=45)
    response.raise_for_status()
    channel = next((x for x in response.json().get("items", []) if x.get("id") == expected_channel), None)
    if channel is None:
        raise PublishBlocked("OAuth did not verify the expected Violin Prince channel.")
    playlist = (channel.get("contentDetails") or {}).get("relatedPlaylists", {}).get("uploads")
    if not playlist:
        raise PublishBlocked("The expected YouTube channel did not return its uploads playlist.")
    next_page = None
    pages = 0
    duplicates = []
    while True:
        params = {"part": "snippet,contentDetails", "playlistId": playlist, "maxResults": 50}
        if next_page:
            params["pageToken"] = next_page
        page = HTTP.get(YOUTUBE_API + "/playlistItems", params=params, headers=headers, timeout=45)
        page.raise_for_status()
        data = page.json()
        for item in data.get("items") or []:
            title = str((item.get("snippet") or {}).get("title") or "")
            if "spliteq 2" in title.casefold():
                duplicates.append({"title": title, "video_id": (item.get("contentDetails") or {}).get("videoId")})
        pages += 1
        next_page = data.get("nextPageToken")
        if not next_page:
            break
        if pages >= 30:
            raise PublishBlocked("The duplicate-check page limit was reached; refusing publication without a complete check.")
    if duplicates:
        raise PublishBlocked("A prior SplitEQ 2 upload already exists: " + json.dumps(duplicates[:5]))
    return {"channel_id": expected_channel, "uploads_checked_pages": pages, "spliteq2_matches": 0}

def git_commit(paths: list[str], message: str):
    subprocess.run(["git", "config", "user.name", "github-actions[bot]"], cwd=ROOT, check=True)
    subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], cwd=ROOT, check=True)
    subprocess.run(["git", "add", *paths], cwd=ROOT, check=True)
    result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
    if result.returncode == 0:
        raise PublishBlocked("No durable publication record was staged; refusing to upload.")
    subprocess.run(["git", "commit", "-m", message], cwd=ROOT, check=True)
    subprocess.run(["git", "push", "origin", "HEAD:main"], cwd=ROOT, check=True)

def summary(message: str):
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if path:
        with open(path, "a", encoding="utf-8") as handle:
            handle.write(message + "\n")

def main() -> int:
    raise PublishBlocked(
        "Public YouTube publication is disabled. Private previews must remain private."
    )
    request = json.loads((ROOT / ".autopilot/approved-preview-publication.json").read_text(encoding="utf-8"))
    plan_path = ROOT / ".autopilot/daily-production-plan.json"
    if request.get("schema_version") != 1 or request.get("mode") != "approved_private_preview_publication" or request.get("publish_to_youtube") is not True:
        raise PublishBlocked("Unsupported or non-public approved-preview request.")
    if os.environ.get("GITHUB_REF_NAME") != "main":
        raise PublishBlocked("Publication must run from main.")
    public_token = require_env("GITHUB_TOKEN")
    private_token = require_env("PRIVATE_VOICE_REPO_TOKEN")
    expected_channel = require_env("EXPECTED_YOUTUBE_CHANNEL_ID")
    if request.get("youtube_channel_id") != expected_channel:
        raise PublishBlocked("The request channel does not match the protected expected channel.")

    audit = validate_runs(request, public_token, private_token)
    video = download_asset(request, private_token, audit, ROOT / "work/approved-preview-publication")
    validate_media(video)
    plan = validate_plan(json.loads(plan_path.read_text(encoding="utf-8")), request)

    attempt_dir = ROOT / ".autopilot/publication-attempts"
    receipt_dir = ROOT / ".autopilot/publication-receipts"
    attempt_path = attempt_dir / (audit["source_run_id"] + ".json")
    receipt_path = receipt_dir / (audit["source_run_id"] + ".json")
    if receipt_path.exists():
        summary("## Already published\n\nA durable receipt already exists for this source run.")
        return 0
    if attempt_path.exists():
        raise PublishBlocked("A durable attempt exists without a receipt. Reconcile YouTube manually before retrying.")

    token = youtube_token()
    duplicate_check = verify_channel_no_duplicate(token, expected_channel)
    attempt_dir.mkdir(parents=True, exist_ok=True)
    attempt = {
        "schema_version": 1, "status": "attempting", "source_workflow_run_id": audit["source_run_id"],
        "private_release_tag": request["private_release_tag"], "expected_sha256": audit["sha256"],
        "youtube_channel_id": expected_channel, "title": plan["title"], "privacy_status": "public",
        "duplicate_check": duplicate_check, "created_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "note": "Committed before upload; an uncertain outcome must be reconciled manually before retry.",
    }
    attempt_path.write_text(json.dumps(attempt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    git_commit([str(attempt_path.relative_to(ROOT))], "Record one-time approved SplitEQ 2 publication attempt")

    sys.path.insert(0, str(ROOT / "autopilot/engine"))
    import publisher
    os.environ["YOUTUBE_PRIVACY_STATUS"] = "public"
    upload = publisher.youtube_upload(video, plan)
    video_id = str(upload.get("id") or "").strip()
    video_url = str(upload.get("url") or "").strip()
    if upload.get("ok") is False or not video_id or not video_url:
        raise PublishBlocked("YouTube did not return a confirmed video ID and URL.")

    receipt = {
        "schema_version": 1, "status": "uploaded", "provider": "youtube_data_api",
        "source_workflow_run_id": audit["source_run_id"], "voice_workflow_run_id": audit["voice_run_id"],
        "youtube_video_id": video_id, "youtube_video_url": video_url, "youtube_channel_id": expected_channel,
        "title": plan["title"], "privacy_status": "public", "sha256": audit["sha256"],
        "size_bytes": audit["size_bytes"], "duplicate_check": duplicate_check,
        "production_audit": audit, "uploaded_at_utc": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    receipt_dir.mkdir(parents=True, exist_ok=True)
    receipt_path.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    attempt.update({"status": "uploaded", "youtube_video_id": video_id, "youtube_video_url": video_url, "completed_at_utc": receipt["uploaded_at_utc"]})
    attempt_path.write_text(json.dumps(attempt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    git_commit([str(attempt_path.relative_to(ROOT)), str(receipt_path.relative_to(ROOT))], "Save confirmed SplitEQ 2 YouTube publication receipt")
    summary("## SplitEQ 2 published successfully\n\nTitle: " + plan["title"] + "\n\nYouTube video: " + video_url + "\n\nDuplicate check: passed against channel uploads playlist\n\nPrivacy: public\n\nSHA-256: " + audit["sha256"])
    print(json.dumps(receipt, ensure_ascii=False, indent=2))
    return 0

if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (PublishBlocked, requests.RequestException, OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        message = "APPROVED PREVIEW PUBLICATION BLOCKED: " + str(exc)
        print(message, file=sys.stderr)
        summary("## Publication blocked\n\n" + message)
        raise SystemExit(1)
