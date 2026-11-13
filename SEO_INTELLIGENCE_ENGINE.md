# Violin Prince — Shared SEO Intelligence Engine

**Architecture:** Discover → Optimize → Learn  
**Scope:** SEO and audience-search intelligence only. It does not control video rendering, visual generation, or publishing approvals.

## Why this is shared

The Autopilot has one SEO intelligence package at `autopilot/engine/seo_intelligence/`. Phase 1, Phase 4 and Phase 5 call the same package so that search research, metadata preparation and report-based learning do not drift into separate systems.

## 1. Discover — before the creative planner chooses a video

During Phase 1 Prepare, Discover runs before `make_plan` selects the subject. It uses the editable `channel_profile.json`:

- Brand: **Violin Prince**
- Creator identity: **Prince Baidya**
- Region: **India**
- Search languages: **English, Hindi and Bengali**
- Channel themes: Western violin covers, Bollywood/Hindi songs, Bengali songs, English pop arrangements, violin performance and gamaka.

The profile currently assigns nine bounded YouTube search queries per run: three in each language. Phrases rotate through the larger configured profile so later runs cover different channel-specific queries. The search sampler observes public result titles, publication dates and available view counts. It can calculate sample-level median views per day and recent-upload share. It labels the result as an observed sample, not search volume.

After the story planner selects one candidate topic, Discover performs a second, video-specific search in all three languages (topic + violin-cover wording). This is three more bounded `search.list` queries. A full Prepare therefore makes at most 12 search queries: nine channel-profile searches and three candidate-topic checks. The topic checks are saved separately as `topic_validation` and are used by Optimize when choosing a relevant keyword for the final metadata review.

The YouTube Data API does not provide exact keyword search-volume figures. Missing search results, missing counts and missing API credentials remain explicitly unavailable; the engine does not invent numbers.

The creative planner receives two separate inputs:
1. Editorial research records (GDELT / Google News) remain the **only factual sources** for story claims.
2. YouTube Discover samples are **demand clues only** to help select a topic that fits the channel. Competitor titles are not copied and public views are not treated as facts about the story.

If no `YOUTUBE_API_KEY` is configured yet, Discover still records the channel's multilingual search plan and clearly reports that live sampling is unavailable. Video production does not silently claim that a live search occurred.

## 2. Optimize — after the MP4 has been rendered

After a video file is rendered, Optimize uses the actual creative plan and saved Discover snapshot to prepare:

- Primary keyword
- Title suggestions (the original creative title is preserved)
- Description
- Ordinary YouTube tags
- Up to three hashtags
- Detected or declared content language
- A compact audit of the selected phrase and metadata limits

The review package records these as suggestions. **Optimize never approves its own metadata.** The YouTube uploader still requires `seo_metadata_approved=true` and all separate publishing gates before an upload can happen.

The same optimizer is called by the native YouTube metadata builder so Phase 4 does not implement a second keyword-selection rule.

## 3. Learn — Phase 5 report review, not continuous polling

The video-render stage does not request YouTube Analytics reports. Phase 5 owns report collection through:

- A weekly GitHub Actions schedule: Monday 03:00 UTC (08:30 India time).
- A manual `workflow_dispatch` option for a deliberate report run.

Each report run makes one bounded 28-day per-video Analytics request and one seven-day channel summary request. It reads available video metadata to associate a video's actual language and saved video tags with that report row. It also requests the top YouTube Search terms that generated views, grouped by declared or script-detected video language, using YouTube's `insightTrafficSourceDetail` dimension filtered to `YT_SEARCH`. For each eligible language it samples three videos individually (at most nine additional report requests in a weekly run). The report records how many of those separate video reports returned each exact phrase; a term only enters Discover learning when all three sampled videos report it. Unlabelled Latin-script titles remain `unknown` rather than being guessed as English. No repeated polling loop is used.

The Learn step is rules-based (not another text-generation call). It:
- Groups available per-video rows by English, Hindi and Bengali language.
- Reviews per-video average percentage viewed, watch duration, views and engagement where returned.
- Groups keyword evidence using the first actual YouTube video tag when available.
- Captures real search phrases reported as traffic sources for groups of at least three channel videos, along with the views attributed to those phrases.
- Feeds sufficiently supported real search phrases into the next Discover run, replacing one lower-priority profile query in the matching language while preserving all three language groups.
- Requires at least three videos before marking a language group as above or below the channel median.
- Leaves small samples as **insufficient data** and keeps all three languages in the Discover test mix.
- Marks metrics as unavailable when the report does not supply them. It does not invent thumbnail CTR or claim that a tag caused a video's views.

The resulting SEO-only learning snapshot is stored with the existing Cloudflare D1 channel-insights record. Phase 1 reads the latest stored snapshot from the authenticated `/internal/seo-learning` endpoint during the next Discover run. The weekly schedule takes effect when this workflow is present on the repository's default branch; a manual trigger is available on the feature branch for validation.

**Learning can change only SEO search allocation and Discover query prioritisation.** It does not rewrite the general creative engine, visual direction, narration, quality-control thresholds, or publishing permissions.

## Data and credentials

- Live public YouTube search sampling: `YOUTUBE_API_KEY`.
- Phase 5 private channel report access: Google OAuth must include the current read-only YouTube scope accepted by the Analytics `reports.query` endpoint (`youtube.readonly`) and the scopes independently required by the upload/privacy workflow. The exact consent set will be verified during the Phase 4 OAuth test.
- Phase 5 storage: existing authenticated Cloudflare Worker `/internal/insights` endpoint and D1 `channel_insights` table.
- No Google Drive or Metricool dependency.
- No OAuth values or API keys are committed to this repository.

The Analytics read-only scopes are documented by Google. Request only scopes the enabled parts of the system actually use; they are not supplied automatically by this code.

## Safety state

The SEO engine does not turn on any upload or publication gate. Phase 4 remains offline-tested until OAuth is deliberately configured and a separate private upload is approved. Public visibility continues to require its independent approval.
