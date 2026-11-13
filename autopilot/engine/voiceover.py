"""Free CPU text-to-speech for the Violin Prince cloud production runner.

Kokoro-82M model weights are Apache-2.0. Inference happens on a GitHub-hosted
runner, not on the user's computer. The selected voice is synthetic and does
not clone or imitate a real person.
"""
from __future__ import annotations

import re
import textwrap
from pathlib import Path

VOICE = "af_heart"
LANG_CODE = "a"  # American English
SAMPLE_RATE = 24000
PAUSE_SECONDS = 0.16


def split_sentences(text: str) -> list[str]:
    """Split a short narration into subtitle-friendly spoken sentences."""
    normalised = re.sub(r"\s+", " ", str(text or "")).strip()
    if not normalised:
        return []
    parts = re.split(r"(?<=[.!?])\s+", normalised)
    return [part.strip() for part in parts if part.strip()]


def _srt_timestamp(seconds: float) -> str:
    milliseconds = max(0, int(round(float(seconds) * 1000)))
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    whole_seconds, millis = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{whole_seconds:02},{millis:03}"


def write_srt(cues: list[dict], output_path: str | Path) -> Path:
    """Write sentence-timed subtitles using the actual TTS chunk durations."""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for index, cue in enumerate(cues, start=1):
        start = float(cue["start"])
        end = float(cue["end"])
        # Keep subtitle lines short enough to read quickly on a phone screen.
        # Shorter subtitle rows reduce line count and make captions easier to scan on phones.
        phrase = textwrap.fill(str(cue["text"]).strip(), width=24)
        if not phrase or end <= start:
            continue
        lines.extend([
            str(index),
            f"{_srt_timestamp(start)} --> {_srt_timestamp(end)}",
            phrase,
            "",
        ])
    if not lines:
        raise ValueError("No valid narration subtitle cues were supplied.")
    target.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return target


def word_cues_from_tokens(tokens, offset_seconds: float = 0.0,
                         chunk_duration: float | None = None) -> list[dict]:
    """Convert Kokoro token times into word cues with punctuation attached.

    Kokoro exposes start_ts/end_ts on English MToken objects after joining its
    predicted phoneme durations. Punctuation-only tokens are folded into the
    neighbouring word so punctuation never animates as a standalone caption.
    """
    cues: list[dict] = []
    offset = max(0.0, float(offset_seconds))
    limit = None if chunk_duration is None else max(0.0, float(chunk_duration))
    pending_prefix = ""
    opening_marks = set("([{“‘«") | {'"'}
    punctuation_only = re.compile(r"^[^\w\s]+$", re.UNICODE)
    apostrophe_suffix = re.compile(r"^['’][A-Za-z]+$")
    for token in tokens or []:
        text = str(getattr(token, "text", "") or "").strip()
        if not text:
            continue
        try:
            start = float(token.start_ts)
            end = float(token.end_ts)
        except (AttributeError, TypeError, ValueError):
            continue
        if not (start >= 0.0 and end > start):
            continue
        if limit is not None:
            start = min(start, limit)
            end = min(end, limit)
        if end - start < 0.001:
            continue
        absolute_start = round(offset + start, 3)
        absolute_end = round(offset + end, 3)

        if punctuation_only.fullmatch(text):
            if not cues or text[0] in opening_marks:
                pending_prefix += text
            else:
                cues[-1]["text"] += text
                cues[-1]["end"] = max(cues[-1]["end"], absolute_end)
            continue

        if cues and apostrophe_suffix.fullmatch(text):
            cues[-1]["text"] += text
            cues[-1]["end"] = max(cues[-1]["end"], absolute_end)
            continue

        if end - start < 0.015:
            continue
        cues.append({
            "start": absolute_start,
            "end": absolute_end,
            "text": pending_prefix + text,
        })
        pending_prefix = ""
    return cues


def synthesize_voiceover(text: str, output_path: str | Path) -> tuple[Path, dict]:
    """Generate a spoken narration WAV and sentence-level subtitle timings."""
    import numpy as np
    import soundfile as sf
    from kokoro import KPipeline

    narration = re.sub(r"\s+", " ", str(text or "")).strip()
    if not narration:
        raise ValueError("Narration script is empty.")
    word_count = len(re.findall(r"\b[\w’'-]+\b", narration))
    if not 30 <= word_count <= 48:
        raise ValueError("Narration must contain 30–48 spoken words.")

    sentences = split_sentences(narration)
    if not sentences:
        raise ValueError("Narration did not contain a speakable sentence.")

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    # CPU inference: no hosted speech API, GPU, or local PC process is used.
    pipeline = KPipeline(lang_code=LANG_CODE)
    audio_parts: list[np.ndarray] = []
    subtitle_cues: list[dict] = []
    word_cues: list[dict] = []
    cursor = 0
    pause = np.zeros(int(PAUSE_SECONDS * SAMPLE_RATE), dtype=np.float32)

    for sentence_index, sentence in enumerate(sentences):
        sentence_parts: list[np.ndarray] = []
        sentence_word_cues: list[dict] = []
        chunk_offset = 0.0
        for generated in pipeline(
            sentence,
            voice=VOICE,
            speed=0.90,
        ):
            # KPipeline.Result keeps the English MToken objects and their
            # start_ts/end_ts while remaining tuple-compatible with older code.
            audio = getattr(generated, "audio", None)
            if audio is None:
                try:
                    audio = generated[2]
                except (IndexError, TypeError):
                    audio = None
            if audio is None:
                continue
            samples = np.asarray(audio, dtype=np.float32).reshape(-1)
            if samples.size:
                chunk_duration = samples.size / SAMPLE_RATE
                sentence_word_cues.extend(
                    word_cues_from_tokens(
                        getattr(generated, "tokens", None),
                        offset_seconds=chunk_offset,
                        chunk_duration=chunk_duration,
                    )
                )
                sentence_parts.append(samples)
                chunk_offset += chunk_duration

        if not sentence_parts:
            raise RuntimeError("Kokoro returned no speech for a narration sentence.")

        spoken = np.concatenate(sentence_parts)
        if not np.isfinite(spoken).all():
            raise RuntimeError("Kokoro produced invalid audio samples.")
        peak_sentence = float(np.max(np.abs(spoken)))
        if peak_sentence < 0.002:
            raise RuntimeError("Kokoro produced effectively silent narration.")

        start = cursor / SAMPLE_RATE
        audio_parts.append(spoken)
        cursor += int(spoken.size)
        end = cursor / SAMPLE_RATE
        subtitle_cues.append({"start": round(start, 3), "end": round(end, 3), "text": sentence})
        for cue in sentence_word_cues:
            word_cues.append({
                "start": round(start + cue["start"], 3),
                "end": round(start + cue["end"], 3),
                "text": cue["text"],
            })

        if sentence_index < len(sentences) - 1:
            audio_parts.append(pause)
            cursor += int(pause.size)

    waveform = np.concatenate(audio_parts)
    duration = waveform.size / SAMPLE_RATE
    if duration > 21.5:
        raise RuntimeError(
            f"Narration is too long for the 24-second format ({duration:.1f}s). "
            "The planner must write a shorter script."
        )

    peak = float(np.max(np.abs(waveform)))
    if peak <= 0.002:
        raise RuntimeError("Generated narration is silent.")
    if peak > 0.95:
        waveform = waveform * (0.95 / peak)

    sf.write(str(target), waveform, SAMPLE_RATE, subtype="PCM_16")
    info = sf.info(str(target))
    if info.frames <= 0 or info.duration <= 0:
        raise RuntimeError("Narration WAV failed its post-write validation.")

    return target, {
        "engine": "Kokoro-82M",
        "model_license": "Apache-2.0",
        "voice": VOICE,
        "language": "English (American)",
        "voice_type": "synthetic_not_voice_cloned",
        "duration_seconds": round(float(info.duration), 2),
        "word_count": word_count,
        "speaking_speed": 0.90,
        "sample_rate": int(info.samplerate),
        "subtitle_cues": subtitle_cues,
        "word_cues": word_cues,
        "word_timing_method": (
            "kokoro_predicted_phoneme_durations"
            if word_cues else "unavailable_sentence_fallback"
        ),
    }
