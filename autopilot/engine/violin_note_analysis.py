"""Monophonic violin note-event analysis from the creator's decoded PCM recording.

This is a timing aid, not a replacement for musical/visual review. It returns no
invented arrangement: uncertain frames are discarded and the caller must fail
closed when too few reliable note events are found.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np


def analyse_violin_note_events(
    path: str | Path,
    *,
    minimum_pitch_hz: float = 175.0,
    maximum_pitch_hz: float = 2500.0,
    minimum_confidence: float = 0.70,
    minimum_duration_seconds: float = 0.075,
) -> dict[str, Any]:
    """Estimate fundamental pitches and contiguous note onsets in a solo violin WAV."""
    import soundfile as sf

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Violin recording does not exist: {source}")
    samples, sample_rate = sf.read(source, dtype="float32", always_2d=True)
    if samples.ndim != 2 or samples.shape[0] == 0 or sample_rate <= 0:
        raise ValueError("Violin recording contains no decoded PCM samples.")
    mono = np.mean(samples, axis=1, dtype=np.float32)
    if not np.isfinite(mono).all():
        raise ValueError("Violin recording contains non-finite PCM samples.")
    duration = len(mono) / float(sample_rate)
    peak = float(np.max(np.abs(mono))) if mono.size else 0.0
    if duration < 1.0 or peak < 1e-5:
        return {
            "status": "low_confidence",
            "source": "creator_uploaded_pcm_autocorrelation",
            "duration_seconds": round(duration, 4),
            "note_events": [],
            "reason": "recording_is_silent_or_too_short",
        }

    # Keep the analysis cost predictable while preserving the violin's useful
    # fundamental range. The source audio itself is never resampled or changed.
    stride = max(1, int(round(sample_rate / 22050.0)))
    analysis = mono[::stride].astype(np.float32, copy=False)
    rate = float(sample_rate) / stride
    frame_length = 4096
    hop_length = 441
    if len(analysis) < frame_length:
        return {
            "status": "low_confidence",
            "source": "creator_uploaded_pcm_autocorrelation",
            "duration_seconds": round(duration, 4),
            "note_events": [],
            "reason": "recording_is_too_short_for_pitch_analysis",
        }

    min_lag = max(2, int(np.floor(rate / maximum_pitch_hz)))
    max_lag = min(frame_length // 2, int(np.ceil(rate / minimum_pitch_hz)))
    window = np.hanning(frame_length).astype(np.float32)
    estimates: list[tuple[float, int | None, float, float]] = []

    for start in range(0, len(analysis) - frame_length + 1, hop_length):
        frame = analysis[start:start + frame_length]
        rms = float(np.sqrt(np.mean(frame * frame)))
        centre_time = (start + frame_length / 2.0) / rate
        if rms < max(1e-5, peak * 0.0015):
            estimates.append((centre_time, None, 0.0, rms))
            continue
        weighted = frame * window
        spectrum = np.fft.rfft(weighted, n=8192)
        autocorrelation = np.fft.irfft(spectrum * np.conjugate(spectrum), n=8192)[:max_lag + 2]
        if not np.isfinite(autocorrelation).all() or autocorrelation[0] <= 1e-10:
            estimates.append((centre_time, None, 0.0, rms))
            continue

        # YIN-style cumulative-mean-normalized difference. A first local
        # minimum avoids repeatedly choosing a strong second harmonic.
        difference = 2.0 * np.maximum(0.0, autocorrelation[0] - autocorrelation[1:max_lag + 1])
        cumulative = np.cumsum(difference) + 1e-12
        lags = np.arange(1, max_lag + 1, dtype=np.float64)
        normalized = difference * lags / cumulative
        valid = normalized[min_lag - 1:max_lag]
        if not valid.size:
            estimates.append((centre_time, None, 0.0, rms))
            continue
        local = np.where(valid < 0.20)[0]
        if local.size:
            tau = int(local[0] + min_lag)
            while tau < max_lag and normalized[tau] > normalized[tau + 1]:
                tau += 1
        else:
            tau = int(np.argmin(valid) + min_lag)
        confidence = float(np.clip(1.0 - normalized[tau - 1], 0.0, 1.0))
        if tau <= 1 or confidence < minimum_confidence:
            estimates.append((centre_time, None, confidence, rms))
            continue

        # Parabolic interpolation around the selected lag reduces semitone
        # quantization at the lower end of the violin register.
        index = tau - 1
        delta = 0.0
        if 1 <= index < len(normalized) - 1:
            left, centre, right = (float(normalized[index - 1]),
                                   float(normalized[index]),
                                   float(normalized[index + 1]))
            denominator = left - 2.0 * centre + right
            if abs(denominator) > 1e-9:
                delta = float(np.clip(0.5 * (left - right) / denominator, -0.5, 0.5))
        frequency = rate / (tau + delta)
        if not minimum_pitch_hz <= frequency <= maximum_pitch_hz:
            estimates.append((centre_time, None, confidence, rms))
            continue
        midi = int(round(69.0 + 12.0 * np.log2(frequency / 440.0)))
        estimates.append((centre_time, midi, confidence, rms))

    # Smooth short vibrato/estimator flicker without fabricating note changes.
    raw_notes = [entry[1] for entry in estimates]
    smoothed: list[int | None] = []
    for index, note in enumerate(raw_notes):
        neighbours = [
            value for value in raw_notes[max(0, index - 2):min(len(raw_notes), index + 3)]
            if value is not None
        ]
        if note is None or not neighbours:
            smoothed.append(None)
        else:
            smoothed.append(int(round(float(np.median(neighbours)))))

    runs: list[list[int]] = []
    current: list[int] = []
    last_note: int | None = None
    for index, note in enumerate(smoothed):
        if note is not None and note == last_note:
            current.append(index)
        else:
            if current:
                runs.append(current)
            current = [index] if note is not None else []
            last_note = note
    if current:
        runs.append(current)

    note_events: list[dict[str, Any]] = []
    for run in runs:
        start_index, end_index = run[0], run[-1]
        start_time = max(0.0, estimates[start_index][0] - frame_length / (2.0 * rate))
        end_time = min(duration, estimates[end_index][0] + frame_length / (2.0 * rate))
        note_duration = end_time - start_time
        confidences = [estimates[i][2] for i in run]
        mean_confidence = float(np.mean(confidences)) if confidences else 0.0
        if note_duration < minimum_duration_seconds or mean_confidence < minimum_confidence:
            continue
        rms_values = [estimates[i][3] for i in run]
        relative_level = float(np.mean(rms_values)) / max(peak, 1e-8)
        velocity = int(np.clip(round(38 + 88 * np.sqrt(relative_level)), 1, 127))
        note = smoothed[start_index]
        if note is None:
            continue
        note_events.append({
            "time": round(start_time, 4),
            "note": int(note),
            "velocity": velocity,
            "duration_seconds": round(note_duration, 4),
            "confidence": round(mean_confidence, 4),
            "frequency_hz": round(440.0 * (2.0 ** ((int(note) - 69) / 12.0)), 2),
        })

    return {
        "status": "passed" if len(note_events) >= 4 else "low_confidence",
        "source": "creator_uploaded_pcm_autocorrelation",
        "sample_rate": int(sample_rate),
        "duration_seconds": round(duration, 4),
        "frame_count": len(estimates),
        "note_event_count": len(note_events),
        "note_events": note_events,
        "reason": None if len(note_events) >= 4 else "fewer_than_four_reliable_note_events",
        "limitations": [
            "Monophonic fundamental estimate; overlapping/polyphonic passages may be rejected or misclassified.",
            "Pitch and articulation still require review against the creator's actual recording.",
        ],
    }
