# Violin Prince — own-voice testing

**Verified 2026-11-18:** the public, data-free GitHub Actions preflight passed for the pinned `qwen-tts==0.1.1` package, Base voice-cloning API signatures, and loading the public `Qwen/Qwen3-TTS-12Hz-0.6B-Base` checkpoint on a standard CPU runner.

## What passed

1. Install the pinned Qwen3-TTS package.
2. Verify the Base voice-cloning API signatures.
3. Download and initialise the public 0.6B Base checkpoint on the standard GitHub-hosted CPU runner.
4. Confirm that the loaded checkpoint reports model type `base` and exposes both voice-cloning methods.

The completed preflight run is [44174265210](https://github.com/baidyaprince69-web/violin-prince-website/actions/runs/44174265210).

## What this does not prove

- It does not read or decrypt the owner's recording.
- It does not synthesise speech.
- It does not measure similarity to the owner's voice.
- It does not prove pronunciation, alignment, CPU inference speed or production readiness.
- It does not enable a narrator in the production engine.

The standard CPU runner loaded the model successfully. Actual CPU synthesis is a separate test and may be slow. A GPU runner is not assumed.

## Data boundary

This public preflight has no audio input, Google Drive connection, passphrase secret, decrypted WAV, transcript or output-audio artifact. It downloads public model weights only.

The copy-ready private test workflow and helpers are in `.github/voice-tests/private-runner/`. They are templates only; this public repository does not run them with personal voice material. The real test must be run manually from a dedicated private repository. The encrypted package stays in that private repository, the passphrase is a repository Actions secret, the decrypted reference exists only in the temporary runner workspace, and only the generated sample is uploaded as a short-retention artifact in the private repository.

Never put a voice recording, encrypted package, decrypted WAV, transcript, passphrase, OAuth token, voice embedding, cloned-voice profile or generated sample in this public repository, its logs, artifacts or releases.

## Production boundary

The production code has a hard fail-closed own-voice gate. `voiceover.py` raises `OwnVoiceRequiredError` until the owner's voice has been tested and approved and an actual provider integration is complete. No generic, preset-speaker, third-party or Kokoro fallback is permitted. The public Qwen preflight and private test template cannot unlock production.
