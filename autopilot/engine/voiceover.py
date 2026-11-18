"""Voiceover timing helpers and fail-closed own-voice production gate.

Caption timing is accepted only when it comes from model-native word cues.
This module does not generate fallback narration while the creator's own
voice provider is untested or unapproved.
"""
from __future__ import annotations

import re
import textwrap
from pathlib import Path

SAMPLE_RATE = 24000


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
    """Write sentence-level subtitles for players without ASS support."""
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
    """Write ASS karaoke captions from validated model-native word timestamps."""
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


class OwnVoiceRequiredError(RuntimeError):
    """Raised while production narration is locked pending approved own-voice cloning."""


def require_approved_own_voice() -> None:
    """Keep production closed until the private Qwen3 narration bridge passes its end-to-end test.

    The user has approved the sample, but the complete production narration,
    transcript verification, word timings, and authenticated handoff must pass
    before this gate can be opened. No environment flag can bypass this hold.
    """
    raise OwnVoiceRequiredError(
        "Production is locked: the private Qwen3 narration bridge has not passed "
        "its complete end-to-end test. Research, visuals and rendering are stopped "
        "until the full narration handoff is verified."
    )


def synthesize_voiceover(text: str, output_path: str | Path) -> tuple[Path, dict]:
    """Generate narration through the private Qwen3 worker after the global gate opens."""
    require_approved_own_voice()
    from private_voice_client import generate_private_voiceover
    return generate_private_voiceover(text, output_path)
