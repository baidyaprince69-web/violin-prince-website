# Violin Prince — isolated Qwen3-TTS test path

**Current status:** GitHub Actions preflight scaffold. No voice recording has been decrypted, transferred, or used by this workflow.

## What the Actions workflow checks

- Installs the pinned official `qwen-tts==0.1.1` package in a fresh runner environment.
- Imports `Qwen3TTSModel`.
- Verifies the Base model's `create_voice_clone_prompt` and `generate_voice_clone` API parameters.
- Reports whether the runner exposes CUDA.
- Does not download Qwen model weights or run synthesis.

The workflow runs on pushes to the isolated feature branch and pull requests to `main`. It has read-only repository permissions.

## What it never receives

This workflow has no audio inputs, Google Drive integration, passphrase secret, transcript, or upload step. It does not read the encrypted `.vprvoice` package. The passphrase remains in the user's Notepad on their own computer. Do not add voice recordings, decrypted WAVs, transcripts, or cloned-voice profiles to the repository, Actions artifacts, logs, or release assets.

## Why this is only a preflight

The standard `ubuntu-latest` GitHub-hosted runner is CPU-only. It can validate the Python package and API, but this workflow deliberately cannot prove that Qwen can clone the user's voice.

GitHub documents GPU-powered larger runners with a Tesla T4 GPU and 16 GB VRAM; these are available only to organizations and enterprises on GitHub Team or GitHub Enterprise Cloud. Do not assume that this personal repository can use one. See [GitHub larger runners](https://docs.github.com/en/actions/reference/runners/larger-runners) and [who can manage them](https://docs.github.com/en/actions/how-tos/manage-runners/larger-runners/manage-larger-runners).

Until a suitable GPU runner is actually available and an appropriate private data-transfer route is deliberately approved, the next step remains blocked. Do not try to force CPU inference on the standard runner or put the recording in GitHub to make the workflow proceed.

## Production safety

The current production `autopilot/engine/voiceover.py` is untouched. No narrator setting changes. Qwen3-TTS is not active in production. There is no preset-speaker, generic-voice, or Kokoro fallback in this test path. A future voice result must be listened to and approved by the creator before any production integration.
