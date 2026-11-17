"""Load the smaller Qwen3-TTS Base checkpoint on a standard CPU runner.

No audio files, reference transcripts, credentials, or user data are accessed.
This tests whether the Base model can be initialised within the ordinary
GitHub-hosted runner's memory budget.
"""
from __future__ import annotations

import gc

import torch
from qwen_tts import Qwen3TTSModel


MODEL_ID = "Qwen/Qwen3-TTS-12Hz-0.6B-Base"


def main() -> None:
    torch.set_num_threads(4)
    print(f"Loading {MODEL_ID} on CPU (float32).")
    print("This step downloads public model weights only; it uses no voice data.")

    model = Qwen3TTSModel.from_pretrained(
        MODEL_ID,
        device_map="cpu",
        dtype=torch.float32,
        attn_implementation="sdpa",
    )

    model_type = getattr(model.model, "tts_model_type", None)
    if model_type != "base":
        raise RuntimeError(
            f"Expected a Base checkpoint, but model type is {model_type!r}."
        )

    if not callable(getattr(model, "create_voice_clone_prompt", None)):
        raise RuntimeError("Base checkpoint does not expose create_voice_clone_prompt.")
    if not callable(getattr(model, "generate_voice_clone", None)):
        raise RuntimeError("Base checkpoint does not expose generate_voice_clone.")

    languages = model.model.get_supported_languages()
    print(f"Loaded model type: {model_type}")
    print(f"Supported language count: {len(languages)}")
    print("CPU model-load smoke test: PASSED")
    print("No voice audio was generated and no reference audio was opened.")

    del model
    gc.collect()


if __name__ == "__main__":
    main()
