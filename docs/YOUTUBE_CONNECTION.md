# YouTube connection and SEO learning setup

This setup uses GitHub Actions for connection checks and scheduled SEO learning. It does **not** require a Cloudflare account, Cloudflare Workers, Cloudflare D1, or a Cloudflare payment plan for the YouTube connection/learning stage.

## Google API setup

1. In Google Cloud Console, create or select a project and enable **YouTube Data API v3** and **YouTube Analytics API**.
2. Create an OAuth client for a web application. Add this redirect URI if using Google's OAuth Playground:
   `https://developers.google.com/oauthplayground`
3. Configure the OAuth consent screen and add the channel owner as a test user while testing. Authorize only these scopes:
   - `https://www.googleapis.com/auth/youtube.upload`
   - `https://www.googleapis.com/auth/youtube.readonly`
4. In OAuth Playground, open its settings, select **Use your own OAuth credentials**, and enter the OAuth client ID and client secret. Authorize the two scopes above, exchange the code, and obtain the refresh token. Do not paste credentials or tokens into chat, issues, workflow inputs, or repository files.

Google documents that offline access is required for long-running services to refresh access tokens without the user present. OAuth authorizations for external apps left in Testing expire after seven days; this is not suitable for unattended weekly publishing. Production publishing status and any required Google verification must be handled through Google's normal process. Do not bypass age, identity, or account verification requirements.

## GitHub repository configuration

Add these under **Settings → Secrets and variables → Actions**:

**Repository secrets**
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`
- `YOUTUBE_STATE_ENCRYPTION_KEY` — URL-safe Base64 encoding of 32 random bytes. This existing Phase 4 key is also used as the root for a separately derived SEO-storage key; the derived key is different from the upload-checkpoint key.
- `YOUTUBE_API_KEY` is optional after OAuth is connected. Discover can use the authorized OAuth token; the key remains a public-data fallback.

**Repository variable**
- `YOUTUBE_EXPECTED_CHANNEL_ID` — set this to the channel ID shown by the connection-check workflow. The publisher refuses to upload to a different channel.

The SEO-learning workflow commits only AES-256-GCM ciphertext to the separate `seo-learning-data` branch. It does not commit raw views, watch time, subscriber counts, channel reports, OAuth tokens, or plaintext keywords. The next production Prepare run decrypts that snapshot inside its temporary GitHub runner. If no snapshot exists yet, Discover keeps its balanced English/Hindi/Bengali plan.

## Safe test order

1. Run **Phase 4 YouTube connection check**. It refreshes OAuth, reads the authorised channel, and makes one small read-only Analytics request. It never uploads.
2. Set `YOUTUBE_EXPECTED_CHANNEL_ID` to the returned channel ID, then run the connection check again.
3. Run **Phase 5 scheduled YouTube SEO learning** manually once. This collects one bounded 7-day channel report and one bounded 28-day per-video report, then stores only encrypted SEO signals.
4. Run the YouTube metadata review workflow. Review the title, description, tags, hashtags, audience setting, synthetic-media disclosure, and rights before any private upload test.
5. A private upload still requires the separate private-beta approval gates. Public publishing remains disabled.

YouTube's Data API has project-level quota allocations shown in Google Cloud Console. This workflow bounds its calls and does not enable unrelated paid Google Cloud services. If Google Console requests payment details or an identity check that the account owner cannot complete, stop there; do not add payment details or try to bypass the requirement.
