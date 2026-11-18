#!/usr/bin/env python3
"""Generate one short private Qwen3-TTS own-voice sample on CPU."""
from __future__ import annotations
import argparse
import math
from pathlib import Path
import numpy as np
import soundfile as sf
import torch
from qwen_tts import Qwen3TTSModel

MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"
TEST_TEXT = "Welcome to Violin Prince. Today, we explore the sound and science behind the violin."

def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--reference-wav", required=True, type=Path)
    parser.add_argument("--reference-text", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not args.reference_wav.is_file() or not args.reference_text.is_file():
        raise SystemExit("A required temporary reference file is missing.")
    reference_text = args.reference_text.read_text(encoding="utf-8").strip()
    if len(reference_text) < 20:
        raise SystemExit("The reference transcript is too short.")
    torch.set_num_threads(4)
    model = Qwen3TTSModel.from_pretrained(
        MODEL_ID, device_map="cpu", dtype=torch.float32, attn_implementation="sdpa"
    )
    if getattr(model.model, "tts_model_type", None) != "base":
        raise SystemExit("The selected checkpoint is not a Qwen3-TTS Base model.")
    try:
        waveforms, sample_rate = model.generate_voice_clone(
            text=TEST_TEXT, language="English",
            ref_audio=str(args.reference_wav), ref_text=reference_text,
            x_vector_only_mode=False, non_streaming_mode=True, max_new_tokens=256,
        )
    finally:
        reference_text = ""
    if not waveforms:
        raise SystemExit("Qwen did not return a sample.")
    waveform = np.asarray(waveforms[0], dtype=np.float32).reshape(-1)
    if waveform.size < sample_rate * 2 or not np.isfinite(waveform).all():
        raise SystemExit("The generated sample is empty, too short or invalid.")
    if float(np.max(np.abs(waveform))) <= 1e-6:
        raise SystemExit("The generated sample is silent.")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    sf.write(args.output, waveform, sample_rate, subtype="PCM_16")
    info = sf.info(args.output)
    if info.samplerate != sample_rate or info.duration < 2 or not math.isfinite(info.duration):
        waveform.fill(0)
        raise SystemExit("The generated WAV failed output validation.")
    print("Qwen3-TTS CPU voice sample generated and validated.")
    waveform.fill(0)
    del waveform, waveforms, model

if __name__ == "__main__":
    main()
