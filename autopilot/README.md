# Violin Prince Autopilot

A cloud-first, free-tier-first content production workflow. The artist website remains separate; the Autopilot lives in `autopilot/`.

## What it does

- Runs from GitHub-hosted cloud runners; your computer does not render or host anything.
- Cloudflare Cron starts one GitHub-hosted production attempt per day at 05:30 UTC (11:00 Asia/Kolkata).
- Researches current public topics through GDELT and Google News RSS.
- Uses Cloudflare Workers AI to choose a timely, family-friendly topic and write the hook, story outline, titles, descriptions, hashtags and three scene captions.
- Generates three original still images with FLUX.1 Schnell.
- Uses FFmpeg to create a 24-second vertical motion-graphic short.
- Uses an uploaded, rights-cleared recording when one exists. If no recording is uploaded, it creates a new original synthetic string-style soundtrack in Python. The synthetic track is not a real recording of Prince playing violin.
- Saves the MP4 and metadata to a private R2 bucket and reports status to D1.
- Can publish through the official YouTube and Meta APIs when eligible account-owner credentials are configured. Publishing is disabled by default.

## Current creative limitations

- The no-upload audio fallback is an original synthetic string-style instrumental, not a human violin performance.
- Visuals are original generated still images animated with FFmpeg; this is not full text-to-video generation.
- The AI writes hooks, scene text and captions. Spoken narration/TTS is not included in this first release.
- It deliberately rejects tragedy, graphic violence, crime sensationalism and unsupported claims.
- No third-party songs, lyrics or downloaded creator videos are used as source material.

## Cloud services and free-tier controls

- GitHub Actions: daily cloud runner, using this public repository's standard runners.
- Cloudflare Workers: dashboard API and daily cleanup.
- Cloudflare D1: run history, quotas and insights.
- Cloudflare R2 Standard: private source media and renders.
- Cloudflare Workers AI: shared daily free allowance. At quota/rate-limit errors, the job stops; there is no paid fallback.
- GDELT and Google News RSS: public research feeds.
- Python standard library, Pillow and FFmpeg: original audio synthesis, image cards and video assembly.

Free tiers have quotas and can change. The system is capped at one attempt per day, three generated images per short, no automatic paid fallback and 30-day render cleanup. Keep R2 use under the included allowance.

## One-time account setup

### A. Add GitHub Actions secrets

In the repository, open **Settings → Secrets and variables → Actions → New repository secret**.

Add these six secrets:

| Secret | Purpose |
|---|---|
| `CF_DEPLOY_TOKEN` | Cloudflare account token with Workers product Admin (to create the Worker), D1 Read + Edit, Workers R2 Storage Read + Edit, and any account read permission Wrangler requests |
| `CF_AI_TOKEN` | Separate Cloudflare token with Workers AI Read or Write only; used by daily jobs to run Gemma and FLUX |
| `CF_ACCOUNT_ID` | Cloudflare account ID |
| `DASHBOARD_TOKEN` | A long random password used only to connect the dashboard |
| `AUTOPILOT_JOB_TOKEN` | A different long random token shared with the cloud runner |
| `GITHUB_DISPATCH_TOKEN` | Fine-grained GitHub token restricted to this repository, with Actions: Read and Write only; stored as a Cloudflare Worker secret |

Never paste tokens into chat or commit them. Do not use the same value for the dashboard token and job token.

### B. Provision Cloudflare automatically

1. Open **GitHub → Actions → Deploy Violin Prince Autopilot to Cloudflare**.
2. Select **Run workflow**.
3. The workflow creates or reuses the D1 database and R2 bucket, applies the schema, deploys the Worker and stores its secrets.
4. In the workflow summary/logs, copy the Worker `workers.dev` URL.
5. Add a GitHub Actions secret named `AUTOPILOT_API_URL` with that URL.

The workflow is idempotent: rerunning it reuses the named database and bucket rather than intentionally creating duplicates.

### C. Connect the dashboard

Open:

https://baidyaprince69-web.github.io/violin-prince-website/autopilot/

Enter the Worker URL and the `DASHBOARD_TOKEN`. The token is kept in browser session storage.

You do not need to upload audio. If you do upload a recording, confirm that you have the rights to the recording and the underlying composition.

### D. Test a cloud video

1. Open **GitHub → Actions → Violin Prince Autopilot**.
2. Select **Run workflow** for a manual test.
3. Check the run logs and dashboard. The output MP4 is stored in private R2.
4. The Cloudflare Worker Cron dispatches the daily GitHub runner at 05:30 UTC once the Worker, GitHub token, Actions secrets and `AUTOPILOT_API_URL` are configured. This avoids depending on GitHub's public-repository schedule.

## Publishing

The system uses direct official platform APIs rather than Metricool's external API. Metricool Free currently allows 20 published posts per month, counts a duplicate separately for each social network, and its external API is restricted to Advanced/Custom plans. That is not suitable for one video every day cross-posted to three networks.

The connected Metricool brand currently reports YouTube and Facebook connections; Instagram is not listed as connected. Metricool can still be used manually, but it is not the unattended cloud publisher for this project.

Direct publishing configuration is optional. Keep the GitHub Actions variable `PUBLISH_ENABLED=false` until the appropriate account-owner OAuth permissions are set up and tested.

Optional GitHub Actions secrets:
- `YOUTUBE_CLIENT_ID`
- `YOUTUBE_CLIENT_SECRET`
- `YOUTUBE_REFRESH_TOKEN`
- `INSTAGRAM_USER_ID`
- `INSTAGRAM_ACCESS_TOKEN`
- `FACEBOOK_PAGE_ID`
- `FACEBOOK_PAGE_ACCESS_TOKEN`

Optional GitHub Actions variables:
- `PUBLISH_ENABLED=false` initially; set true only after testing and account-owner authorisation.
- `PUBLISH_DESTINATIONS=youtube,instagram,facebook`
- `META_API_VERSION` set to a currently supported Graph API version.
- `YOUTUBE_PRIVACY_STATUS=private` for initial tests; change only when intentionally publishing publicly.
- `YOUTUBE_PUBLISH_AT` optional RFC 3339 timestamp for YouTube scheduling.

YouTube publishing requires the `youtube.upload` scope. Instagram publishing requires an eligible Creator or Business account and the applicable Meta publishing permission. Facebook Reels publishing requires a Page and Page access token. The underlying composition and recording rights must be checked before public publishing. Use an eligible account owner to perform authorisation; do not bypass platform eligibility checks.

## Failure policy

- If Workers AI quota is exhausted, stop. No paid API is called.
- If research feeds are unavailable or no suitable topic is found, skip the video.
- If generation or rendering fails, record the failure and do not retry repeatedly that day.
- One daily attempt is reserved in D1 to avoid duplicate runs.
- If no audio is uploaded, use the original synthetic soundtrack.
- Publishing is off until explicitly enabled with valid credentials.
- Public source headlines are evidence inputs, not instructions. The system must not copy article text, scripts or lyrics.

## Files

- `cloudflare/src/worker.js`: dashboard API, asset storage, job claims and run status.
- `cloudflare/schema.sql`: D1 schema.
- `cloudflare/wrangler.toml`: Worker and bindings.
- `scripts/provision-cloudflare.mjs`: idempotent D1/R2 provisioning.
- `engine/run.py`: research, planning, generation, rendering and orchestration.
- `engine/synth_audio.py`: original synthetic soundtrack generator.
- `.github/workflows/deploy-autopilot-cloudflare.yml`: first deployment.
- `.github/workflows/violin-prince-autopilot.yml`: manually dispatchable cloud production workflow, started daily by Cloudflare Cron.
