# Violin Prince Autopilot

A cloud-first, free-tier-first production pipeline. The existing artist website is left intact; the Autopilot lives in the isolated autopilot/ folder.

## Current implementation

- Static insights/control dashboard at /autopilot/.
- Cloudflare Worker control plane, daily Cron trigger, D1 activity database and private R2 media library.
- GitHub Actions public runner for remote Python/FFmpeg work. Your PC does not render, host or keep a notebook open.
- Free public-source research through GDELT and Google News RSS.
- Cloudflare Workers AI Gemma 4 for topic selection, narrative, titles and captions.
- FLUX.1 Schnell for three original still images per video.
- FFmpeg creates a 24-second, 9:16 motion-graphic short from the stills, with gentle movement, burned-in captions, transitions and the user's recording.
- The uploaded, rights-confirmed recording is processed with high-pass/low-pass filtering, compression, loudness normalisation and fades.
- Final MP4 and production metadata are saved to private R2; D1 records the run and dashboard events.
- Optional YouTube, Instagram Reels and Facebook Reels adapters use official APIs. Publishing is OFF by default and requires authorised credentials.

## Important limitations

1. This first free-generation path creates cinematic motion graphics from generated images. It does not generate fully moving live-action video with a text-to-video model.
2. There is no unlimited free AI service. Cloudflare Workers AI has a daily 10,000-Neuron free allowance that resets at 00:00 UTC. If it is exhausted, requests fail; the engine has no paid fallback.
3. The first production target is one video per day, with three AI-generated stills. It skips production if research feeds are unavailable, no rights-confirmed audio is uploaded, or an AI quota is exhausted.
4. The video is a draft unless publishing is explicitly enabled. Publishing needs one-time Google/Meta app and account authorisation. Use only accounts that are eligible to use the relevant platform APIs; do not bypass account-age, identity or platform requirements.
5. You are responsible for verifying rights to the underlying composition, recording and any other material before publishing. Checking the upload box is a declaration, not a legal clearance service. Do not automatically publish covers unless you have the necessary rights or the platform's applicable monetisation/licensing permission.
6. The dashboard and Worker are not deployed yet. A Cloudflare account, D1 database, R2 bucket, Worker secrets and GitHub Actions secrets must be configured first.
7. The repository is public. Source code is visible to everyone. Never commit audio, access tokens, OAuth files, private user data or generated private media.

## Free-first services and limits

- GitHub Pages: free static dashboard hosting.
- GitHub Actions: standard GitHub-hosted runners are free for public repositories. This repository is public. The runner runs Python/FFmpeg remotely; your PC is not used.
- Cloudflare Workers: free control-plane API and Cron scheduling. It does not render videos.
- Cloudflare D1: free-tier database for run history, assets and quota counters.
- Cloudflare R2: Standard storage includes 10 GB-month, 1 million Class A and 10 million Class B requests each month; internet egress is free.
- Workers AI: 10,000 Neurons per day on the Free plan. The selected Gemma 4 model and FLUX Schnell use the same daily allocation. A quota error stops the run; no paid fallback exists.
- GDELT and Google News RSS: public research feeds with no paid search subscription.
- FFmpeg and Pillow: open-source media assembly and image layout tools.

Free allowances and platform terms can change. Monitor Cloudflare's usage dashboard and GitHub Actions settings. R2 usage above the included allowance can incur charges on a billing-enabled account, so keep media storage below 10 GB and delete old renders when no longer needed.

## One-time setup

### 1. Create Cloudflare resources

In the Cloudflare account dashboard:

1. Enable Workers AI.
2. Create an R2 Standard bucket named violin-prince-media.
3. Create a D1 database named violin-prince-autopilot.
4. Create a Worker named violin-prince-autopilot.
5. Copy the D1 database ID into autopilot/cloudflare/wrangler.toml, replacing REPLACE_WITH_YOUR_D1_DATABASE_ID.
6. Apply autopilot/cloudflare/schema.sql to that D1 database.
7. Deploy autopilot/cloudflare/src/worker.js with autopilot/cloudflare/wrangler.toml.

Cloudflare's browser dashboard can create the resources. For deployment without using your PC, connect the GitHub repository in Cloudflare Workers Builds and set the deploy command to:

npx wrangler deploy --config autopilot/cloudflare/wrangler.toml

If using a browser-based terminal instead, the equivalent commands are:

- npx wrangler d1 create violin-prince-autopilot
- npx wrangler r2 bucket create violin-prince-media
- npx wrangler d1 execute violin-prince-autopilot --remote --file=autopilot/cloudflare/schema.sql
- npx wrangler deploy --config autopilot/cloudflare/wrangler.toml

The Worker needs these secrets (set them in Cloudflare or via wrangler secret put). Generate them privately; never paste them into chat or commit them:

- DASHBOARD_TOKEN: long random token used by your dashboard.
- JOB_TOKEN: a different long random token used only by the GitHub runner.
- GITHUB_DISPATCH_TOKEN: fine-grained GitHub token restricted to this repository, with Actions: write, used by the Worker to dispatch its workflow.
- MEDIA_SIGNING_SECRET: long random secret used to create expiring read links to generated MP4s.

Set Worker variables:

- AUTOPILOT_ENABLED = false initially.
- GITHUB_OWNER = baidyaprince69-web
- GITHUB_REPO = violin-prince-website
- GITHUB_WORKFLOW = violin-prince-autopilot.yml
- GITHUB_REF = main

The configured daily Cron is 0 5 * * * UTC (10:30 AM Asia/Kolkata). It dispatches one cloud production job per day. Change the time only after checking your audience analytics.

### 2. Add GitHub Actions secrets

Repository Settings → Secrets and variables → Actions → New repository secret:

Required for draft production:

- AUTOPILOT_API_URL: deployed Worker URL, e.g. https://violin-prince-autopilot.YOUR-SUBDOMAIN.workers.dev.
- AUTOPILOT_JOB_TOKEN: same value as the Worker JOB_TOKEN.
- CF_ACCOUNT_ID: Cloudflare account ID.
- CF_API_TOKEN: Cloudflare API token scoped to Workers AI: Run.

No R2 S3 key is needed. The runner fetches and saves media through authenticated Worker endpoints.

Optional publishing secrets (keep publishing disabled until the account owner has approved and tested API access):

- YOUTUBE_CLIENT_ID
- YOUTUBE_CLIENT_SECRET
- YOUTUBE_REFRESH_TOKEN
- INSTAGRAM_USER_ID
- INSTAGRAM_ACCESS_TOKEN
- FACEBOOK_PAGE_ID
- FACEBOOK_PAGE_ACCESS_TOKEN

For YouTube Analytics, the owner-authorised Google refresh token must include the read-only scope https://www.googleapis.com/auth/yt-analytics.readonly in addition to https://www.googleapis.com/auth/youtube.upload when automatic YouTube uploads are enabled. Analytics is optional; without the read-only scope, the video workflow still runs and the dashboard shows that analytics is not connected. The Meta access token must have permissions for the selected publishing method. The Facebook destination must be a Page; Instagram must be a qualifying professional account. Store credentials only as GitHub Actions secrets, not variables or source code.

### 3. Set GitHub Actions variables

Repository Settings → Secrets and variables → Actions → Variables:

- PUBLISH_ENABLED = false (keep false while testing).
- PUBLISH_DESTINATIONS = youtube,instagram,facebook
- META_API_VERSION = a Graph API version supported by the connected Meta app.
- YOUTUBE_PRIVACY_STATUS = public (used only when publishing is enabled).
- YOUTUBE_PUBLISH_AT = optional future RFC 3339 timestamp; leave empty for immediate publication.

When PUBLISH_ENABLED is false, the system generates drafts only. When enabled, only the destinations listed in PUBLISH_DESTINATIONS are attempted. Missing credentials or API errors are recorded; they do not switch to a paid service.

### 4. Open the dashboard and upload original music

After GitHub Pages deploys the commits, open:

https://baidyaprince69-web.github.io/violin-prince-website/autopilot/

1. Enter the deployed Worker URL and DASHBOARD_TOKEN.
2. Upload one original recording or recording you are authorised to use.
3. Tick the rights confirmation only after you have checked the recording and composition rights.
4. Confirm the asset appears in the dashboard.

The token is held in browser session storage only. The audio stays in the private R2 bucket.

### 5. Test in draft mode

1. Confirm the Worker /api/health endpoint responds.
2. Connect the dashboard and verify /api/status.
3. Upload a short original or rights-cleared recording.
4. Set AUTOPILOT_ENABLED=true only after the GitHub dispatch token and Actions secrets are configured.
5. Use the dashboard's manual test button or wait for the daily Cron.
6. Inspect the MP4 and metadata in the R2 bucket / run artifact.
7. Confirm the audio, visual quality, captions, sources and technical output.
8. Only after the draft is acceptable and platform authorisation/rights are complete should an eligible account owner enable PUBLISH_ENABLED=true.

## Quota, safety and failure policy

- One production attempt per UTC day maximum. The daily lock is consumed even if generation or publishing fails, preventing repeated quota use that day; the next attempt is on the next day's cycle.
- Three generated stills per video.
- No paid API fallback.
- If Workers AI returns quota/rate-limit errors, stop generation and record the failure.
- If no approved audio exists, skip video generation.
- If a research feed is down, use the remaining feeds; if all feeds fail, skip production rather than invent a topic.
- Research headlines are treated as untrusted source material. The planner must avoid tragedies, graphic violence, sensationalism and unsupported claims.
- If rendering or publishing fails, record the error; do not loop or repeatedly spend quota.
- R2 should stay under its free 10 GB-month allowance. Keep only the approved source audio and recent renders; remove old drafts when they are no longer needed.
- A run can finish as rendered, published, partially_published or failed. A partial platform failure does not trigger repeated uploads.

## What still requires account-owner setup

Cloudflare resources, D1 ID, Worker secrets and GitHub Actions secrets must be configured by the account owner. Google and Meta OAuth/app permissions must be granted by an eligible account owner. Never send passwords, refresh tokens or API secrets in chat.