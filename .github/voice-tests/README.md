# Violin Prince — isolated Qwen3-TTS test path

**Verified on 2026-11-18:** the GitHub Actions preflight passed for the pinned `qwen-tts==0.1.1` package, the Base voice-cloning API, and loading the public `Qwen/Qwen3-TTS-12Hz-0.6B-Base` checkpoint on the standard CPU runner.

## What passed

1. Install the pinned official `qwen-tts==0.1.1` package.
2. Verify the Base voice-cloning API signatures.
3. Download and initialise the 0.6B Base checkpoint on the standard GitHub-hosted CPU runner.
4. Confirm the loaded checkpoint reports model type `base` and exposes both voice-cloning methods.

The verified run is [44174265210](https://github.com/baidyaprince69-web/violin-prince-website/actions/runs/44174265210).

## What this does not prove

- It does not synthesise any audio.
- It does not use the creator's voice recording or transcript.
- It does not prove voice similarity, pronunciation quality, latency for a full narration, or production readiness.
- It does not enable Qwen in the production engine.

The standard CPU runner can load the 0.6B Base model. Actual CPU synthesis still needs a separate controlled test and may be slow. A GPU runner is not assumed.

## Data boundary

This workflow has no audio input, Google Drive integration, passphrase secret, decrypted WAV, reference transcript, or upload step. It downloads only public Qwen model weights. It does not read the encrypted `.vprvoice` package.

The passphrase remains in the creator's Notepad on their own computer. GitHub Actions cannot read a local Notepad. Never add a voice recording, decrypted WAV, transcript, passphrase, access token, voice embedding, or cloned-voice profile to this public repository, Actions logs, artifacts, or releases.

Before a real voice-cloning test, a separately approved private data-transfer and decryption design is required. The encrypted package remains in the creator's Google Drive until that path exists.

## Production boundary

The production `autopilot/engine/voiceover.py` remains unchanged by this preflight and currently uses Kokoro. This PR does not switch the narrator and does not claim that production uses the creator's voice. A separate production safety change must make narration fail closed while the approved own-voice provider is unavailable. No generic, preset-speaker, third-party, or Kokoro fallback may be used for the creator's own-voice-only workflow.
