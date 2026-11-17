# Violin Prince own-voice enrollment

**Status:** The private browser enrollment and encrypted Google Drive storage interface is implemented on the feature branch. Actual voice enrollment, model profiling and production narration integration remain pending.

## Enrollment route

Once merged and deployed to GitHub Pages, the user-facing route is:

`https://baidyaprince69-web.github.io/violin-prince-website/voice-vault/`

The browser page records through `MediaRecorder` or imports an existing audio file. It keeps the original recording, creates a 24 kHz mono PCM16 WAV locally, and asks for an exact transcript. It encrypts the original recording, WAV and transcript into one `.vprvoice` package with AES-256-GCM before uploading directly to the user's Google Drive.

The Google authorization uses only `https://www.googleapis.com/auth/drive.file`. The token exists only in page memory. The page creates a `Violin Prince Voice Vault` folder and does not create share permissions or public links. The encrypted package is private to the user's Drive account subject to that account's own folder-sharing policies.

No plaintext audio, transcript, passphrase, Google token, voice embedding or model profile belongs in the public Git repository, GitHub Actions artifacts, release assets, issue attachments or logs. The page has a local decrypt-and-download recovery flow. The passphrase cannot be recovered if lost.

## Model profile preparation

The private `.vprvoice` package must be downloaded from Drive and unlocked locally in the browser when an actual profile-preparation step is scheduled. The original recording, normalized WAV and transcript are supplied to a selected voice-cloning runtime only after the user explicitly starts enrollment. Provider-specific voice profiles/conditioning are generated separately; Qwen and GPT-SoVITS profiles must not be assumed interchangeable.

## Production voice identity rule

The target production architecture is:

1. Qwen3-TTS Base as the primary engine, conditioned on the user's approved reference voice.
2. GPT-SoVITS as a backup candidate, with its own profile built from the same user-owned reference recordings.
3. A voice-identity acceptance gate before narration is approved.
4. If neither configured provider can generate acceptable speech in the approved voice, stop the run. Never fall back to Kokoro, a preset speaker, a generic narrator or another person's voice.

This architecture is not yet activated in the production workflow. The current production `voiceover.py` still contains the legacy Kokoro implementation. Do not claim that every production Short already uses the creator's voice. Do not remove or change the current production narrator until provider hosting, cost/quota, model licences, alignment, identity checks and actual sample outputs have been verified.

## Required next tests

- Live HTTPS microphone permission and 30–60 second recording on the user's browser.
- Actual OAuth consent from the owner's Google account using the already configured public web client ID.
- Confirm the created folder and `.vprvoice` package are private in Drive and not publicly shared.
- Download and decrypt the package using the saved passphrase; verify the original audio, 24 kHz mono WAV and transcript.
- Compare a small Qwen3-TTS sample against the reference; evaluate GPT-SoVITS separately before authorizing it as backup.
- Verify the generated audio's word timings and reject incomplete alignment without interpolation.
- Add no model runtime or production switch until the previous tests pass and the user explicitly approves the production stage.
