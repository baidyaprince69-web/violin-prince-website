"""CPU text-to-speech with model-native word timings for Violin Prince.

Kokoro's English tokens carry start/end timestamps derived from the same
phoneme-duration prediction used to render the waveform. The renderer uses
those exact timings for word-synchronised captions rather than estimating
where words should appear.
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
    """Write sentence-level fallback subtitles for players without ASS support."""
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    for index, cue in enumerate(cues, start=1):
        start = float(cue["start"])
        end = float(cue["end"])
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


def _read_result_audio(result):
    """Read audio from current Kokoro Result objects or their tuple interface."""
    audio = getattr(result, "audio", None)
    if audio is not None:
        return audio
    try:
        return result[2]
    except (TypeError, IndexError, KeyError):
        return None


def synthesize_voiceover(text: str, output_path: str | Path) -> tuple[Path, dict]:
    """Generate narration, sentence cues, and Kokoro-native per-word timings."""
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
    pipeline = KPipeline(lang_code=LANG_CODE)

    audio_parts: list[np.ndarray] = []
    sentence_cues: list[dict] = []
    word_cues: list[dict] = []
    cursor_samples = 0
    pause = np.zeros(int(PAUSE_SECONDS * SAMPLE_RATE), dtype=np.float32)

    for sentence_index, sentence in enumerate(sentences):
        sentence_parts: list[np.ndarray] = []
        sentence_samples = 0
        sentence_start = cursor_samples / SAMPLE_RATE
        sentence_word_cues: list[dict] = []

        for result in pipeline(sentence, voice=VOICE, speed=1.0):
            raw_audio = _read_result_audio(result)
            if raw_audio is None:
                raise RuntimeError("Kokoro returned a chunk without audio.")
            samples = np.asarray(raw_audio, dtype=np.float32).reshape(-1)
            if samples.size == 0:
                continue
            if not np.isfinite(samples).all():
                raise RuntimeError("Kokoro produced invalid audio samples.")

            chunk_start = sentence_start + sentence_samples / SAMPLE_RATE
            tokens = getattr(result, "tokens", None) or []
            for token in tokens:
                token_text = str(getattr(token, "text", "") or "")
                whitespace = str(getattr(token, "whitespace", "") or "")
                start_ts = getattr(token, "start_ts", None)
                end_ts = getattr(token, "end_ts", None)

                if start_ts is None or end_ts is None:
                    # Punctuation tokens are not voiced and have no duration.
                    # Attach them to the preceding spoken word for exact text.
                    if token_text and sentence_word_cues and not re.search(r"\w", token_text):
                        sentence_word_cues[-1]["text"] += token_text
                        if whitespace:
                            sentence_word_cues[-1]["whitespace"] = whitespace
                    elif token_text and re.search(r"\w", token_text):
                        raise RuntimeError(
                            "Kokoro did not provide a timestamp for spoken token "
                            + repr(token_text) + ". Refusing guessed caption timing."
                        )
                    continue

                start = chunk_start + max(0.0, float(start_ts))
                end = chunk_start + max(0.0, float(end_ts))
                if end <= start:
                    raise RuntimeError(
                        "Kokoro returned a zero-length word timestamp for "
                        + repr(token_text) + "."
                    )
                if not re.search(r"\w", token_text):
                    continue

                sentence_word_cues.append({
                    "text": token_text,
                    "whitespace": whitespace,
                    "start": round(start, 4),
                    "end": round(end, 4),
                    "sentence_index": sentence_index,
                })

            sentence_parts.append(samples)
            sentence_samples += int(samples.size)

        if not sentence_parts:
            raise RuntimeError("Kokoro returned no speech for a narration sentence.")
        if not sentence_word_cues:
            raise RuntimeError(
                "Kokoro did not expose native word timings for sentence "
                + str(sentence_index + 1) + ". Word-synced captions are required."
            )

        spoken = np.concatenate(sentence_parts)
        peak_sentence = float(np.max(np.abs(spoken)))
        if peak_sentence < 0.002:
            raise RuntimeError("Kokoro produced effectively silent narration.")

        sentence_end = sentence_start + spoken.size / SAMPLE_RATE
        sentence_cues.append({
            "start": round(sentence_start, 4),
            "end": round(sentence_end, 4),
            "text": sentence,
        })
        word_cues.extend(sentence_word_cues)
        audio_parts.append(spoken)
        cursor_samples += int(spoken.size)

        if sentence_index < len(sentences) - 1:
            audio_parts.append(pause)
            cursor_samples += int(pause.size)

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

    # Confirm every sentence has a monotonically timed word sequence inside
    # that sentence's real audio interval. This is a render-blocking QA gate.
    for sentence_index, cue in enumerate(sentence_cues):
        rows = [item for item in word_cues if item["sentence_index"] == sentence_index]
        if not rows:
            raise RuntimeError(f"Sentence {sentence_index + 1} has no word timing data.")
        previous_end = float(cue["start"]) - 0.03
        for row in rows:
            if row["start"] < previous_end - 0.03 or row["end"] <= row["start"]:
                raise RuntimeError("Kokoro word timings are not monotonically ordered.")
            if row["start"] < float(cue["start"]) - 0.08 or row["end"] > float(cue["end"]) + 0.12:
                raise RuntimeError("A Kokoro word timestamp falls outside its spoken sentence.")
            previous_end = row["end"]

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
        "sample_rate": int(info.samplerate),
        "subtitle_cues": sentence_cues,
        "word_cues": word_cues,
        "word_timing_method": "Kokoro model-native token timestamps",
        "word_timing_count": len(word_cues),
        "word_sync_status": "passed",
    }
