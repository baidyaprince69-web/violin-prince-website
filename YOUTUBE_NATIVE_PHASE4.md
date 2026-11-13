# Phase 4 — Native YouTube engine (offline-tested foundation)

## Current safety state
- `PUBLISH_ENABLED=false` is fixed in the validation workflow.
- No OAuth token is present in the repository or test workflow.
- No real YouTube upload, privacy change, or publication is performed by these tests.
- The first eventual upload must be separately approved and defaults to **private**.
- Public visibility requires a separate `YOUTUBE_PUBLICATION_APPROVED=true` gate in addition to the global publishing switch.

## What this component provides
1. Strict metadata validation: title (100 characters), description (5,000 UTF-8 bytes), separate ordinary keyword tags (500 characters including separators), and relevant hashtags. Hashtags are put in the description; they are not copied into the API keyword-tag field.
2. Keyword research from public YouTube search results, sampled by region/language. It reports result samples and public views/day estimates only. The YouTube Data API does not expose a reliable keyword search-volume number, so the engine deliberately reports no fabricated search volume.
3. OAuth refresh using secrets, with an explicit target-channel ID check before an upload.
4. Chunked resumable upload. The server's acknowledged byte range is authoritative. A missing/expired session fails closed rather than silently starting a second upload.
5. AES-256-GCM encrypted checkpoint state. A resumable upload session URL is a sensitive capability and is never written in plaintext to an Actions artifact.
6. Processing-status polling and a separate, approval-gated visibility-change method.

## SEO policy
YouTube states that titles, thumbnails and descriptions are more important to discovery than keyword tags; tags mainly help with common misspellings. Hashtags are kept to three relevant items by default. Metadata drafts are not uploadable until the plan contains `seo_metadata_approved: true`.

The engine does not claim exact search volume from result counts. Its research report includes the query, sampled search results, publicly visible views, upload dates, and a rough views/day estimate where dates and counts are available. These are competitive samples, not demand measurements.

## Explicit review fields required before upload
Each video plan must contain:
- `seo_metadata_approved`: true only after the title, description, ordinary tags and hashtags have been reviewed.
- `made_for_kids`: an explicit true/false decision for the video.
- `contains_synthetic_media`: an explicit true/false decision based on the actual content and YouTube's disclosure guidance.

The engine does not silently set the audience or synthetic-media declaration.

## OAuth permission choice
For the staged private-upload beta, request `youtube.upload` and `youtube.readonly`. The read-only scope is used to verify the signed-in channel, read the uploaded video's processing status, and access the current YouTube Analytics reports endpoint. Do not request privacy-change permission for the first private-only test.

The later `videos.update` call used to change visibility requires the broader `youtube` or `youtube.force-ssl` scope; `youtube.upload` and `youtube.readonly` alone are not enough for that update operation. Add that broader permission only in a separately reviewed publication phase. Public or unlisted visibility remains disabled until a separate approval is recorded.

Google OAuth must request offline access so a refresh token can be stored. A Google Cloud OAuth project left in Testing has refresh tokens that expire after seven days for YouTube scopes. Production verification/publishing status must be settled before relying on unattended long-term publishing. Never paste OAuth client secrets or refresh tokens into chat.

## Required GitHub configuration (not added yet)
Secrets:
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`
- `YOUTUBE_API_KEY` (for public keyword research)
- `YOUTUBE_STATE_ENCRYPTION_KEY` (URL-safe base64 encoding of 32 random bytes)

Repository variable:
- `YOUTUBE_EXPECTED_CHANNEL_ID` — the exact channel ID that the OAuth account must return.

Runtime safety variables:
- `PUBLISH_ENABLED=false`
- `YOUTUBE_UPLOAD_APPROVED=false`
- `YOUTUBE_PUBLICATION_APPROVED=false`
- `YOUTUBE_PRIVACY_STATUS=private`

No Google Drive or Metricool integration is used. No billing or payment credentials are stored in this repository.

## Test coverage
The offline tests cover metadata limits, hashtag/tag separation, privacy gates, encrypted checkpoint integrity, no-network behaviour when publishing is disabled, resumable byte-range handling, upload-state encryption, YouTube processing status, and the SEO research response contract.
