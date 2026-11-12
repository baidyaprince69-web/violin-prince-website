"""Free CPU text-to-speech for the Violin Prince cloud production runner.

Kokoro-82M is downloaded and executed on the GitHub-hosted runner. Nothing is
installed or rendered on the user's computer. The selected voice is synthetic;
it does not clone or imitate a real person.
"""
from __future__ import annotations

import re
from pathlib import Path


VOICE = "af_heart"
LANG_CODE = "a"  # American English


def synthesize_voiceover(text: str, output_path: str | Path) -> tuple[Path, dict]:
    """Generate a narration WAV with Kokoro and return its metadata."""
    narration = re.sub(r"\s+", " ", str(text or "")).strip()
    if not narration:
        raise ValueError("Narration script is empty.")
    word_count = len(re.findall(r"\b[\w’'-]+\b", narration))
    if not 20 <= word_count <= 55:
        raise ValueError("Narration must contain 20–55 words.")

    try:
        import numpy as np
        import soundfile as sf
        from kokoro import KPipeline
    except ImportError as exc:
        raise RuntimeError(
            "Kokoro voice dependencies are missing. Install the cloud runner requirements."
        ) from exc

    target = Path(output_path)
    target.parent.mkdir(parents=True, exist_ok=True)

    # The pipeline runs on CPU in GitHub-hosted Actions; no GPU or paid API is used.
    pipeline = KPipeline(lang_code=LANG_CODE)
    chunks = []
    for _graphemes, _phonemes, audio in pipeline(
        narration,
        voice=VOICE,
        speed=0.96,
        split_pattern=r"(?<=[.!?])\s+",
    ):
        samples = np.asarray(audio, dtype=np.float32).reshape(-1)
        if samples.size:
            chunks.append(samples)

    if not chunks:
        raise RuntimeError("Kokoro returned no narration audio.")

    waveform = np.concatenate(chunks)
    if not np.isfinite(waveform).all():
        raise RuntimeError("Kokoro produced invalid audio samples.")

    # Prevent accidental clipping while preserving the natural model dynamics.
    peak = float(np.max(np.abs(waveform)))
    if peak > 0.98:
        waveform = waveform * (0.98 / peak)

    sf.write(str(target), waveform, 24000, subtype="PCM_16")
    info = sf.info(str(target))
    return target, {
        "engine": "Kokoro-82M",
        "model_license": "Apache-2.0",
        "voice": VOICE,
        "language": "English (American)",
        "voice_type": "synthetic_not_voice_cloned",
        "duration_seconds": round(float(info.duration), 2),
        "word_count": word_count,
        "sample_rate": int(info.samplerate),
    }
