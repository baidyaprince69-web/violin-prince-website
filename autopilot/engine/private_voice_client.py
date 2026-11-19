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

import requests

PRIVATE_REPO = "baidyaprince69-web/violin-prince-private-voice"
WORKFLOW_FILE = "private-qwen3-narration.yml"
CLEANUP_WORKFLOW_FILE = "private-qwen3-cleanup.yml"
API_ROOT = "https://api.github.com"
WORD_RE = re.compile(r"[\w’'-]+", re.UNICODE)
GENERATION_SEEDS = (43, 44, 45)
GENERATION_TEMPERATURE = 0.9


class PrivateVoiceBridgeError(RuntimeError):
    """Raised when the private narration worker or its output cannot be trusted."""


def _normalise_script(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _normalise_hotwords(value) -> list[str]:
    if isinstance(value, list):
        raw_terms = value
    else:
        raw_terms = str(value or "").split(",")
    terms = [str(term).strip() for term in raw_terms if str(term).strip()]
    if len(terms) > 10:
        raise PrivateVoiceBridgeError("At most 10 ASR hotword hints may be supplied.")
    for term in terms:
        if not re.fullmatch(r"[\w’'-]+(?: [\w’'-]+){0,2}", term, flags=re.UNICODE):
            raise PrivateVoiceBridgeError("An ASR hotword hint contains unsupported characters or spacing.")
    if len({term.casefold() for term in terms}) != len(terms):
        raise PrivateVoiceBridgeError("ASR hotword hints must be unique.")
    return terms


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


def _download_private_transfer_file(
    session: requests.Session, token: str, request_id: str, branch: str, filename: str
) -> bytes:
    """Read one approved binary file from a temporary branch in the private repository."""
    if filename not in {"narration.wav", "narration.json"}:
        raise PrivateVoiceBridgeError("The requested private transfer filename is not permitted.")
    path = f"bridge-transfer/{request_id}/{filename}"
    url = f"{API_ROOT}/repos/{PRIVATE_REPO}/contents/{path}"
    headers = _headers(token, binary=True)
    headers["Accept"] = "application/vnd.github.raw+json"
    try:
        response = session.get(
            url, headers=headers, params={"ref": branch},
            timeout=(20, 120), allow_redirects=True
        )
    except requests.RequestException as exc:
        raise PrivateVoiceBridgeError("Could not reach the private narration transfer branch.") from exc
    if not response.ok:
        if response.status_code in (401, 403, 404):
            raise PrivateVoiceBridgeError(
                "The private narration file could not be read (HTTP "
                f"{response.status_code}). Check that PRIVATE_VOICE_REPO_TOKEN has "
                "Contents: read access to violin-prince-private-voice."
            )
        raise PrivateVoiceBridgeError(
            f"Private narration file download returned HTTP {response.status_code}."
        )
    data = response.content
    limit = 20 * 1024 * 1024 if filename == "narration.wav" else 2 * 1024 * 1024
    if not data or len(data) > limit:
        raise PrivateVoiceBridgeError("A private narration transfer file is empty or too large.")
    return data


def _find_cleanup_run(
    session: requests.Session, token: str, request_id: str, dispatched_at: datetime
):
    url = (
        f"{API_ROOT}/repos/{PRIVATE_REPO}/actions/workflows/"
        f"{CLEANUP_WORKFLOW_FILE}/runs?event=workflow_dispatch&branch=main&per_page=100"
    )
    payload = _json_request(session, "GET", url, token)
    runs = payload.get("workflow_runs", []) if isinstance(payload, dict) else []
    expected_title = f"Clean up private narration transfer {request_id}"
    candidates = []
    for run in runs:
        if run.get("event") != "workflow_dispatch" or run.get("head_branch") != "main":
            continue
        if run.get("path") and run.get("path") != f".github/workflows/{CLEANUP_WORKFLOW_FILE}":
            continue
        if str(run.get("display_title") or "") != expected_title:
            continue
        try:
            created = datetime.fromisoformat(str(run.get("created_at", "")).replace("Z", "+00:00"))
        except ValueError:
            continue
        if created >= dispatched_at:
            candidates.append(run)
    return max(candidates, key=lambda item: item.get("created_at", "")) if candidates else None


def _request_private_transfer_cleanup(
    session: requests.Session, token: str, request_id: str, timeout_seconds: int = 180
) -> dict:
    """Ask the private repository to delete the transfer branch and confirm cleanup."""
    dispatched_at = datetime.now(timezone.utc)
    dispatch_url = (
        f"{API_ROOT}/repos/{PRIVATE_REPO}/actions/workflows/"
        f"{CLEANUP_WORKFLOW_FILE}/dispatches"
    )
    _json_request(
        session, "POST", dispatch_url, token,
        json={"ref": "main", "inputs": {"request_id": request_id}},
    )
    deadline = time.monotonic() + timeout_seconds
    cleanup_run = None
    while time.monotonic() < deadline:
        cleanup_run = _find_cleanup_run(session, token, request_id, dispatched_at)
        if cleanup_run and cleanup_run.get("status") == "completed":
            if cleanup_run.get("conclusion") != "success":
                raise PrivateVoiceBridgeError(
                    "Private narration transfer cleanup failed: "
                    + str(cleanup_run.get("html_url") or "open the private cleanup Actions run")
                )
            print("Temporary private narration branch was deleted.")
            return cleanup_run
        time.sleep(5)
    raise PrivateVoiceBridgeError(
        "The temporary private narration branch cleanup did not finish before the timeout."
    )


def validate_private_narration(
    script: str, wav_bytes: bytes, metadata: dict, expected_hotwords: list[str] | None = None
) -> dict:
    """Validate provenance, exact word sequence, and monotonic model-derived timings."""
    from io import BytesIO
    import soundfile as sf

    script = _normalise_script(script)
    expected_words = WORD_RE.findall(script)
    if len(expected_words) != 35:
        raise PrivateVoiceBridgeError("Narration must contain exactly 35 words, calibrated for a natural 22–23-second delivery.")
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
    recorded_hotwords = aligner.get("hotwords")
    if not isinstance(recorded_hotwords, list) or not all(isinstance(term, str) for term in recorded_hotwords):
        raise PrivateVoiceBridgeError("Private narration ASR hotword metadata is missing or invalid.")
    if expected_hotwords is not None and recorded_hotwords != expected_hotwords:
        raise PrivateVoiceBridgeError("Private narration ASR hotword hints do not match the requested terms.")
    generation = metadata.get("generation") or {}
    try:
        generation_tokens = int(generation.get("max_new_tokens", 0))
        generation_penalty = float(generation.get("repetition_penalty", 0))
        generation_temperature = float(generation.get("temperature", 0))
        generation_seed = int(generation.get("seed", -1))
        generation_attempt = int(generation.get("attempt", 0))
    except (TypeError, ValueError) as exc:
        raise PrivateVoiceBridgeError("Private narration generation metadata is invalid.") from exc
    if (
        generation_tokens != 288
        or generation_penalty != 1.1
        or generation.get("do_sample") is not True
        or generation_temperature != GENERATION_TEMPERATURE
        or generation_attempt < 1
        or generation_attempt > len(GENERATION_SEEDS)
        or generation_seed != GENERATION_SEEDS[generation_attempt - 1]
    ):
        raise PrivateVoiceBridgeError("Private narration generation safeguards do not match the reviewed configuration.")

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
    if not 22.0 <= duration <= 23.0 or abs(duration - float(audio.get("duration_seconds") or 0)) > 0.08:
        raise PrivateVoiceBridgeError("Private narration must be naturally generated between 22.0 and 23.0 seconds; post-generation speed changes are not accepted.")
    if metadata.get("audio_postprocessing") != "none":
        raise PrivateVoiceBridgeError("Private narration must use raw Qwen3 audio without time-stretching.")

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
                               timeout_seconds: int | None = None,
                               asr_hotwords: str | list[str] | None = None) -> tuple[Path, dict]:
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
    hotwords = _normalise_hotwords(
        asr_hotwords if asr_hotwords is not None else os.environ.get("ASR_HOTWORDS", "")
    )
    dispatch_started = datetime.now(timezone.utc)
    session = requests.Session()
    dispatch_url = (
        f"{API_ROOT}/repos/{PRIVATE_REPO}/actions/workflows/{WORKFLOW_FILE}/dispatches"
    )
    _json_request(
        session, "POST", dispatch_url, token,
        json={"ref": "main", "inputs": {
            "request_id": request_id,
            "narration_text": script,
            "asr_hotwords": ", ".join(hotwords),
        }},
    )
    timeout_seconds = int(timeout_seconds or os.environ.get("PRIVATE_VOICE_TIMEOUT_SECONDS", "5100"))
    run = None
    transfer_branch = "private-qwen3-transfer-" + request_id
    try:
        run = _wait_for_run(session, token, request_id, dispatch_started, timeout_seconds)
        wav_bytes = _download_private_transfer_file(
            session, token, request_id, transfer_branch, "narration.wav"
        )
        metadata_bytes = _download_private_transfer_file(
            session, token, request_id, transfer_branch, "narration.json"
        )
        try:
            metadata = json.loads(metadata_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise PrivateVoiceBridgeError("Private narration metadata is not valid UTF-8 JSON.") from exc
        if metadata.get("request_id") != request_id:
            raise PrivateVoiceBridgeError("Private narration request ID does not match the current run.")
        info = validate_private_narration(
            script, wav_bytes, metadata, expected_hotwords=hotwords
        )
    except Exception:
        try:
            _request_private_transfer_cleanup(session, token, request_id)
        except Exception as cleanup_exc:
            print("::warning::Private transfer cleanup also failed: " + str(cleanup_exc), file=sys.stderr)
        raise
    else:
        _request_private_transfer_cleanup(session, token, request_id)

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(wav_bytes)
    info["private_voice_run_id"] = int(run["id"])
    info["private_transfer_branch"] = transfer_branch
    info["audio_sha256"] = hashlib.sha256(wav_bytes).hexdigest()
    return target, info


def main() -> int:
    parser = argparse.ArgumentParser(description="Run and verify the private Qwen3 own-voice narration bridge.")
    parser.add_argument("--output", default=os.environ.get("NARRATION_OUTPUT_PATH", "work/output/narration.wav"))
    args = parser.parse_args()
    script = os.environ.get("NARRATION_TEXT", "").strip()
    if not script:
        raise PrivateVoiceBridgeError("NARRATION_TEXT was not supplied.")
    path, info = generate_private_voiceover(
        script, args.output, asr_hotwords=os.environ.get("ASR_HOTWORDS", "")
    )
    print("Private Qwen3 narration bridge passed exact transcript and word-timing validation.")
    print("Word timings: " + str(info["word_timing_count"]))
    print("Private transfer branch: " + str(info.get("private_transfer_branch") or "verified in the private repository"))
    print("Temporary WAV: " + str(path))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PrivateVoiceBridgeError as exc:
        print("::error::" + str(exc), file=sys.stderr)
        raise SystemExit(1)
