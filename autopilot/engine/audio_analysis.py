"""Dependency-light beat/onset analysis from decoded audio samples."""
from __future__ import annotations

from pathlib import Path
import subprocess
from typing import Any

import numpy as np


def _empty_result(duration: float, sample_rate: int, reason: str) -> dict[str, Any]:
    return {
        "status": "low_confidence",
        "source": "decoded_audio",
        "duration_seconds": round(float(duration), 4),
        "sample_rate": int(sample_rate),
        "bpm": None,
        "confidence": 0.0,
        "beat_times": [],
        "downbeats": [],
        "onsets": [],
        "reason": reason,
    }


def _spectral_flux(samples: np.ndarray, sample_rate: int, *, fft_size: int = 2048) -> tuple[np.ndarray, float]:
    hop = max(128, int(sample_rate * 0.01))
    if len(samples) < fft_size:
        return np.zeros(0, dtype=np.float32), hop
    frames = np.lib.stride_tricks.sliding_window_view(samples, fft_size)[::hop]
    window = np.hanning(fft_size).astype(np.float32)
    spectrum = np.abs(np.fft.rfft(frames * window, axis=1)).astype(np.float32)
    log_spectrum = np.log1p(spectrum)
    difference = np.maximum(0.0, np.diff(log_spectrum, axis=0, prepend=log_spectrum[:1]))
    flux = np.sqrt(np.mean(difference * difference, axis=1) + 1e-12)
    if len(flux) >= 5:
        kernel = np.asarray([1, 2, 3, 2, 1], dtype=np.float32) / 9.0
        flux = np.convolve(flux, kernel, mode="same")
    return flux.astype(np.float32), float(hop)


def analyse_audio_file(
    path: str | Path,
    *,
    known_bpm: float | None = None,
    minimum_bpm: float = 60.0,
    maximum_bpm: float = 200.0,
) -> dict[str, Any]:
    """Decode the real track, estimate tempo from spectral flux, and return confidence."""
    import soundfile as sf

    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"Audio file does not exist: {source}")
    decode_backend = "soundfile"
    try:
        samples, sample_rate = sf.read(source, dtype="float32", always_2d=True)
        if samples.ndim != 2 or samples.shape[0] == 0 or sample_rate <= 0:
            raise ValueError("SoundFile returned no decoded audio samples.")
        mono = np.mean(samples, axis=1, dtype=np.float32)
    except Exception as soundfile_error:
        # Some creator uploads use codecs not supported by the installed
        # libsndfile. FFmpeg is already a production dependency, so decode the
        # actual compressed audio to mono PCM rather than substituting a beat map.
        try:
            decoded = subprocess.run(
                [
                    "ffmpeg", "-v", "error", "-i", str(source), "-vn",
                    "-ac", "1", "-ar", "22050", "-f", "f32le", "pipe:1",
                ],
                capture_output=True,
                timeout=120,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(
                "Audio could not be decoded by SoundFile or the FFmpeg fallback."
            ) from soundfile_error
        if decoded.returncode != 0 or not decoded.stdout:
            message = decoded.stderr.decode("utf-8", errors="replace")[-500:]
            raise RuntimeError("FFmpeg audio decoding failed: " + message) from soundfile_error
        mono = np.frombuffer(decoded.stdout, dtype="<f4").copy()
        sample_rate = 22050
        if mono.size == 0:
            return _empty_result(0.0, sample_rate, "ffmpeg_decode_returned_no_samples")
        decode_backend = "ffmpeg"
    duration = mono.shape[0] / float(sample_rate)
    finite = np.isfinite(mono)
    if not finite.all():
        return _empty_result(duration, sample_rate, "decoded_audio_contains_non_finite_samples")
    rms = float(np.sqrt(np.mean(mono * mono)))
    peak = float(np.max(np.abs(mono)))
    if rms < 1e-5 or duration < 3.0:
        return _empty_result(duration, sample_rate, "audio_is_silent_or_too_short_for_tempo_analysis")

    if known_bpm is not None:
        try:
            bpm = float(known_bpm)
        except (TypeError, ValueError):
            bpm = None
        if bpm is not None and not minimum_bpm <= bpm <= maximum_bpm:
            bpm = None
    else:
        bpm = None

    if bpm is not None:
        period = 60.0 / bpm
        flux, hop = _spectral_flux(mono, sample_rate)
        phase = 0
        if len(flux) >= 5 and float(np.std(flux)) >= 1e-7:
            frames_per_second = float(sample_rate) / hop
            phase_frames = max(1, int(round(period * frames_per_second)))
            phase_scores = [
                float(np.sum(flux[offset::phase_frames]))
                for offset in range(min(phase_frames, len(flux)))
            ]
            phase = int(np.argmax(phase_scores)) if phase_scores else 0
        offset_seconds = phase * hop / float(sample_rate)
        beats = np.arange(offset_seconds, duration, period, dtype=np.float64)
        return {
            "status": "metadata_guided",
            "source": "declared_tempo_with_decoded_audio_phase",
            "decode_backend": decode_backend,
            "duration_seconds": round(duration, 4),
            "sample_rate": int(sample_rate),
            "bpm": round(bpm, 3),
            "confidence": 1.0,
            "beat_times": [round(float(value), 4) for value in beats],
            "downbeats": [round(float(value), 4) for value in beats[::4]],
            "onsets": [],
            "peak": round(peak, 6),
            "rms": round(rms, 6),
        }

    flux, hop = _spectral_flux(mono, sample_rate)
    if len(flux) < 30 or float(np.std(flux)) < 1e-7:
        return _empty_result(duration, sample_rate, "spectral_flux_has_insufficient_variation")

    centred = flux - float(np.mean(flux))
    nfft = 1 << (len(centred) * 2 - 1).bit_length()
    power = np.fft.rfft(centred, n=nfft)
    autocorrelation = np.fft.irfft(power * np.conjugate(power), n=nfft)[:len(centred)]
    if autocorrelation[0] <= 1e-12:
        return _empty_result(duration, sample_rate, "onset_envelope_has_no_periodicity")
    autocorrelation /= autocorrelation[0]

    frames_per_second = float(sample_rate) / hop
    min_lag = max(1, int(frames_per_second * 60.0 / maximum_bpm))
    max_lag = min(len(autocorrelation) - 2, int(frames_per_second * 60.0 / minimum_bpm))
    if max_lag <= min_lag:
        return _empty_result(duration, sample_rate, "track_is_too_short_for_tempo_search")
    search = autocorrelation[min_lag:max_lag + 1]
    best_lag = int(np.argmax(search)) + min_lag
    strength = float(autocorrelation[best_lag])
    baseline = float(np.median(search))
    contrast = max(0.0, (strength - baseline) / max(0.08, 1.0 - baseline))
    confidence = float(np.clip(contrast * 1.45, 0.0, 1.0))
    bpm = 60.0 * frames_per_second / best_lag
    period = 60.0 / bpm

    # Choose phase by maximizing onset energy at each offset within one period.
    phase_frames = max(1, best_lag)
    phase_scores = np.asarray([
        float(np.sum(flux[offset::phase_frames]))
        for offset in range(phase_frames)
    ])
    phase = int(np.argmax(phase_scores))
    offset_seconds = phase * hop / float(sample_rate)
    beat_times = np.arange(offset_seconds, duration, period, dtype=np.float64)

    threshold = float(np.mean(flux) + 0.65 * np.std(flux))
    peaks = []
    minimum_gap = max(1, int(0.09 * frames_per_second))
    last = -minimum_gap
    for index in range(1, len(flux) - 1):
        if index - last >= minimum_gap and flux[index] >= threshold and flux[index] >= flux[index - 1] and flux[index] > flux[index + 1]:
            peaks.append(round(index * hop / float(sample_rate), 4))
            last = index

    if confidence < 0.28:
        result = _empty_result(duration, sample_rate, "tempo_periodicity_below_confidence_threshold")
        result.update({"confidence": round(confidence, 4), "onsets": peaks, "peak": round(peak, 6), "rms": round(rms, 6)})
        return result
    return {
        "status": "analysed",
        "source": "decoded_audio_spectral_flux_autocorrelation",
        "decode_backend": decode_backend,
        "duration_seconds": round(duration, 4),
        "sample_rate": int(sample_rate),
        "bpm": round(float(bpm), 3),
        "confidence": round(confidence, 4),
        "beat_times": [round(float(value), 4) for value in beat_times],
        "downbeats": [round(float(value), 4) for value in beat_times[::4]],
        "onsets": peaks,
        "peak": round(peak, 6),
        "rms": round(rms, 6),
    }
