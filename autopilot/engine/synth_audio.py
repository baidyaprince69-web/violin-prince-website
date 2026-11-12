"""Quiet non-violin ambient fallback for drafts without an approved recording.

This intentionally does not imitate a bowed violin. A real creator-recorded
violin take is preferred and is loaded by the main pipeline when available.
"""
from array import array
import hashlib
import math
import wave
from pathlib import Path

SAMPLE_RATE = 24000
DURATION_SECONDS = 24

CHORDS = (
    (50, 57, 62, 65),  # D minor
    (46, 53, 58, 62),  # B-flat major
    (41, 48, 53, 57),  # F major
    (48, 55, 60, 64),  # C major
)


def midi_hz(note: int) -> float:
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def smoothstep(value: float) -> float:
    value = max(0.0, min(1.0, value))
    return value * value * (3.0 - 2.0 * value)


def create_ambient_fallback(output_path: Path, seed_text: str = "") -> Path:
    """Write a soft 24-second ambient chord bed with no fake violin lead."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    seed = int.from_bytes(hashlib.sha256(seed_text.encode("utf-8")).digest()[:2], "big")
    rotate = seed % len(CHORDS)
    chords = CHORDS[rotate:] + CHORDS[:rotate]

    frame_count = SAMPLE_RATE * DURATION_SECONDS
    pcm = array("h")
    peak = 0.0

    for frame in range(frame_count):
        t = frame / SAMPLE_RATE
        section = min(int(t // 6.0), len(chords) - 1)
        local = t - section * 6.0
        next_chord = chords[(section + 1) % len(chords)]
        blend = smoothstep((local - 5.0) / 1.0)
        edge = smoothstep(t / 1.1) * smoothstep((DURATION_SECONDS - t) / 1.4)

        pad = 0.0
        for chord, weight in ((chords[section], 1.0 - blend), (next_chord, blend)):
            for note_index, midi_note in enumerate(chord):
                frequency = midi_hz(midi_note)
                phase = 2.0 * math.pi * frequency * t + note_index * 0.19
                tone = (
                    math.sin(phase)
                    + 0.12 * math.sin(2.0 * phase)
                    + 0.035 * math.sin(3.0 * phase)
                )
                pad += weight * tone * (0.62 if note_index < 2 else 0.42)

        slow_breath = 0.96 + 0.04 * math.sin(2.0 * math.pi * 0.07 * t)
        sample = pad * 0.018 * edge * slow_breath
        pan = 0.012 * math.sin(2.0 * math.pi * 0.035 * t)
        left = sample * (1.0 + pan)
        right = sample * (1.0 - pan)
        peak = max(peak, abs(left), abs(right))
        pcm.append(int(max(-1.0, min(1.0, left)) * 32767))
        pcm.append(int(max(-1.0, min(1.0, right)) * 32767))

    if peak > 0:
        scale = min(1.0, 0.32 / peak)
        for index in range(len(pcm)):
            pcm[index] = int(pcm[index] * scale)

    with wave.open(str(output_path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(pcm.tobytes())

    return output_path


def create_original_soundtrack(output_path: Path, seed_text: str = "") -> Path:
    """Backward-compatible alias for the non-violin ambient fallback."""
    return create_ambient_fallback(output_path, seed_text=seed_text)
