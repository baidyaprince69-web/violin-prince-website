# Private Qwen3 narration bridge

This bridge keeps the enrolled reference voice private while allowing the public Violin Prince renderer to use an explicitly approved Qwen3 narration.

## Data flow

1. The public Actions workflow sends the current 37–38-word narration estimate, calibrated from the prior 40-word generation that lasted 24.08 seconds and its numeric run ID to the private repository's `private-qwen3-narration.yml` workflow.
2. The private runner checks `private/voice-approval.json`, decrypts the voice package only in its temporary workspace, and generates audio with `Qwen/Qwen3-TTS-12Hz-0.6B-Base`.
3. The private runner uses `faster-whisper==1.2.1` with `word_timestamps=True` to estimate word boundaries using cross-attention and dynamic time warping. It independently checks that the recognized word sequence exactly matches the requested script. Missing, extra, reordered, or low-coverage word timings fail the job.
4. The private runner stores only `narration.wav` and `narration.json` in a private draft release. It never uploads the reference WAV, decrypted transcript, or model cache.
5. The public renderer downloads those two assets into its ephemeral runner workspace, verifies checksums, script hash, exact word sequence, timing order, audio format, the 22.0–23.0-second raw-duration target, and sentence coverage, then writes the narration WAV to the render workspace. It does not put the narration WAV in public artifacts or a public release.

Qwen3's `generate_voice_clone` interface returns generated waveforms and a sample rate, not per-word timing cues. The timing step therefore uses a separate speech-recognition pass. This is transcript-checked word timing, not a phoneme-level forced alignment.

References:
- [Qwen3-TTS voice-clone API](https://github.com/QwenLM/Qwen3-TTS)
- [faster-whisper word-level timestamps](https://github.com/SYSTRAN/faster-whisper#word-level-timestamps)

## One-time GitHub connection

Create a fine-grained personal access token with access to **only** `baidyaprince69-web/violin-prince-private-voice`. Grant:
- **Actions:** Read and write (to dispatch the private workflow and inspect its run).
- **Contents:** Read-only (to inspect and download private draft-release assets).

Add it to the public `baidyaprince69-web/violin-prince-website` repository as an Actions secret named:

`PRIVATE_VOICE_REPO_TOKEN`

Never paste the token into chat, source code, workflow inputs, or a commit. Do not add it to the public website.

## Run the first complete narration test

After both bridge PRs are reviewed, merged, and the first end-to-end test is started, run **Private Qwen3 narration bridge test** from the public repository's Actions tab. It uses the current `.autopilot/daily-production-plan.json` narration. The workflow does not render a video, publish anything, or upload a public artifact. The private repository retains the resulting draft release so the narration can be downloaded and listened to.

The production voice gate remains closed until the bridge test completes successfully. The separate illustration-provider gate remains unchanged.
