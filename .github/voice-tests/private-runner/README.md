# Private GitHub Actions own-voice test template

These files are **templates only**. They are deliberately outside `.github/workflows/` in the public repository, so they cannot run here. Copy them into a separate repository whose visibility is set to **Private**.

## Files to copy

| This public template file | Destination in the private repository |
|---|---|
| `private-voice-test.workflow.yml` | `.github/workflows/private-voice-test.yml` |
| `decrypt_vprvoice.mjs` | `scripts/voice/decrypt_vprvoice.mjs` |
| `generate_qwen_voice_sample.py` | `scripts/voice/generate_qwen_voice_sample.py` |
| `private-repo.gitignore` | `.gitignore` (rename it when copying) |

The public decryption-helper test uses generated synthetic audio and a test-only passphrase. It never reads personal files or secrets.

## Private repository setup

1. Create a new, dedicated repository (suggested name: `violin-prince-private-voice`) and set it to **Private**. Do not reuse an unrelated private project.
2. Copy the workflow and two scripts to the listed destinations. Copy `private-repo.gitignore` to the private repository root as `.gitignore`. It permits only the encrypted package at the expected path and ignores decrypted/reference and sample WAV files.
3. From the private Google Drive Voice Vault folder, download the encrypted `.vprvoice` package. Upload only that encrypted file to `private/voice-prince-voice.vprvoice` in the private repository. Do not upload the original audio, normalized WAV or transcript. Keep the encrypted package in that private repository only; never commit it to the public website repository.
4. In the private repository's Settings → Secrets and variables → Actions, create a repository secret named `VOICE_PACKAGE_PASSPHRASE`. Enter the passphrase directly into GitHub's secret editor. Never put it in a workflow input, source file, commit, issue, chat, log or artifact.
5. Run **Private own-voice Qwen3 sample** manually from the private repository's Actions tab.

Review the data-processing and retention arrangement with a parent or guardian before uploading or processing personal voice material on a third-party service.

## Data handling

- The workflow runs only on manual dispatch from the private repository's main branch, and its job is restricted to the repository owner and a private repository.
- The encrypted package is stored in the private repository.
- The passphrase is read only from the private repository's Actions secret.
- Decrypted reference WAV and transcript files are written only to the temporary runner workspace with restrictive file permissions.
- The original recording is authenticated but is never extracted to disk by the helper.
- The generated WAV is the only artifact, uploaded to the private repository with a one-day retention period.
- The workflow does not cache, publish or release the reference WAV, transcript, encrypted package, passphrase or voice profile.
- Cleanup removes the temporary reference directory and Hugging Face model cache. GitHub-hosted runners are ephemeral.
- The workflow uses CPU inference only. The public model-load check passed; actual CPU synthesis speed is not yet known. No GPU availability is assumed.

This template does not enable production narration. The production own-voice gate must remain closed until the sample is reviewed and explicitly approved.
