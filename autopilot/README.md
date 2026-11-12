# Violin Prince Autopilot

A cloud-first, zero-paid-API-by-default production pipeline. The existing artist website is not modified; this project lives in the isolated autopilot folder.

## What this first version does

- Hosts a dashboard at /autopilot/ through the repository's existing GitHub Pages site.
- Provides a Cloudflare Worker control plane, daily Cron trigger, D1 activity database, and R2 media library.
- Uses a GitHub Actions public runner for remote Python/FFmpeg work; your PC does not render or host anything.
- Researches global news/music topics from public RSS and GDELT feeds.
- Uses Cloudflare Workers AI (Llama 3.3 70B Fast) for topic selection, narrative and captions.
- Uses FLUX.1 Schnell for a capped number of original still images, then animates them with FFmpeg into a vertical video.
- Uses an uploaded, rights-cleared recording from the private R2 library as the soundtrack.
- Saves finished videos to R2 and records the run in D1.

## Important honest limitations

1. This creates cinematic motion videos from generated still images (pan/zoom, transitions, captions and the user's recording). It is not a free text-to-video model producing fully moving live-action scenes.
2. There is no unlimited free AI service. Workers AI has a daily free allocation; the engine has hard caps and does not fall back to paid APIs.
3. Platform publishing requires one-time OAuth / Meta authorisation. The first deployment is draft-only. Do not enable automatic publishing until the platform credentials, rights and destination accounts have been configured and tested.
4. A public GitHub repository exposes its source code. Never commit audio files, tokens, OAuth files, personal data or generated private media.
5. The dashboard and Worker are not deployed by these commits. A Cloudflare account, D1 database, R2 bucket, Worker secrets and GitHub Actions secrets must be configured first.

## Free-first components

- GitHub Pages: static dashboard hosting.
- Cloudflare Workers: short control-plane requests and Cron; not video rendering.
- Cloudflare D1: run history, asset metadata and quota counters.
- Cloudflare R2: user-approved music library and rendered MP4s.
- Cloudflare Workers AI: Llama 3.3 70B Fast and FLUX.1 Schnell, subject to the free daily allocation.
- GitHub Actions: cloud runner for Python and FFmpeg. This repo is public, so standard GitHub-hosted runner usage is free under GitHub's current public-repository policy.
- GDELT and public RSS feeds: research sources without a paid search subscription.
- FFmpeg and Pillow: open-source rendering tools.

## One-time setup

### 1. Create Cloudflare resources

In a Cloudflare account:

1. Enable Workers AI.
2. Create an R2 bucket named violin-prince-media.
3. Create a D1 database named violin-prince-autopilot.
4. Create or deploy a Worker named violin-prince-autopilot.
5. Copy the D1 database ID into autopilot/cloudflare/wrangler.toml.
6. Apply autopilot/cloudflare/schema.sql to the D1 database.
7. Deploy autopilot/cloudflare/src/worker.js using the Wrangler configuration.

Example commands (run in Cloudflare's browser-based terminal / Workers Builds, or another cloud development environment; no local computer rendering is needed):

- npx wrangler d1 create violin-prince-autopilot
- npx wrangler r2 bucket create violin-prince-media
- npx wrangler d1 execute violin-prince-autopilot --remote --file=autopilot/cloudflare/schema.sql
- npx wrangler deploy --config autopilot/cloudflare/wrangler.toml

The Worker needs these secrets (set them in Cloudflare's dashboard or with wrangler secret put; never commit them):

- DASHBOARD_TOKEN: long random token used by the dashboard.
- JOB_TOKEN: separate long random token used only by the GitHub runner.
- GITHUB_DISPATCH_TOKEN: fine-grained GitHub token scoped to this repository with Actions: write, used by Cron to dispatch the workflow.
- MEDIA_SIGNING_SECRET: long random secret used to issue expiring media URLs.

Set Worker variables in the Cloudflare dashboard:
- AUTOPILOT_ENABLED = false initially.
- GITHUB_OWNER = baidyaprince69-web
- GITHUB_REPO = violin-prince-website
- GITHUB_WORKFLOW = violin-prince-autopilot.yml
- GITHUB_REF = main

The configured Cron is 0 5 * * * UTC (10:30 AM India time). Change it only after checking your audience analytics.

### 2. Add GitHub Actions secrets

Repository → Settings → Secrets and variables → Actions → New repository secret:

- AUTOPILOT_API_URL: the deployed Worker URL, e.g. https://violin-prince-autopilot.<your-subdomain>.workers.dev
- AUTOPILOT_JOB_TOKEN: same value as the Worker JOB_TOKEN.
- CF_ACCOUNT_ID: your Cloudflare account ID.
- CF_API_TOKEN: Cloudflare API token restricted to Workers AI: Run.

No R2 S3 key is required: the runner downloads and uploads media through authenticated Worker endpoints.

### 3. Open the dashboard

After GitHub Pages publishes this commit, open:

https://baidyaprince69-web.github.io/violin-prince-website/autopilot/

Enter the Worker URL and the DASHBOARD_TOKEN in the connection panel. The dashboard keeps the token in session storage only (cleared when the browser session ends).

Upload one or more recordings that you own or are licensed to use. Confirm the rights checkbox for each upload. The audio stays in your private R2 bucket.

### 4. Test before enabling automation

1. Confirm /api/health responds.
2. Connect the dashboard and verify /api/status.
3. Upload one short original or rights-cleared recording.
4. Run one manual workflow from GitHub Actions.
5. Inspect the generated draft in R2 and review its audio, visuals and captions.
6. Only after the draft is acceptable, configure publishing credentials and test platform adapters.
7. Set AUTOPILOT_ENABLED=true to permit Cron dispatch. Publishing remains separately disabled unless PUBLISH_ENABLED=true is configured in GitHub Actions.

## Quota and failure policy

- One video per UTC day maximum by default.
- Up to four AI-generated stills per video.
- No paid API fallback.
- If Workers AI returns a quota/rate-limit error, stop AI generation for that run and record quota_exhausted.
- If no rights-cleared audio is available, research can complete but video generation is skipped.
- If rendering or publishing fails, record the error and retry only on the next scheduled cycle; do not create repeated paid requests.
- Old renders should be deleted from R2 periodically to remain under the free storage allowance.

## What still requires account-owner action

The user must create the Cloudflare resources and add secrets in the relevant account dashboards. Social platform OAuth grants must be approved by the account owner. Do not send passwords, refresh tokens or API secrets in chat.
