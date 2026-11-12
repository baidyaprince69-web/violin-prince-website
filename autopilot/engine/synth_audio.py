"""Generate a short, original synthetic string-style soundtrack.

This is algorithmically composed and synthesised from oscillators. It is not a
recording of a human violin performance and uses no third-party samples.
"""
from array import array
import hashlib
import math
import wave
from pathlib import Path


SAMPLE_RATE = 22050
DURATION_SECONDS = 24


def midi_hz(note: int) -> float:
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def create_original_soundtrack(output_path: Path, seed_text: str = "") -> Path:
    """Write an original 24-second bowed-string-like instrumental WAV."""
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    seed = int.from_bytes(hashlib.sha256(seed_text.encode("utf-8")).digest()[:2], "big")
    melody = [62, 65, 69, 74, 72, 69, 67, 65, 62, 65, 67, 69, 70, 69, 65, 62]
    rotate = seed % len(melody)
    melody = melody[rotate:] + melody[:rotate]

    chords = [
        (50, 57, 62),  # D minor
        (46, 53, 58),  # B-flat major
        (41, 48, 53),  # F major
        (48, 55, 60),  # C major
    ]
    chord_rotate = (seed // 7) % len(chords)
    chords = chords[chord_rotate:] + chords[:chord_rotate]

    frames = SAMPLE_RATE * DURATION_SECONDS
    pcm = array("h")
    peak = 0.0

    for frame in range(frames):
        t = frame / SAMPLE_RATE

        # A slow, singing lead with gentle vibrato and a harmonic-rich timbre.
        note_index = min(int(t / 1.5), len(melody) - 1)
        note_local = t - note_index * 1.5
        note_envelope = max(0.0, min(1.0, note_local / 0.14, (1.5 - note_local) / 0.28))
        base_freq = midi_hz(melody[note_index])
        vibrato = 1.0 + 0.0032 * math.sin(2.0 * math.pi * 5.1 * t)
        phase = 2.0 * math.pi * base_freq * vibrato * t
        lead = (
            1.00 * math.sin(phase)
            + 0.43 * math.sin(2.0 * phase + 0.12)
            + 0.20 * math.sin(3.0 * phase + 0.31)
            + 0.09 * math.sin(4.0 * phase + 0.55)
        )
        lead *= 0.24 * note_envelope

        # A quiet sustained pad gives the melody harmonic support.
        chord = chords[min(int(t / 6.0), 3)]
        chord_local = t % 6.0
        chord_envelope = max(0.0, min(1.0, chord_local / 0.65, (6.0 - chord_local) / 0.75))
        pad = 0.0
        for index, midi_note in enumerate(chord):
            frequency = midi_hz(midi_note - 12)
            pad += math.sin(2.0 * math.pi * frequency * t + index * 0.37) * (0.55 if index == 0 else 0.35)
        pad *= 0.105 * chord_envelope

        # A soft upper shimmer, kept low so it does not compete with narration.
        shimmer = 0.025 * math.sin(2.0 * math.pi * midi_hz(86) * t) * math.sin(math.pi * min(1.0, t / 24.0))
        edge = max(0.0, min(1.0, t / 0.75, (DURATION_SECONDS - t) / 1.1))
        sample = (lead + pad + shimmer) * edge

        # Very slight stereo movement; no clipping or external audio samples.
        pan = 0.025 * math.sin(2.0 * math.pi * 0.08 * t)
        left = sample * (1.0 + pan)
        right = sample * (1.0 - pan)
        peak = max(peak, abs(left), abs(right))
        pcm.append(int(max(-1.0, min(1.0, left)) * 32767))
        pcm.append(int(max(-1.0, min(1.0, right)) * 32767))

    if peak > 0:
        scale = min(1.0, 0.82 / peak)
        for index in range(len(pcm)):
            pcm[index] = int(pcm[index] * scale)

    with wave.open(str(output_path), "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(SAMPLE_RATE)
        output.writeframes(pcm.tobytes())

    return output_path
