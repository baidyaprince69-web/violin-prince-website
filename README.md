# Encrypted Violin Prince SEO-learning data

This branch is the persistence location for Phase 5's YouTube SEO-only learning signals.

- The workflow stores only AES-256-GCM encrypted JSON at `seo-learning/latest.enc.json`.
- Plaintext YouTube Analytics reports, raw channel metrics, access tokens, refresh tokens, client secrets and encryption keys must never be committed here.
- The encryption key is supplied only as a GitHub Actions secret. The workflow derives a purpose-specific key from the existing `YOUTUBE_STATE_ENCRYPTION_KEY`.
- The production runner decrypts the snapshot temporarily and passes only SEO signals into Discover.
- The workflow runs manually or weekly; it does not continuously poll YouTube.
- This branch is public because the repository is public, so encryption is mandatory.

Do not add any unencrypted reports, credentials, backups or personal channel data to this branch.
