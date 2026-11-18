# Violin Prince own-voice enrollment

**Status (2026-11-18):** The private browser Voice Vault is merged and deployed on GitHub Pages. The owner confirmed that the encrypted `.vprvoice` package was saved to private Google Drive. The public Qwen3-TTS preflight passed package/API checks and loaded the 0.6B Base model on a standard CPU runner. No personal recording has been decrypted by GitHub Actions, no voice sample has been generated, and production narration remains locked.

## Private enrollment page

`https://baidyaprince69-web.github.io/violin-prince-website/voice-vault/`

The page records through the browser microphone or imports an audio file. It prepares a 24 kHz mono PCM16 WAV, asks for the exact recording transcript, and encrypts the original audio, prepared WAV and transcript into one `.vprvoice` package in the browser.

Encryption uses AES-256-GCM with a PBKDF2-SHA256-derived key and 600,000 iterations. The Google OAuth scope is `drive.file`; the short-lived access token remains in page memory. The page does not create public sharing permissions. The owner must keep the encrypted Drive folder private and retain the original passphrase locally. The passphrase cannot be recovered if lost.

## Private GitHub Actions voice-test route

The real voice test is designed to run in a **separate private GitHub repository**, not in this public website repository.

The copy-ready, data-free template is stored under `.github/voice-tests/private-runner/`. It is not an active workflow in this public repository. Before a real test:

1. Create a dedicated private repository for the voice test. Do not reuse an unrelated private project.
2. Copy the template workflow and helper scripts into that private repository.
3. Upload only the encrypted `.vprvoice` package from the private Drive folder into the private repository's `private/` folder.
4. Add the passphrase independently as the private repository's `VOICE_PACKAGE_PASSPHRASE` Actions secret. Never put it in a workflow input, source file, commit, issue, log or artifact.
5. Run the workflow manually. It decrypts the package only in the temporary GitHub-hosted runner workspace, creates a short Qwen3-TTS sample, uploads only that generated sample as a one-day artifact in the private repository, and removes temporary files at the end of the job.

The workflow is CPU-only and uses the public `Qwen/Qwen3-TTS-12Hz-0.6B-Base` model. The existing model-load check passed, but CPU voice-generation speed and quality have not yet been tested. A hosted GPU is not assumed. No Cloudflare Worker or R2 route is used by this voice-test design.

The public repository must never contain the encrypted voice package, raw recording, normalized WAV, transcript, passphrase, OAuth token, voice embedding, cloned-voice profile or generated sample. Do not upload personal voice material as an artifact from this public repository. Review the private-repository and third-party processing arrangement with a parent or guardian before running a real test.

## Voice identity and production rules

1. Qwen3-TTS Base is the primary candidate, using the owner's own reference recording and exact transcript.
2. GPT-SoVITS remains a separate backup candidate and must be evaluated independently before it is considered.
3. The owner must listen to and approve the generated voice sample.
4. If neither provider produces acceptable speech in the owner's own voice, production stays stopped. There is no Kokoro, preset, generic or third-party narrator fallback.
5. Production narration may be enabled only after voice identity, pronunciation, audio quality, timing/alignment, hosting limits, licence and cost have been checked and the owner explicitly approves it.

## Current production state

`autopilot/engine/voiceover.py` is intentionally fail-closed. Both the legacy staged runner and the ChatGPT daily-plan runner stop before research, soundtrack preparation, image generation or rendering. The Qwen test template does not unlock production. No generated sample is currently approved, and no provider is connected to production.
