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

from voiceover import synthesize_voiceover, write_srt, write_karaoke_ass
from violin_sampler import create_sampled_violin_bed

SCRIPT = (
    "Violin sound begins when bow hair grips a string. "
    "The bridge carries vibration into the maple body, where wood and air shape the tone. "
    "Sound leaves through the f-holes. "
    "Bow speed, pressure, and contact shape each phrase; the final note resolves as the camera returns to the instrument."
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
        "Six distinct full-frame Blender shots: hero reveal (0–3.5s), bow/string contact (3.5–7.5s), "
        "bridge vibration (7.5–12s), body resonance and f-holes (12–17s), scroll and pegs (17–20.5s), "
        "and a final hero resolve (20.5–24s). Every shot has its own framing and transition. "
        "Use the story-selected real downloaded model and exactly one bow rig.\n\n"
        "Audio disclosure:\n"
        "Narration is synthetic Kokoro speech. The instrumental is a newly arranged phrase rendered "
        "from a checksum-verified CC0 violin sample library. It is not a live recording by the creator.\n",
        encoding="utf-8",
    )

    narration_path = output / "narration.wav"
    narration_path, narration_info = synthesize_voiceover(SCRIPT, narration_path)
    captions_path = output / "captions.srt"
    write_srt(narration_info["subtitle_cues"], captions_path)
    karaoke_path = output / "captions.ass"
    write_karaoke_ass(narration_info["word_cues"], karaoke_path, width=720, height=1280, words_per_caption=2)
    word_timing_path = output / "word-timing.json"
    word_timing_path.write_text(
        json.dumps(narration_info["word_cues"], ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    if not 21.5 <= float(narration_info["duration_seconds"]) <= 22.4:
        raise RuntimeError(
            "Narration must finish between 21.5 and 22.4 seconds so the spoken final phrase "
            "reaches the closing shot. Revise the script or pacing; do not leave a long silent voice gap."
        )

    music_path = output / "cc0-violin-music.wav"
    music_path, music_info = create_sampled_violin_bed(
        music_path,
        seed_text="violin-prince-first-production:how-a-violin-makes-sound:2026-11-15",
    )

    sfx_path = output / "cinematic-sound-effects.wav"
    create_sfx(sfx_path)

    storyboard = {
        "title": TITLE,
        "duration_seconds": 24.0,
        "format": "9:16",
        "production_mode": "full-frame Blender 3D; story-selected real downloaded asset",
        "shots": [
            {"id": 1, "start": 0.0, "end": 3.5, "title": "The hero reveal", "camera": "three-quarter wide reveal", "visual": "complete violin with one visible bow rig", "transition_out": "match cut on bow direction"},
            {"id": 2, "start": 3.5, "end": 7.5, "title": "Bow meets the strings", "camera": "macro bow-hair contact track", "visual": "single bow rig crossing the actual string plane", "transition_out": "directional camera whip"},
            {"id": 3, "start": 7.5, "end": 12.0, "title": "The bridge transfers vibration", "camera": "bridge-level macro dolly", "visual": "bridge, string path and restrained vibration graphics", "transition_out": "resonance match dissolve"},
            {"id": 4, "start": 12.0, "end": 17.0, "title": "The body resonates", "camera": "f-hole and carved-plate close sweep", "visual": "wood grain, f-hole detail and expanding acoustic rings", "transition_out": "vertical detail wipe"},
            {"id": 5, "start": 17.0, "end": 20.5, "title": "The scroll and tuning pegs", "camera": "upper-instrument macro tilt", "visual": "scroll, pegs and string winding detail", "transition_out": "match cut to full silhouette"},
            {"id": 6, "start": 20.5, "end": 24.0, "title": "Four strings, one voice", "camera": "final hero dolly-out and settle", "visual": "full instrument, brand and composed final image", "transition_out": "final musical cadence and image hold"},
        ],
        "title_safe_area": {"brand": "top-left fixed", "subject_title": "below brand, shot-start only", "model": "central hero area"},
        "caption_safe_area": {"position": "lower centre", "lines": 1, "words_per_event": 2, "highlight": "Kokoro-native word timestamps; active word gold"},
        "audio_timeline": {
            "narration": "0s start; final spoken phrase is paced to finish at 21.5–22.4s with a short natural resonance tail",
            "music": "0–24s; audible from the opening frame and resolves with the final image",
            "transition_sfx": "shot cut accents aligned to the six scene transitions",
            "final_image_and_audio": "the closing shot, final spoken phrase and musical cadence share the same endpoint",
        },
        "full_render_authorized": False,
    }
    storyboard_path = output / "storyboard.json"
    storyboard_path.write_text(json.dumps(storyboard, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    mixed_path = output / "final-audio-mix.wav"
    filters = (
        "[1:a]volume=0.22,lowpass=f=10500,"
        "afade=t=in:st=0:d=0.30,afade=t=out:st=22.8:d=1.2[bed];"
        "[0:a]highpass=f=75,lowpass=f=11500,"
        "acompressor=threshold=0.11:ratio=2.7:attack=10:release=140:makeup=1.55,"
        "aecho=0.8:0.20:90|180|300:0.22|0.13|0.07[voice];"
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

    music_duration = float(sf.info(str(music_path)).duration)
    mix_duration = float(sf.info(str(mixed_path)).duration)
    if music_duration < 23.95 or mix_duration < 23.90:
        raise RuntimeError(
            f"Audio bed/mix must cover the full 24-second picture (music={music_duration:.2f}s, mix={mix_duration:.2f}s)."
        )
    if narration_info["duration_seconds"] < 21.5:
        raise RuntimeError("The final spoken phrase does not reach the closing scene.")
    report = {
        "title": TITLE,
        "script": SCRIPT,
        "storyboard": storyboard_path.name,
        "narration": {
            "file": narration_path.name,
            "engine": narration_info["engine"],
            "voice": narration_info["voice"],
            "license": narration_info["model_license"],
            "duration_seconds": narration_info["duration_seconds"],
            "word_count": narration_info["word_count"],
            "word_timing_count": narration_info["word_timing_count"],
            "target_finish_window_seconds": [21.5, 22.4],
            "voice_resonance_tail_seconds": round(max(0.0, 24.0 - narration_info["duration_seconds"]), 2),
        },
        "music": {
            "file": music_path.name,
            "duration_seconds": round(music_duration, 3),
            "origin": music_info["audio_source"],
            "license": music_info["license"],
            "source_library": music_info["source_library"],
            "attribution": music_info["attribution"],
            "sample_bank_revision": music_info["sample_bank_revision"],
            "zones_used": music_info["zones_used"],
        },
        "sound_effects": {"file": sfx_path.name, "origin": "original procedural effects"},
        "final_mix": {"file": mixed_path.name, "duration_seconds": round(mix_duration, 3), "sample_rate": 48000, "channels": 2},
        "captions": captions_path.name,
        "karaoke_captions": karaoke_path.name,
        "word_timing_file": word_timing_path.name,
        "voice_tracks_target_near_end": True,
        "narration_full_timeline_gate": "passed",
        "music_covers_full_video": True,
        "final_audio_endpoint_seconds": 24.0,
    }
    (output / "audio-report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
