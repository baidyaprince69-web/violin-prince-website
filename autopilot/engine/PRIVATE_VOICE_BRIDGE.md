# Private Qwen3 narration bridge

This bridge keeps the enrolled reference voice private while allowing the public Violin Prince renderer to use an explicitly approved Qwen3 narration.

## Data flow

1. The public Actions workflow sends the current 35-word narration script, calibrated for the worker's natural 20–24-second delivery target and its numeric run ID to the private repository's `private-qwen3-narration.yml` workflow.
2. The private runner checks `private/voice-approval.json`, decrypts the voice package only in its temporary workspace, and generates audio with `Qwen/Qwen3-TTS-12Hz-0.6B-Base`.
3. The private runner uses `faster-whisper==1.2.1` with `word_timestamps=True` to estimate word boundaries using cross-attention and dynamic time warping. It independently checks that the recognized word sequence exactly matches the requested script. Missing, extra, reordered, or low-coverage word timings fail the job.
4. The private runner creates a one-request orphan branch in the private repository containing only `narration.wav` and `narration.json`. It never uploads the reference WAV, decrypted transcript, or model cache, and it does not use Actions artifact storage.
5. The public bridge downloads those two files from that private branch into its ephemeral runner workspace, verifies checksums, script hash, exact word sequence, timing order, audio format, the 20.0–24.0-second raw-duration target, and sentence coverage, then asks the private cleanup workflow to delete the temporary branch. The narration WAV is written only to the render workspace; it is not placed in a public artifact or release.

Qwen3's `generate_voice_clone` interface returns generated waveforms and a sample rate, not per-word timing cues. The timing step therefore uses a separate speech-recognition pass. This is transcript-checked word timing, not a phoneme-level forced alignment.

References:
- [Qwen3-TTS voice-clone API](https://github.com/QwenLM/Qwen3-TTS)
- [faster-whisper word-level timestamps](https://github.com/SYSTRAN/faster-whisper#word-level-timestamps)

## One-time GitHub connection

Create a fine-grained personal access token with access to **only** `baidyaprince69-web/violin-prince-private-voice`. Grant:
- **Actions:** Read and write (to dispatch the private workflow and inspect its run).
- **Contents:** Read-only (to download the two files from the temporary private transfer branch).

Add it to the public `baidyaprince69-web/violin-prince-website` repository as an Actions secret named:

`PRIVATE_VOICE_REPO_TOKEN`

Never paste the token into chat, source code, workflow inputs, or a commit. Do not add it to the public website.

## Run the first complete narration test

After both bridge PRs are reviewed, merged, and the first end-to-end test is started, run **Private Qwen3 narration bridge test** from the public repository's Actions tab. It uses the current `.autopilot/daily-production-plan.json` narration. The workflow does not render a video, publish anything, or upload a public artifact. The private repository exposes the two verified files only on a temporary branch, which the bridge deletes after validation.

The private Qwen3 end-to-end bridge test completed successfully:
- Public bridge run: `44514229249`
- Private worker run: `44514263171`
- Private cleanup run: `44517206357`
- Exact 35-word transcript, all word timings, natural 22.96-second duration and SHA-256 validation passed.
- The temporary private transfer branch was deleted and verified absent.

The production own-voice gate is now open for the private Qwen3 provider only, backed by `voice-approval.json`. The private client still requires `PRIVATE_VOICE_REPO_TOKEN` and validates every run before writing narration to the temporary public runner workspace. The separate illustration-provider gate remains closed. Publishing remains disabled.
