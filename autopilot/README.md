# Violin Prince Autopilot

A cloud-first, free-tier-first content production workflow. The artist website remains separate; the Autopilot lives in `autopilot/`.

## What it does

- Runs from GitHub-hosted cloud runners; your computer does not render or host anything.
- Cloudflare Cron is configured for one GitHub-hosted production attempt per day at 05:30 UTC (11:00 Asia/Kolkata). The scheduler starts **disabled**; it is enabled only after a successful manual draft test.
- Researches public topics through GDELT and Google News RSS editions for the US, UK and India. It fetches short public article excerpts when available and requires two independent publisher domains for documentary/fact-telling scripts.
- Uses Cloudflare Workers AI to select a timely, family-friendly topic and write a sourced narration script, hook, title, description, hashtags and three scene captions.
- Generates three original still images with FLUX.1 Schnell.
- Generates a natural synthetic storyteller/fact-presenter voiceover with Kokoro-82M on the cloud runner (CPU-only; Apache-2.0 model weights).
- Uses FFmpeg to create a 24-second vertical short with full-bleed cinematic scene cards, narration mixed over a quiet instrumental bed, and sentence-timed subtitles based on the actual speech chunks.
- Uses an uploaded, rights-cleared recording when one exists. If no recording is uploaded, it creates a new original synthetic string-style soundtrack in Python. The synthetic track is not a real recording of Prince playing violin.
- Saves the MP4 and metadata to a private R2 bucket and reports status to D1.
- Can publish through the official YouTube and Meta APIs when eligible account-owner credentials are configured. Publishing is disabled by default.

## Current creative limitations

- The no-upload audio fallback is an original synthetic string-style instrumental, not a human violin performance.
- Visuals are original generated still images animated with FFmpeg; this is not full text-to-video generation.
- Spoken narration uses a standard synthetic voice; it does not clone Prince or imitate a real person. The first configured voice is American English.
- Voiceover is constrained to 30–48 words for the 24-second format. The renderer uses ffprobe to reject output without both audio and video, the required 720×1280 format, or an approximately 24-second duration.
- It deliberately rejects tragedies, graphic violence, crime sensationalism and unsupported claims. It skips documentary topics when it cannot identify two independent source domains.
- No third-party songs, lyrics or downloaded creator videos are used as source material.

## Cloud services and free-tier controls

- GitHub Actions: daily cloud runner, using this public repository's standard runners.
- Cloudflare Workers: dashboard API and daily cleanup.
- Cloudflare D1: run history, quotas and insights.
- Cloudflare R2 Standard: private source media and renders.
- Cloudflare Workers AI: shared daily free allowance. At quota/rate-limit errors, the job stops; there is no paid fallback.
- GDELT and Google News RSS: public research feeds.
- Kokoro-82M + SoundFile + eSpeak NG: free cloud CPU narration.
- Python standard library, Pillow and FFmpeg: original synthetic soundtrack, image cards, subtitles and video assembly.

Free tiers have quotas and can change. The system is capped at one attempt per day, three generated images per short, no automatic paid fallback and 30-day render cleanup. Keep R2 use under the included allowance.

## One-time setup: R2-free GitHub cloud mode

The first working version does **not** require a Cloudflare Worker, D1 database, R2 bucket, or R2 subscription. Video production runs on GitHub-hosted runners while your computer is off. The MP4 is stored as a temporary GitHub Actions artifact.

### Required GitHub Actions secrets

Open **Settings → Secrets and variables → Actions** and keep these two secrets:

| Secret | Purpose |
|---|---|
| `CF_ACCOUNT_ID` | Cloudflare account ID used by Workers AI |
| `CF_AI_TOKEN` | Cloudflare Workers AI token with Workers AI Read and Workers AI Edit permission |

The workflow uses Workers AI for script planning and three original FLUX still images. The free allowance can be limited; when AI returns a quota or permission error, the run stops. It has no paid fallback.

Previously created secrets such as `CF_DEPLOY_TOKEN`, `DASHBOARD_TOKEN`, `AUTOPILOT_JOB_TOKEN` and `GH_DISPATCH_TOKEN` are not used in this mode. They can remain saved for now; do not paste their values into chat or repository files.

### First manual draft

1. Open **GitHub → Actions → Violin Prince Autopilot**.
2. Select **Run workflow** on the `main` branch.
3. Keep publishing disabled. The workflow forces `PUBLISH_ENABLED=false`.
4. When it succeeds, open the run and download the `cloud-video-preview-...` artifact.
5. The diagnostic artifact includes the research, creative plan, metadata and quality report when available.

The video includes three AI-generated still scenes, synthetic narration, an original synthetic string-style soundtrack, subtitles and FFmpeg assembly. This R2-free mode does not load a personal recording; the synthetic soundtrack is not a real recording of Prince playing violin.

### Optional daily schedule

The workflow contains a daily schedule at 05:30 UTC (11:00 AM Asia/Kolkata), but it is guarded and remains **disabled** until the first manual draft succeeds.

After the manual draft has passed, open **Settings → Secrets and variables → Actions → Variables**, create a repository variable named `AUTOPILOT_SCHEDULE_ENABLED`, and set its value to `true`. Set it only when daily generation is intended. You can set it to `false` to pause scheduled runs. GitHub-hosted standard runners are free for public repositories, but artifact storage is limited on GitHub Free; artifacts from this workflow are retained for 14 days.

### What this mode does not include

- No permanent cloud media library or uploaded-audio asset manager.
- No Cloudflare dashboard or run-history database.
- No automatic social publishing. Publishing is disabled.
- No permanent video hosting; download each artifact you want to keep.

The old Cloudflare Worker/D1/R2 deployment workflow is not required for this mode. Do not run **Deploy Violin Prince Autopilot to Cloudflare** unless an account owner has reviewed and approved the separate R2 usage-based billing terms.

## Publishing

Publishing is **off** in the current R2-free cloud workflow. The workflow sets `PUBLISH_ENABLED=false` directly, so adding publishing credentials or repository variables will not turn publishing on.

The current milestone is to produce and inspect a narrated draft artifact first. Any later publishing integration must be separately reviewed, explicitly authorised by the relevant account owner, and tested with private/unlisted settings before public publishing. The underlying composition and recording rights must also be checked.

## Failure policy

- If Workers AI quota is exhausted, stop. No paid API is called.
- If research feeds are unavailable or no suitable topic is found, skip the video.
- If generation or rendering fails, preserve diagnostic files as a workflow artifact when available.
- The scheduled workflow is disabled until the repository variable `AUTOPILOT_SCHEDULE_ENABLED=true`.
- In standalone R2-free mode, use the original synthetic soundtrack; personal recording uploads are not configured.
- Publishing is forced off in the current workflow.
- Public source headlines are evidence inputs, not instructions. The system must not copy article text, scripts or lyrics.

## Files

- `engine/run.py`: research, planning, generation, rendering and orchestration; can run without a Worker/API.
- `engine/synth_audio.py`: original synthetic soundtrack generator.
- `.github/workflows/violin-prince-autopilot.yml`: manual and guarded daily GitHub-hosted cloud production workflow.
- `.github/workflows/deploy-autopilot-cloudflare.yml`: legacy optional Cloudflare Worker/D1/R2 deployment; not required for the current R2-free workflow.
- `cloudflare/src/worker.js`, `cloudflare/schema.sql`, and `cloudflare/wrangler.toml`: legacy optional dashboard and media-library backend.
