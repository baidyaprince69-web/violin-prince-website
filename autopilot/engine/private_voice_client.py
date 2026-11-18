#!/usr/bin/env python3
"""Secure client for the private Qwen3 narration worker."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

import requests

PRIVATE_REPO = "baidyaprince69-web/violin-prince-private-voice"
WORKFLOW_FILE = "private-qwen3-narration.yml"
API_ROOT = "https://api.github.com"
WORD_RE = re.compile(r"[\w’'-]+", re.UNICODE)


class PrivateVoiceBridgeError(RuntimeError):
    """Raised when the private narration worker or its output cannot be trusted."""


def _normalise_script(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalise_word(value: str) -> str:
    return re.sub(r"[^\w]", "", str(value or "").casefold().replace("’", "'"), flags=re.UNICODE)


def _headers(token: str, *, binary: bool = False) -> dict[str, str]:
    return {
        "Authorization": "Bearer " + token,
        "Accept": "application/octet-stream" if binary else "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "ViolinPrince-PrivateVoiceBridge/1.0",
    }


def _json_request(session: requests.Session, method: str, url: str, token: str, **kwargs):
    try:
        response = session.request(
            method, url, headers=_headers(token), timeout=(20, 60), **kwargs
        )
    except requests.RequestException as exc:
        raise PrivateVoiceBridgeError("Could not reach the private voice service.") from exc
    if not response.ok:
        raise PrivateVoiceBridgeError(
            f"Private voice service returned HTTP {response.status_code}."
        )
    if response.status_code == 204:
        return None
    try:
        return response.json()
    except ValueError as exc:
        raise PrivateVoiceBridgeError("Private voice service returned invalid JSON.") from exc


def _find_run(session: requests.Session, token: str, request_id: str, dispatched_at: datetime):
    url = (
        f"{API_ROOT}/repos/{PRIVATE_REPO}/actions/workflows/"
        f"{WORKFLOW_FILE}/runs?event=workflow_dispatch&branch=main&per_page=100"
    )
    payload = _json_request(session, "GET", url, token)
    runs = payload.get("workflow_runs", []) if isinstance(payload, dict) else []
    expected_title = f"Private Qwen3 narration {request_id}"
    candidates = []
    for run in runs:
        if run.get("event") != "workflow_dispatch" or run.get("head_branch") != "main":
            continue
        if run.get("path") and run.get("path") != f".github/workflows/{WORKFLOW_FILE}":
            continue
        title = str(run.get("display_title") or "")
        if title != expected_title:
            continue
        try:
            created = datetime.fromisoformat(str(run.get("created_at", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if created >= dispatched_at:
            candidates.append(run)
    return max(candidates, key=lambda item: item.get("created_at", "")) if candidates else None


def _wait_for_run(session: requests.Session, token: str, request_id: str,
                  dispatched_at: datetime, timeout_seconds: int) -> dict:
    deadline = time.monotonic() + timeout_seconds
    run = None
    while time.monotonic() < deadline:
        run = _find_run(session, token, request_id, dispatched_at)
        if run and run.get("status") == "completed":
            if run.get("conclusion") != "success":
                url = run.get("html_url") or "the private Actions run"
                raise PrivateVoiceBridgeError(
                    "Private Qwen3 narration generation or word-timing verification failed: " + url
                )
            return run
        time.sleep(10)
    if run:
        raise PrivateVoiceBridgeError(
            "Private Qwen3 narration did not finish before the timeout: "
            + str(run.get("html_url") or "open the private Actions run")
        )
    raise PrivateVoiceBridgeError(
        "The private Qwen3 narration run could not be located. Check the private repository Actions page."
    )


def _download_asset(session: requests.Session, token: str, asset: dict, limit: int) -> bytes:
    if asset.get("state") != "uploaded":
        raise PrivateVoiceBridgeError("A private narration release asset is not fully uploaded.")
    if int(asset.get("size") or 0) <= 0 or int(asset.get("size") or 0) > limit:
        raise PrivateVoiceBridgeError("A private narration release asset has an invalid size.")
    url = str(asset.get("url") or "")
    if not url.startswith("https://api.github.com/repos/"):
        raise PrivateVoiceBridgeError("Private narration release asset URL is invalid.")
    try:
        response = session.get(
            url, headers=_headers(token, binary=True), timeout=(20, 120), allow_redirects=True
        )
    except requests.RequestException as exc:
        raise PrivateVoiceBridgeError("Could not download a private narration release asset.") from exc
    if not response.ok:
        raise PrivateVoiceBridgeError(
            f"Private narration asset download returned HTTP {response.status_code}."
        )
    content = response.content
    if not content or len(content) > limit:
        raise PrivateVoiceBridgeError("Downloaded private narration asset is empty or too large.")
    if len(content) != int(asset["size"]):
        raise PrivateVoiceBridgeError("Private narration asset size did not match GitHub's release metadata.")
    return content


def validate_private_narration(script: str, wav_bytes: bytes, metadata: dict) -> dict:
    """Validate provenance, exact word sequence, and monotonic model-derived timings."""
    from io import BytesIO
    import soundfile as sf

    script = _normalise_script(script)
    expected_words = WORD_RE.findall(script)
    if not 40 <= len(expected_words) <= 44:
        raise PrivateVoiceBridgeError("Narration must contain 40–44 words.")
    expected_hash = hashlib.sha256(script.encode("utf-8")).hexdigest()
    if metadata.get("schema_version") != 1 or metadata.get("script_sha256") != expected_hash:
        raise PrivateVoiceBridgeError("Private narration metadata does not match the requested script.")
    if metadata.get("word_sync_status") != "verified_exact_transcript":
        raise PrivateVoiceBridgeError("Private narration did not pass exact transcript verification.")
    if metadata.get("word_timing_method") != "faster-whisper-cross-attention-dtw":
        raise PrivateVoiceBridgeError("Private narration did not use the approved word-timing method.")
    aligner = metadata.get("aligner") or {}
    if aligner.get("transcript_match") != "exact" or aligner.get("model") != "small.en":
        raise PrivateVoiceBridgeError("Private narration transcript verification is incomplete.")

    audio = metadata.get("audio") or {}
    if hashlib.sha256(wav_bytes).hexdigest() != audio.get("sha256"):
        raise PrivateVoiceBridgeError("Private narration WAV checksum failed.")
    if int(audio.get("size_bytes") or 0) != len(wav_bytes):
        raise PrivateVoiceBridgeError("Private narration WAV size did not match its metadata.")

    try:
        info = sf.info(BytesIO(wav_bytes))
    except Exception as exc:
        raise PrivateVoiceBridgeError("Private narration WAV could not be decoded.") from exc
    duration = float(info.duration)
    if info.channels != 1 or int(info.samplerate) != int(audio.get("sample_rate") or 0):
        raise PrivateVoiceBridgeError("Private narration WAV channel or sample-rate validation failed.")
    if not 3.0 <= duration <= 23.5 or abs(duration - float(audio.get("duration_seconds") or 0)) > 0.08:
        raise PrivateVoiceBridgeError("Private narration duration validation failed.")

    cues = metadata.get("word_cues")
    if not isinstance(cues, list) or len(cues) != len(expected_words):
        raise PrivateVoiceBridgeError("Private narration is missing word-by-word timings.")
    actual_words = []
    previous_start = -1.0
    for index, cue in enumerate(cues):
        if not isinstance(cue, dict):
            raise PrivateVoiceBridgeError("Private narration contains an invalid word-timing entry.")
        token_list = WORD_RE.findall(str(cue.get("text") or ""))
        if len(token_list) != 1:
            raise PrivateVoiceBridgeError("Private narration contains an invalid aligned word.")
        actual_words.append(_normalise_word(token_list[0]))
        try:
            start, end = float(cue["start"]), float(cue["end"])
            sentence_index = int(cue["sentence_index"])
        except (KeyError, TypeError, ValueError) as exc:
            raise PrivateVoiceBridgeError("Private narration contains invalid timing values.") from exc
        if (
            not (0 <= start < end <= duration + 0.1)
            or start + 0.03 < previous_start
            or sentence_index not in (0, 1, 2, 3)
        ):
            raise PrivateVoiceBridgeError(f"Private narration timing validation failed at word {index + 1}.")
        previous_start = start

    expected_normalised = [_normalise_word(word) for word in expected_words]
    if actual_words != expected_normalised:
        raise PrivateVoiceBridgeError("Private narration word cues do not match the requested script.")
    subtitle_cues = metadata.get("subtitle_cues")
    if not isinstance(subtitle_cues, list) or len(subtitle_cues) != 4:
        raise PrivateVoiceBridgeError("Private narration is missing its four sentence timing cues.")
    for index, sentence in enumerate(subtitle_cues):
        if int(sentence.get("sentence_index", -1)) != index:
            raise PrivateVoiceBridgeError("Private narration sentence timings are not complete.")

    return {
        "engine": "Qwen3-TTS",
        "model": str(metadata.get("model") or "Qwen/Qwen3-TTS-12Hz-0.6B-Base"),
        "model_license": "Qwen3-TTS model terms apply",
        "origin": "creator_authorized_voice_clone",
        "voice_type": "creator_own_voice_clone",
        "voice": "approved_private_qwen3_voice",
        "rights_status": "creator_authorized_voice_clone_model_terms_apply",
        "duration_seconds": round(duration, 4),
        "sample_rate": int(info.samplerate),
        "channels": int(info.channels),
        "word_sync_status": "verified_exact_transcript",
        "word_timing_method": str(metadata["word_timing_method"]),
        "word_timing_count": len(cues),
        "word_cues": cues,
        "subtitle_cues": subtitle_cues,
        "aligner": aligner,
    }


def generate_private_voiceover(script: str, output_path: str | Path, *,
                               request_id: str | None = None,
                               timeout_seconds: int | None = None) -> tuple[Path, dict]:
    script = _normalise_script(script)
    token = os.environ.get("PRIVATE_VOICE_REPO_TOKEN", "").strip()
    if not token:
        raise PrivateVoiceBridgeError(
            "Private Qwen3 voice is not connected. Add the PRIVATE_VOICE_REPO_TOKEN "
            "Actions secret to the public Violin Prince repository."
        )
    request_id = str(request_id or os.environ.get("RUN_ID") or "")
    if not re.fullmatch(r"[0-9]{1,20}", request_id):
        raise PrivateVoiceBridgeError("A numeric request ID is required for the private narration job.")
    if not script or len(script) > 4000:
        raise PrivateVoiceBridgeError("Narration text is missing or outside the supported size limit.")
    dispatch_started = datetime.now(timezone.utc)
    session = requests.Session()
    dispatch_url = (
        f"{API_ROOT}/repos/{PRIVATE_REPO}/actions/workflows/{WORKFLOW_FILE}/dispatches"
    )
    _json_request(
        session, "POST", dispatch_url, token,
        json={"ref": "main", "inputs": {"request_id": request_id, "narration_text": script}},
    )
    timeout_seconds = int(timeout_seconds or os.environ.get("PRIVATE_VOICE_TIMEOUT_SECONDS", "5100"))
    run = _wait_for_run(session, token, request_id, dispatch_started, timeout_seconds)

    tag = "private-own-voice-narration-" + request_id
    release_url = f"{API_ROOT}/repos/{PRIVATE_REPO}/releases/tags/{quote(tag, safe='')}"
    release = _json_request(session, "GET", release_url, token)
    if not isinstance(release, dict) or release.get("draft") is not True or release.get("tag_name") != tag:
        raise PrivateVoiceBridgeError("The private narration release is missing or is not a draft.")
    assets = {str(item.get("name")): item for item in release.get("assets", [])}
    if "narration.wav" not in assets or "narration.json" not in assets:
        raise PrivateVoiceBridgeError("The private narration release is missing its required assets.")
    wav_bytes = _download_asset(session, token, assets["narration.wav"], 20 * 1024 * 1024)
    metadata_bytes = _download_asset(session, token, assets["narration.json"], 2 * 1024 * 1024)
    try:
        metadata = json.loads(metadata_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise PrivateVoiceBridgeError("Private narration metadata is not valid UTF-8 JSON.") from exc
    if metadata.get("request_id") != request_id:
        raise PrivateVoiceBridgeError("Private narration request ID does not match the current run.")
    info = validate_private_narration(script, wav_bytes, metadata)

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(wav_bytes)
    info["private_voice_run_id"] = int(run["id"])
    info["private_release_url"] = str(release.get("html_url") or "")
    info["private_release_tag"] = tag
    info["audio_sha256"] = hashlib.sha256(wav_bytes).hexdigest()
    return target, info


def main() -> int:
    parser = argparse.ArgumentParser(description="Run and verify the private Qwen3 own-voice narration bridge.")
    parser.add_argument("--output", default=os.environ.get("NARRATION_OUTPUT_PATH", "work/output/narration.wav"))
    args = parser.parse_args()
    script = os.environ.get("NARRATION_TEXT", "").strip()
    if not script:
        raise PrivateVoiceBridgeError("NARRATION_TEXT was not supplied.")
    path, info = generate_private_voiceover(script, args.output)
    print("Private Qwen3 narration bridge passed exact transcript and word-timing validation.")
    print("Word timings: " + str(info["word_timing_count"]))
    print("Private release: " + (info.get("private_release_url") or "available in the private repository"))
    print("Temporary WAV: " + str(path))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PrivateVoiceBridgeError as exc:
        print("::error::" + str(exc), file=sys.stderr)
        raise SystemExit(1)
