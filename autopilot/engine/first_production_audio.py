"""Create the complete first-production narration, CC0 violin bed and final mix."""
from __future__ import annotations

import json
import math
import subprocess
import sys
from pathlib import Path

import numpy as np
import soundfile as sf

ENGINE = Path(__file__).resolve().parent
sys.path.insert(0, str(ENGINE))

from voiceover import synthesize_voiceover, write_srt
from violin_sampler import create_sampled_violin_bed

SCRIPT = (
    "A violin's sound begins when the bow sets a string moving. "
    "The bridge carries that vibration into the wooden body. "
    "Its plates and inner air resonate, shaping the tone and projecting sound through the f-holes. "
    "Four strings become a voice."
)
TITLE = "How a Violin Makes Sound"


def run(command: list[str], label: str, timeout: int = 180):
    result = subprocess.run(command, capture_output=True, text=True, timeout=timeout, check=False)
    if result.returncode:
        detail = (result.stderr or result.stdout or "No diagnostic")[-2500:]
        raise RuntimeError(f"{label} failed: {detail}")
    return result


def create_sfx(path: Path, duration: float = 24.0, sample_rate: int = 48000):
    """Create restrained original whooshes and soft impacts for shot transitions."""
    frames = int(duration * sample_rate)
    mix = np.zeros((frames, 2), dtype=np.float32)
    rng = np.random.default_rng(271128)

    def add_impact(start: float, strength: float):
        length = int(1.15 * sample_rate)
        start_index = int(start * sample_rate)
        end_index = min(frames, start_index + length)
        count = end_index - start_index
        if count <= 0:
            return
        t = np.arange(count, dtype=np.float32) / sample_rate
        envelope = np.exp(-t * 4.8)
        tone = (
            np.sin(2 * np.pi * 92.0 * t)
            + 0.28 * np.sin(2 * np.pi * 138.0 * t)
        ) * envelope
        noise = rng.normal(0.0, 1.0, count).astype(np.float32)
        # A short moving average softens the noise into an airy cinematic accent.
        kernel = np.ones(120, dtype=np.float32) / 120.0
        airy = np.convolve(noise, kernel, mode="same")
        rise = np.sin(np.pi * np.clip(t / 1.15, 0.0, 1.0)) ** 1.5
        signal = strength * (0.075 * tone + 0.06 * airy * rise)
        pan = (-0.20, 0.10, 0.20, -0.08)[int(start) % 4]
        mix[start_index:end_index, 0] += signal * math.sqrt((1 - pan) * 0.5)
        mix[start_index:end_index, 1] += signal * math.sqrt((1 + pan) * 0.5)

    for start, strength in ((0.12, 0.45), (5.6, 0.30), (10.2, 0.30), (15.3, 0.28), (19.0, 0.25), (22.4, 0.35)):
        add_impact(start, strength)

    peak = float(np.max(np.abs(mix)))
    if peak > 0:
        mix *= min(1.0, 0.28 / peak)
    sf.write(str(path), mix, sample_rate, subtype="PCM_16")
    return path


def main():
    output = Path(sys.argv[1] if len(sys.argv) > 1 else "work/first-production").expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)

    script_path = output / "production-script.txt"
    script_path.write_text(
        f"{TITLE}\n\nNarration:\n{SCRIPT}\n\n"
        "Visual direction:\n"
        "A real imported violin mesh in a midnight-blue studio. A slow three-quarter reveal, "
        "a close move toward the bridge, a sweep past the f-holes, a scroll detail, and a final hero shot. "
        "The bow, camera, 3D title cards, dust and resonance rings are animated inside Blender.\n\n"
        "Audio disclosure:\n"
        "Narration is synthetic Kokoro speech. The instrumental is a newly arranged phrase rendered "
        "from a checksum-verified CC0 violin sample library. It is not a live recording by the creator.\n",
        encoding="utf-8",
    )

    narration_path = output / "narration.wav"
    narration_path, narration_info = synthesize_voiceover(SCRIPT, narration_path)
    captions_path = output / "captions.srt"
    write_srt(narration_info["subtitle_cues"], captions_path)

    music_path = output / "cc0-violin-music.wav"
    music_path, music_info = create_sampled_violin_bed(
        music_path,
        seed_text="violin-prince-first-production:how-a-violin-makes-sound:2026-11-15",
    )

    sfx_path = output / "cinematic-sound-effects.wav"
    create_sfx(sfx_path)

    mixed_path = output / "final-audio-mix.wav"
    filters = (
        "[1:a]volume=0.22,lowpass=f=10500,"
        "afade=t=in:st=0:d=0.65,afade=t=out:st=22.0:d=2.0[bed];"
        "[0:a]highpass=f=75,lowpass=f=11500,"
        "acompressor=threshold=0.11:ratio=2.7:attack=10:release=140:makeup=1.55[voice];"
        "[2:a]volume=0.20[sfx];"
        "[bed][voice]sidechaincompress=threshold=0.025:ratio=4:attack=18:release=280[ducked];"
        "[ducked][voice][sfx]amix=inputs=3:duration=longest:normalize=0,"
        "alimiter=limit=0.92[out]"
    )
    run([
        "ffmpeg", "-y", "-hide_banner", "-loglevel", "error",
        "-i", str(narration_path), "-i", str(music_path), "-i", str(sfx_path),
        "-filter_complex", filters, "-map", "[out]",
        "-ar", "48000", "-ac", "2", "-c:a", "pcm_s16le", str(mixed_path),
    ], "Narration/music mix", timeout=180)

    report = {
        "title": TITLE,
        "script": SCRIPT,
        "narration": {
            "file": narration_path.name,
            "engine": narration_info["engine"],
            "voice": narration_info["voice"],
            "license": narration_info["model_license"],
            "duration_seconds": narration_info["duration_seconds"],
            "word_count": narration_info["word_count"],
            "word_timing_count": narration_info["word_timing_count"],
        },
        "music": {
            "file": music_path.name,
            "origin": music_info["audio_source"],
            "license": music_info["license"],
            "source_library": music_info["source_library"],
            "attribution": music_info["attribution"],
            "sample_bank_revision": music_info["sample_bank_revision"],
            "zones_used": music_info["zones_used"],
        },
        "sound_effects": {"file": sfx_path.name, "origin": "original procedural effects"},
        "final_mix": {"file": mixed_path.name, "sample_rate": 48000, "channels": 2},
        "captions": captions_path.name,
    }
    (output / "audio-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
