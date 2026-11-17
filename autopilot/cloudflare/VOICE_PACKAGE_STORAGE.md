# Private encrypted voice package storage

**Status:** implemented on a feature branch; this storage route is not deployed until the pull request is merged and the Cloudflare deployment workflow succeeds.

## Purpose

Move an already-encrypted Violin Prince Voice Vault package from the owner's browser into the existing private Cloudflare R2 bucket. This is a ciphertext handoff only. It does not decrypt, inspect, transcribe, clone, or generate any audio.

## Browser flow

1. Connect the existing Autopilot dashboard using its Cloudflare Worker URL and Dashboard access token.
2. Select only the `.vprvoice` file previously downloaded from the private Google Drive Voice Vault folder.
3. The browser checks the public package magic header and PBKDF2 iteration count (600,000). It does not decrypt the file.
4. The Worker accepts the encrypted bytes and returns an opaque UUID package ID.
5. The package ID is held in this browser tab's session storage so the owner can later identify/delete the stored copy.

The dashboard never asks for or reads the encryption passphrase. Do not upload the original recording, prepared WAV, transcript, or an unencrypted file.

## Worker API

All routes use HTTPS and require bearer authentication.

| Route | Auth | Purpose |
|---|---|---|
| `POST /api/voice-packages` | Dashboard token | Upload a `.vprvoice` ciphertext file up to 50 MB |
| `GET /internal/voice-packages/{uuid}` | Internal job token | Stream the ciphertext to an authorised private runner |
| `DELETE /api/voice-packages/{uuid}` | Dashboard token | Delete the R2 copy |

The upload route validates the file extension, exact stream size, `VPRVOICE` magic bytes, and the supported PBKDF2 header. It then stores the bytes in R2 under `voice-packages/{uuid}.vprvoice`. It does not create a D1 asset row, public link, or signed media URL.

The retrieval route returns `application/octet-stream` with `Cache-Control: private, no-store`. It is under `/internal/`, so the Worker's existing authentication gate requires the internal job token. Unknown or malformed IDs return 404.

## Retention

Scheduled cleanup deletes R2 copies older than 30 days. The owner's encrypted Google Drive copy is not modified and remains the durable backup. The owner can also delete the R2 copy through the dashboard.

## Not included yet

- A separate private GitHub repository for voice tests.
- A GitHub Actions workflow that calls the internal retrieval route.
- A secure user-managed passphrase secret for the test runner.
- Decryption, Qwen inference, generated sample storage, or private sample download.
- Any change to production narration.

Before enabling a real test, the owner must independently create/approve the separate private repository and secret arrangement. The public website repository and its Actions artifacts must never receive voice recordings, transcript, passphrase, OAuth tokens, embeddings, cloned voice profiles, or generated samples.
