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
PAUSE_SECONDS = 0.22
# A measured pace keeps the complete narration audible near the 24-second finale.
NARRATION_SPEED = 1.15


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


def _ass_timestamp(seconds: float) -> str:
    centiseconds = max(0, int(round(float(seconds) * 100)))
    hours, remainder = divmod(centiseconds, 360000)
    minutes, remainder = divmod(remainder, 6000)
    whole_seconds, cs = divmod(remainder, 100)
    return f"{hours}:{minutes:02}:{whole_seconds:02}.{cs:02}"


def _ass_escape(value: str) -> str:
    return (
        str(value or "").replace("\\", "\\\\")
        .replace("{", "\\{").replace("}", "\\}")
        .replace("\n", " ").replace("\r", " ")
    )


def write_karaoke_ass(
    word_cues: list[dict],
    output_path: str | Path,
    *,
    width: int = 720,
    height: int = 1280,
    words_per_caption: int = 2,
) -> Path:
    """Write ASS karaoke captions; the gold word follows Kokoro's native timestamps."""
    if not isinstance(word_cues, list) or not word_cues:
        raise ValueError("Word-level narration timings are required for karaoke captions.")
    words_per_caption = max(1, min(int(words_per_caption), 3))
    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)
    header = [
        "[Script Info]",
        "Title: Violin Prince word-synchronised captions",
        "ScriptType: v4.00+",
        f"PlayResX: {int(width)}",
        f"PlayResY: {int(height)}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,MarginL,MarginR,MarginV,Encoding",
        "Style: Karaoke,DejaVu Sans,48,&H0000C8E4,&H00F4F0E8,&H00101925,&H8008101A,1,0,0,0,100,100,0,0,1,3,1,2,66,66,218,1",
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]
    groups: list[list[dict]] = []
    current: list[dict] = []
    current_sentence = None
    for cue in word_cues:
        text = str(cue.get("text") or "").strip()
        start = float(cue.get("start", -1))
        end = float(cue.get("end", -1))
        if not text or start < 0 or end <= start:
            raise ValueError("Invalid model-native word cue; refusing guessed caption timing.")
        sentence = cue.get("sentence_index", 0)
        if current and (sentence != current_sentence or len(current) >= words_per_caption):
            groups.append(current)
            current = []
        current_sentence = sentence
        current.append(cue)
    if current:
        groups.append(current)

    events = []
    for group_index, group in enumerate(groups):
        start = float(group[0]["start"])
        last_end = float(group[-1]["end"])
        following_start = float(groups[group_index + 1][0]["start"]) if group_index + 1 < len(groups) else last_end + 0.20
        end = min(last_end + 0.18, following_start)
        if end <= start:
            end = last_end
        fragments = []
        for index, cue in enumerate(group):
            duration_cs = max(1, int(round((float(cue["end"]) - float(cue["start"])) * 100)))
            word = _ass_escape(cue["text"])
            trailing_space = " " if index < len(group) - 1 else ""
            fragments.append(f"{{\\k{duration_cs}}}{word}{trailing_space}")
        events.append(
            f"Dialogue: 0,{_ass_timestamp(start)},{_ass_timestamp(end)},Karaoke,,0,0,0,,{''.join(fragments)}"
        )
    if not events:
        raise ValueError("No valid karaoke caption events were created.")
    target.write_text("\n".join(header + events) + "\n", encoding="utf-8")
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

        for result in pipeline(sentence, voice=VOICE, speed=NARRATION_SPEED):
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
        "speed": NARRATION_SPEED,
        "language": "English (American)",
        "voice_type": "synthetic_not_voice_cloned",
        "duration_seconds": round(float(info.duration), 2),
        "word_count": len(word_cues),
        "sample_rate": int(info.samplerate),
        "subtitle_cues": sentence_cues,
        "word_cues": word_cues,
        "word_timing_method": "Kokoro model-native token timestamps",
        "word_timing_count": len(word_cues),
        "word_sync_status": "passed",
    }
