# Violin Prince — isolated Qwen3-TTS test path

**Current status:** the Qwen3-TTS package/API preflight passed in GitHub Actions. A CPU model-load smoke test is being added next. No voice recording has been decrypted, transferred, or used by these checks.

## GitHub Actions test stages

1. Install the pinned official `qwen-tts==0.1.1` package.
2. Check the Qwen3-TTS Base voice-cloning API signatures.
3. Download and initialise the smaller `Qwen/Qwen3-TTS-12Hz-0.6B-Base` checkpoint on the standard `ubuntu-latest` CPU runner, then verify it exposes the Base cloning methods.

The standard GitHub-hosted Ubuntu runner has 4 vCPUs and 16 GB RAM. Qwen's CLI supports a CPU device. The 0.6B Base checkpoint is being tested as a lower-resource path; this is a model-load test only, not a claim that voice inference or generation quality has passed. It may be slower than a GPU run.

The 1.7B Base checkpoint remains a later quality candidate if suitable compute becomes available. A GPU larger runner is not assumed: GitHub restricts hosted larger runners to organizations and enterprises using Team or Enterprise Cloud.

## What the Actions workflow never receives

These checks have no audio inputs, Google Drive integration, passphrase secret, transcript, or upload step. They do not read the encrypted `.vprvoice` package. The passphrase stays in the user's Notepad on their own computer. Do not add voice recordings, decrypted WAVs, transcripts, or cloned-voice profiles to the repository, Actions artifacts, logs, or release assets.

**Important:** GitHub Actions cannot read a passphrase from the user's local Notepad. Before a real voice-cloning test, we must agree on a separate, private transfer/decryption path. Never enter the passphrase into a workflow input or a log. The encrypted package remains in the user's Google Drive until that path is ready.

## Production safety

The current production `autopilot/engine/voiceover.py` is untouched. No narrator setting changes. Qwen3-TTS is not active in production. There is no preset-speaker, generic-voice, or Kokoro fallback in this test path. A future voice result must be listened to and approved by the creator before any production integration. Model-load success alone is not evidence of voice similarity.
