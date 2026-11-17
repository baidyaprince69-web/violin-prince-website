"""Offline-data-free API preflight for the isolated Qwen3-TTS voice test.

This script imports the official Qwen package and checks the Base-model
voice-cloning API signatures. It never loads model weights, opens audio,
reads secrets, or contacts Google Drive.
"""
from __future__ import annotations

import inspect
from importlib.metadata import version

import torch
from qwen_tts import Qwen3TTSModel


def require_parameters(callable_object, expected: set[str], label: str) -> None:
    actual = set(inspect.signature(callable_object).parameters)
    missing = sorted(expected - actual)
    if missing:
        raise RuntimeError(
            f"{label} is missing expected parameters: {', '.join(missing)}"
        )


def main() -> None:
    installed = version("qwen-tts")
    if installed != "0.1.1":
        raise RuntimeError(
            f"Expected qwen-tts 0.1.1, found {installed}. "
            "Review the Qwen package update before changing the pin."
        )

    require_parameters(
        Qwen3TTSModel.create_voice_clone_prompt,
        {"self", "ref_audio", "ref_text", "x_vector_only_mode"},
        "create_voice_clone_prompt",
    )
    require_parameters(
        Qwen3TTSModel.generate_voice_clone,
        {
            "self",
            "text",
            "language",
            "ref_audio",
            "ref_text",
            "x_vector_only_mode",
            "voice_clone_prompt",
            "non_streaming_mode",
        },
        "generate_voice_clone",
    )

    print(f"qwen-tts package: {installed}")
    print("Qwen3TTSModel import: OK")
    print("Base voice-clone prompt API: OK")
    print("Base voice-clone generation API: OK")

    if torch.cuda.is_available():
        device = torch.cuda.get_device_name(0)
        memory_gib = torch.cuda.get_device_properties(0).total_memory / (1024**3)
        print(f"CUDA device detected: {device} ({memory_gib:.1f} GiB VRAM)")
        print(
            "API preflight only: this workflow still does not load weights "
            "or process voice data."
        )
    else:
        print(
            "No CUDA GPU on this standard runner. This is expected: "
            "model inference is intentionally not attempted."
        )

    print("No audio, transcript, .vprvoice package, or passphrase was accessed.")


if __name__ == "__main__":
    main()
