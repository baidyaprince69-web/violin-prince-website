# Violin Prince own-voice enrollment

**Status (2026-11-18):** The private browser Voice Vault is deployed and the encrypted `.vprvoice` package is stored in the dedicated private repository `baidyaprince69-web/violin-prince-private-voice`. In private Actions run `44301408133`, encrypted-package verification, decryption inside the temporary runner, Qwen3-TTS installation, sample generation and sample validation all succeeded. The final artifact upload failed because the account's Actions storage quota was full; there is currently no downloadable sample. Temporary decrypted reference files and model cache were removed successfully. The owner has not listened to or approved a sample, so production narration remains locked.

## Private enrollment page

`https://baidyaprince69-web.github.io/violin-prince-website/voice-vault/`

The page records through the browser microphone or imports an audio file. It prepares a 24 kHz mono PCM16 WAV, asks for the exact recording transcript, and encrypts the original audio, prepared WAV and transcript into one `.vprvoice` package in the browser.

Encryption uses AES-256-GCM with a PBKDF2-SHA256-derived key and 600,000 iterations. The Google OAuth scope is `drive.file`; the short-lived access token remains in page memory. The page does not create public sharing permissions. The owner must keep the encrypted Drive folder private and retain the original passphrase locally. The passphrase cannot be recovered if lost.

## Private GitHub Actions voice-test route

The dedicated private repository is `baidyaprince69-web/violin-prince-private-voice`. It contains the encrypted package at `private/voice-prince-voice.vprvoice`, the private workflow `.github/workflows/private-own-voice-qwen3.yml`, and the passphrase secret was entered by the owner directly in that repository's Actions settings.

Private Actions run `44301408133` verified the encrypted package, decrypted it only inside the temporary runner workspace, installed the pinned Qwen3-TTS runtime, generated one sample and passed the workflow's audio-file validation. The artifact upload then failed because the account's Actions storage quota was full. The cleanup step completed, but no downloadable sample artifact exists from that run.

The workflow is CPU-only and uses `Qwen/Qwen3-TTS-12Hz-0.6B-Base`. CPU generation and automatic file validation have therefore been exercised; human listening, pronunciation review and subjective voice-quality approval are still outstanding because the sample was not retained as an artifact. After GitHub's Actions storage usage refreshes and there is space, the owner can rerun the workflow and download the one-day sample artifact from the private repository.

The public repository must never contain the encrypted voice package, raw recording, normalized WAV, transcript, passphrase, OAuth token, voice embedding, cloned-voice profile or generated sample. Decrypted reference audio and transcript must remain confined to the temporary private runner workspace and be removed at job completion. No Cloudflare Worker or R2 route is used.

## Voice identity and production rules

1. Qwen3-TTS Base is the primary candidate, using the owner's own reference recording and exact transcript.
2. GPT-SoVITS remains a separate backup candidate and must be evaluated independently before it is considered.
3. The owner must listen to and approve the generated voice sample.
4. If neither provider produces acceptable speech in the owner's own voice, production stays stopped. There is no Kokoro, preset, generic or third-party narrator fallback.
5. Production narration may be enabled only after voice identity, pronunciation, audio quality, timing/alignment, hosting limits, licence and cost have been checked and the owner explicitly approves it.

## Current production state

`autopilot/engine/voiceover.py` remains intentionally fail-closed. The Qwen sample was generated but could not be uploaded as an Actions artifact because storage was full, so the owner cannot yet review it. Both the own-voice gate and the text/illustration provider gates remain closed; production must not run until all three are genuinely configured and tested. The scheduled readiness gate checks these conditions and skips the expensive job when any blocker remains.
