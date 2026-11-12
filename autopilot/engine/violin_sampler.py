"""CC0 multisampled solo-violin bed renderer.

Uses real recorded violin notes from String Studio / VSCO 2 CE, not oscillator
synthesis. The melody is newly arranged for the short. If sample retrieval fails,
the caller can safely choose the ambient fallback.
"""
from __future__ import annotations

import hashlib
import io
import json
import math
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import numpy as np
import requests
import soundfile as sf

SAMPLE_REPO = "AEmotionStudio/stringstudio-violin-samples"
SAMPLE_REVISION = "1e4e0ca"
BASE_URL = f"https://huggingface.co/{SAMPLE_REPO}/resolve/{SAMPLE_REVISION}/"
SAMPLE_RATE = 24000
DURATION_SECONDS = 24
BPM = 80
BEAT_SECONDS = 60.0 / BPM
CACHE_ROOT = Path(os.environ.get(
    "VIOLIN_SAMPLE_CACHE",
    str(Path.home() / ".cache" / "violin-prince" / "cc0-solo-violin-v1"),
))

# Two 16-beat phrases in D minor. The second phrase resolves the first.
PHRASE_A = (
    (62, 2, 60), (65, 1, 58), (67, 1, 64), (69, 2, 72),
    (72, 1, 78), (70, 1, 66), (69, 2, 70), (67, 1, 64),
    (65, 1, 60), (62, 2, 58), (65, 1, 68), (67, 1, 72),
)
PHRASE_B = (
    (65, 2, 64), (69, 1, 72), (72, 1, 78), (74, 2, 82),
    (77, 1, 88), (74, 1, 78), (72, 2, 76), (69, 1, 70),
    (67, 1, 66), (65, 2, 64), (62, 1, 60), (62, 1, 58),
)


def _get_json(url: str) -> dict[str, Any]:
    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            response = requests.get(url, timeout=(7, 25))
            response.raise_for_status()
            value = response.json()
            if not isinstance(value, dict):
                raise ValueError("Violin sample manifest must be a JSON object.")
            return value
        except (requests.RequestException, ValueError) as exc:
            last_error = exc
    raise RuntimeError(f"Violin sample manifest could not be downloaded: {last_error}")


def _load_manifest() -> dict[str, Any]:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    target = CACHE_ROOT / "manifest.json"
    if target.is_file():
        try:
            manifest = json.loads(target.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            target.unlink(missing_ok=True)
            manifest = None
    else:
        manifest = None

    if manifest is None:
        manifest = _get_json(BASE_URL + "manifest.json")
        temporary = target.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        temporary.replace(target)

    if manifest.get("instrument") != "violin" or manifest.get("license") != "CC0-1.0":
        raise RuntimeError("The violin sample pack did not pass its instrument/license check.")
    if not isinstance(manifest.get("zones"), list) or not manifest["zones"]:
        raise RuntimeError("The violin sample manifest contains no mapped sample zones.")
    return manifest


def _choose_zone(zones: list[dict[str, Any]], note: int, velocity: int) -> dict[str, Any]:
    matches = [
        zone for zone in zones
        if int(zone.get("lowPitch", 0)) <= note <= int(zone.get("highPitch", 0))
        and int(zone.get("lowVelocity", 0)) <= velocity <= int(zone.get("highVelocity", 127))
    ]
    if not matches:
        raise RuntimeError(f"No violin sample zone covers MIDI note {note}, velocity {velocity}.")
    return min(matches, key=lambda zone: abs(int(zone.get("rootPitch", note)) - note))


def _safe_sample_path(relative: str) -> Path:
    path = Path(relative)
    if path.is_absolute() or ".." in path.parts:
        raise RuntimeError("Violin sample manifest contains an unsafe file path.")
    return CACHE_ROOT / path


def _download_sample(relative: str, expected_sha256: str, expected_size: int) -> bytes:
    target = _safe_sample_path(relative)
    if target.is_file():
        payload = target.read_bytes()
        if len(payload) == expected_size and hashlib.sha256(payload).hexdigest() == expected_sha256:
            return payload
        target.unlink(missing_ok=True)

    last_error: Exception | None = None
    for _attempt in range(2):
        try:
            response = requests.get(BASE_URL + relative, timeout=(7, 30))
            response.raise_for_status()
            payload = response.content
            if len(payload) != expected_size:
                raise RuntimeError(f"Unexpected size for violin sample {relative}.")
            if hashlib.sha256(payload).hexdigest() != expected_sha256:
                raise RuntimeError(f"Checksum verification failed for violin sample {relative}.")
            target.parent.mkdir(parents=True, exist_ok=True)
            temporary = target.with_suffix(target.suffix + ".tmp")
            temporary.write_bytes(payload)
            temporary.replace(target)
            return payload
        except (requests.RequestException, RuntimeError) as exc:
            last_error = exc
    raise RuntimeError(f"Violin sample download failed for {relative}: {last_error}")


def _events(seed_text: str) -> list[tuple[int, int, int, int]]:
    """Return (note, velocity, start_beat, duration_beats) for a 24-second phrase."""
    digest = hashlib.sha256(seed_text.encode("utf-8")).digest()
    transpose = (0, 2, 4)[digest[0] % 3]
    first = [(note + transpose, velocity, beats) for note, beats, velocity in PHRASE_A]
    second = [(note + transpose, velocity, beats) for note, beats, velocity in PHRASE_B]

    # Small deterministic phrasing differences, without changing the 32-beat length.
    if digest[1] % 2:
        second = second[2:] + second[:2]
    if digest[2] % 2:
        first = first[:6] + [(n, max(52, v - 6), b) for n, v, b in first[6:]]

    events: list[tuple[int, int, int, int]] = []
    beat = 0
    for note, velocity, beats in first + second:
        events.append((note, velocity, beat, beats))
        beat += beats
    if beat != 32:
        raise RuntimeError(f"Violin arrangement is {beat} beats; expected 32.")
    return events


def render_from_sample_arrays(
    output_path: str | Path,
    manifest: dict[str, Any],
    samples: dict[str, tuple[np.ndarray, int]],
    seed_text: str = "",
) -> Path:
    """Render offline from decoded sample arrays; this keeps CI tests network-free."""
    zones = manifest.get("zones", [])
    events = _events(seed_text)
    total_frames = SAMPLE_RATE * DURATION_SECONDS
    mix = np.zeros((total_frames, 2), dtype=np.float32)

    for event_index, (note, velocity, start_beat, beats) in enumerate(events):
        zone = _choose_zone(zones, note, velocity)
        relative = str(zone["file"])
        if relative not in samples:
            raise RuntimeError(f"Decoded violin sample is missing: {relative}")
        source, source_rate = samples[relative]
        source = np.asarray(source, dtype=np.float32).reshape(-1)
        if source.size < 2048 or source_rate < 22050:
            raise RuntimeError(f"Violin sample is too short or has an invalid sample rate: {relative}")

        root_pitch = int(zone["rootPitch"])
        pitch_ratio = 2.0 ** ((note - root_pitch) / 12.0)
        start = int(round(start_beat * BEAT_SECONDS * SAMPLE_RATE))
        seconds = min(DURATION_SECONDS - start / SAMPLE_RATE, beats * BEAT_SECONDS + 0.035)
        frame_count = max(1, int(round(seconds * SAMPLE_RATE)))
        positions = np.arange(frame_count, dtype=np.float32) * (
            float(source_rate) / SAMPLE_RATE * pitch_ratio
        )
        positions = positions[positions <= len(source) - 1]
        if positions.size < 1024:
            raise RuntimeError(f"Violin sample ended too early for MIDI note {note}.")
        clip = np.interp(
            positions, np.arange(len(source), dtype=np.float32), source
        ).astype(np.float32)

        attack = min(int(0.045 * SAMPLE_RATE), len(clip) // 3)
        release = min(int(0.16 * SAMPLE_RATE), len(clip) // 3)
        envelope = np.ones(len(clip), dtype=np.float32)
        if attack:
            x = np.linspace(0.0, 1.0, attack, dtype=np.float32)
            envelope[:attack] = x * x * (3.0 - 2.0 * x)
        if release:
            x = np.linspace(0.0, 1.0, release, dtype=np.float32)
            envelope[-release:] *= 1.0 - (x * x * (3.0 - 2.0 * x))
        clip *= envelope

        pan = (-0.035, 0.035)[event_index % 2]
        left_gain = math.sqrt((1.0 - pan) * 0.5)
        right_gain = math.sqrt((1.0 + pan) * 0.5)
        velocity_gain = 0.58 + 0.22 * (velocity / 127.0)
        end = min(total_frames, start + len(clip))
        length = max(0, end - start)
        if length:
            mix[start:end, 0] += clip[:length] * velocity_gain * left_gain
            mix[start:end, 1] += clip[:length] * velocity_gain * right_gain

    fade_in = int(0.7 * SAMPLE_RATE)
    fade_out = int(1.1 * SAMPLE_RATE)
    x_in = np.linspace(0.0, 1.0, fade_in, dtype=np.float32)
    x_out = np.linspace(0.0, 1.0, fade_out, dtype=np.float32)
    mix[:fade_in] *= (x_in * x_in * (3.0 - 2.0 * x_in))[:, None]
    mix[-fade_out:] *= (1.0 - (x_out * x_out * (3.0 - 2.0 * x_out)))[:, None]

    peak = float(np.max(np.abs(mix))) if mix.size else 0.0
    if peak < 0.0005:
        raise RuntimeError("The sampled violin arrangement rendered silence.")
    mix *= min(1.0, 0.68 / peak)

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(target), mix, SAMPLE_RATE, subtype="PCM_16")
    return target


def create_sampled_violin_bed(
    output_path: str | Path, seed_text: str = ""
) -> tuple[Path, dict[str, Any]]:
    """Download only the note zones required, verify their hashes, then render."""
    manifest = _load_manifest()
    zones = manifest["zones"]
    events = _events(seed_text)
    chosen: dict[str, dict[str, Any]] = {}
    for note, velocity, _start, _beats in events:
        zone = _choose_zone(zones, note, velocity)
        chosen[str(zone["file"])] = zone

    def fetch_zone(zone: dict[str, Any]) -> tuple[str, bytes]:
        relative = str(zone["file"])
        payload = _download_sample(relative, str(zone["sha256"]), int(zone["sizeBytes"]))
        return relative, payload

    payloads: dict[str, bytes] = {}
    with ThreadPoolExecutor(max_workers=6) as pool:
        for relative, payload in pool.map(fetch_zone, chosen.values()):
            payloads[relative] = payload

    decoded: dict[str, tuple[np.ndarray, int]] = {}
    for relative, payload in payloads.items():
        audio, sample_rate = sf.read(io.BytesIO(payload), dtype="float32", always_2d=False)
        if audio.ndim == 2:
            audio = audio.mean(axis=1)
        decoded[relative] = (np.asarray(audio, dtype=np.float32), int(sample_rate))

    target = render_from_sample_arrays(output_path, manifest, decoded, seed_text=seed_text)
    info = {
        "audio_source": "sampled_violin_cc0",
        "license": manifest["license"],
        "source_library": manifest.get("sourceLibrary", "VSCO 2 Community Edition"),
        "attribution": manifest.get("attribution", "Versilian Studios"),
        "duration_seconds": DURATION_SECONDS,
        "sample_rate": SAMPLE_RATE,
        "zones_used": len(chosen),
        "sample_bank_revision": SAMPLE_REVISION,
    }
    return target, info
