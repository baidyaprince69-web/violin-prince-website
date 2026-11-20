# Violin Prince Autopilot

A cloud-first short-video production pipeline. GitHub-hosted runners do the production work; the creator's computer does not need to stay on.

## ChatGPT-operated daily production

ChatGPT is the only daily scheduler. Its existing daily automation prepares one sourced production plan, writes `.autopilot/daily-production-plan.json` to `main`, then updates `.autopilot/prepare-request.json` to trigger this workflow. The GitHub Actions runner produces the MP4 and creates a public GitHub Release asset. ChatGPT then reads that release and schedules the YouTube Short through the connected Metricool brand with automatic publishing enabled.

- The production entry points are currently locked before research or rendering until the creator's own voice has been tested and explicitly approved. There is no Kokoro, preset, generic or third-party narrator fallback.
- The former Cloudflare-based text, image and media services have been removed. No replacement text-planning or illustration provider is currently configured; those stages must stop until an approved non-Cloudflare provider is selected and tested.
- The final scene is a symbolic violin-performance visual unless a permitted creator recording is deliberately added; generated/sample violin audio must never be described as a live recording by the creator.
- The production job keeps direct publishing disabled and creates the verified public GitHub Release handoff. ChatGPT uses the connected Metricool brand as the primary publisher. Only when Metricool confirms its monthly post limit has been reached does ChatGPT push `.autopilot/publisher-fallback-request.json`, triggering the separate `.github/workflows/publisher-fallback.yml` route. That route revalidates the exact MP4, manifest and provenance, stores a durable no-duplicate attempt marker, then reuses the existing Google OAuth/resumable uploader in `engine/publisher.py` to publish directly to YouTube. It does not rerun production. vidIQ remains analytics/optimisation only; its approval-dependent draft route is not an unattended fallback.
- The GitHub cron schedule has been removed. ChatGPT is the daily operator and triggers the request-file push.
- The manual `workflow_dispatch` stage selector remains visible, but all production stages currently stop at the own-voice gate. The Visuals stage also remains disabled until an approved non-Cloudflare illustration provider is configured.

## Approved channel identity and production format

The standing creative direction is **Violin Prince = music facts + cinematic visual explanations + the creator's own violin performance**. This channel-format decision is recorded in `engine/creative_direction.py`; it is not the same as the separate review of an individual prepared story.

The editorial gate accepts only these story categories: violin physics, instrument design, sound and perception, melody and composition, song anatomy, music production, music technology, and violin-cover breakdowns. It rejects individual-musician biographies, career profiles, competition-result stories and celebrity profiles as the main subject. If the evidence pool only contains those topics, Prepare should stop rather than force an unsuitable story.

The daily cloud-first visual implementation is an illustrated 2D pipeline. Its character rig accepts original separated artwork; it does not claim to generate a complete layered character automatically from one portrait.

- 24-second vertical video, 720 × 1280.
- Target visual direction: three original 2D editorial illustrations with precise linework, painted materials, layered shading and the midnight-navy / muted-teal / antique-gold palette. Illustration generation is currently disabled until a replacement provider is approved and tested.
- Target renderer: Motion-driven scene entrances, spring movement, crossfades, character poses and gestures, expression-layer animation, and word-synchronised captions. HyperFrames captures exact frame times; FFmpeg performs final audio/caption finishing and QA. The legacy manual recovery path retains its frame-by-frame Pillow explainer renderer.
- Structured visual modes: illustrated macro detail, illustrated mechanism cutaway, waveform, melody map, comparison, and cover-performance payoff.
- Scene 3 is planned as the musical payoff and must include a `cover_payoff` explaining how an original Violin Prince violin phrase demonstrates the fact.
- Target narration: four-sentence, 40–44-word English script voiced only by the creator's tested and approved own-voice provider. No voice synthesis is currently enabled.
- A creator-recorded violin take when supplied. Otherwise, the existing CC0 sampled-violin path remains available, with the existing ambient fallback if sample retrieval fails.
- Target scene timing follows measured narration beats. The approved own-voice provider must supply validated word timestamps for each spoken-word highlight; rendering must stop if timings are missing or invalid. FFmpeg validates final picture and audio.

**This is a 2D illustrated animation pipeline, not a 3D renderer or image-to-video model.** The scene plates are AI-generated illustrations; a character can be animated only when its separate original body, face, arms, hands, joint anchors and expression assets are present. The rig validator rejects missing parts rather than replacing them with geometric placeholders.

### Render quality correction — version 6

- Remove the repeated 5.5% zoom/push-in; keep photographic framing steady and let authored overlays supply purposeful motion.
- Preserve the approved voice provider's native token start/end timestamps. The caption layer uses those timestamps for word-by-word highlighting and blocks rendering when valid timings are unavailable.
- Replace the single heavy bold-font treatment with separate display, label and body-text roles. Scene headlines use a serif display face; explanatory text uses a lighter sans-serif face.
- Simplify the explainer panel: the photograph stays dominant, the diagram occupies a compact upper-right window, and each story mode has a distinct animated visual instead of a repeated generic card.
- The final type system uses **DM Serif Display** for editorial headlines and **DM Sans** for labels, supporting copy and word-synchronised captions. The WOFF2 assets are bundled with their original SIL Open Font License 1.1 notices in `engine/assets/fonts/`; fontTools creates local TTF working copies for Pillow and FFmpeg/libass. No remote font request is needed while rendering.
- The previous video was technically encoded but was not visually quality-approved. A frame/contact-sheet review is required for the first render after this correction before treating the new style as accepted.

### Preserved legacy manual renderer — Pillow motion system version 7

The legacy manual recovery renderer retains the established Pillow frame-by-frame animation system. The ChatGPT daily route instead uses Motion for JavaScript and HyperFrames for seekable, frame-accurate scene rendering:

- **Speech-led choreography:** scene-local timestamps from the approved own-voice provider will drive the motion panel's visual progress, focus marker, restrained beat pulse, and staggered label/headline/detail reveals. Changes follow spoken content words, not an arbitrary linear timer or music beat.
- **Deterministic spring animation:** every panel frame is derived from its local time using closed-form damped spring responses. The same frame can be regenerated independently; no CSS transition state, timers, Chromium capture, GPU, or paid video service is required.
- **Scene-specific visual grammar:** the existing macro, mechanism, waveform, melody-map, comparison, and performance modes remain. Their focus markers now advance on the words assigned to that scene.
- **Encoded-output verification:** after FFmpeg finishes, ffprobe must confirm H.264, 720 × 1280, approximately 25 fps, the 24-second duration contract, and a valid audio stream. The renderer also freezes six moments from the actual encoded MP4 into `visual-contact-sheet.png`; this sheet is kept with the render artifacts for inspection.
- **No invented data:** diagrams remain explanatory and source-grounded. Illustrative geometry is not presented as measured instrument data.

The legacy Pillow renderer retains the pure-time spring tracks and word-timed graphics. The daily renderer uses [Motion](https://github.com/motiondivision/motion) for JavaScript animation and [HyperFrames](https://github.com/heygen-com/hyperframes) as its installed HTML-to-video frame renderer. Both routes retain contact-sheet inspection and ffprobe validation. The talking-head-only object-separation workflow, high-energy product-promo templates, browser-based 4× motion-blur renderer, and large sound-effects bundle are not adopted: they add local/GPU/browser or editing overhead and do not fit this photo-first music-explainer pipeline.

A generated contact sheet is a review aid, not automatic creative approval. The first production MP4 using this version still requires a real frame/contact-sheet review before its visual style is accepted.

### Reference-informed 2D visual direction — version 8

OpenMontage's most useful idea for this engine is its **reference-video analysis contract**: understand a reference's pacing, shot types, visual language and whether it uses moving clips or animated stills before deciding how to reproduce its broad craft. We are adopting that idea without installing OpenMontage, Remotion, yt-dlp, PySceneDetect, WhisperX, or another provider stack.

ChatGPT may add an optional `visual_reference` object to the daily production JSON after it has actually reviewed a supplied reference. The engine validates the brief and maps it into the three existing scenes:

- `visual_language`: `illustrated_editorial`, `macro_documentary`, `kinetic_graphics`, or `hybrid`.
- `pacing`: `rapid`, `dynamic`, `steady`, or `slow`; this selects a short, bounded transition duration.
- `motion_profile`: `video_clips`, `animated_stills`, `mixed`, or `static`; this is used for honest capability reporting, not to invent a video-generation provider.
- Three `scene_guidance` entries specify a shot type, an optional small pan (`locked`, `pan_left`, `pan_right`, `pan_up`, `pan_down`), and the outgoing transition (`crossfade`, `wipe_left`, `wipe_right`, `smooth_left`, `fade_through_black`).

Example shape:

```json
{
  "visual_reference": {
    "source_url": "https://www.youtube.com/shorts/REFERENCE_ID",
    "reference_summary": "Fast macro reveals and dimensional explainer graphics",
    "motion_profile": "animated_stills",
    "visual_language": "illustrated_editorial",
    "pacing": "dynamic",
    "scene_guidance": [
      {"shot_type": "extreme_macro", "camera_move": "pan_left", "transition_out": "wipe_left"},
      {"shot_type": "mechanism_cutaway", "camera_move": "pan_up", "transition_out": "smooth_left"},
      {"shot_type": "performance_close", "camera_move": "locked", "transition_out": "crossfade"}
    ]
  }
}
```

If the reference uses real video clips (`video_clips` or `mixed`), the render report records that limitation: the intended engine uses still 2D scene illustrations animated by Motion and captured by HyperFrames, not new AI video clips. Illustration generation is currently disabled pending provider selection. The system adapts only high-level craft, never exact frames, text, logos, music, assets or another creator's identity. If no reference analysis is supplied, the existing Violin Prince visual direction and stable framing remain unchanged.

This adds no runtime dependency, paid provider, extra API call or new scheduler. ChatGPT remains the daily operator; GitHub Actions remains the cloud production worker; publishing stays outside the render workflow.

Direct publishing remains disabled inside GitHub Actions. The ChatGPT-operated daily route publishes only through the connected Metricool account after the required YouTube audience setting is confirmed.

### Publisher preflight and asset provenance — version 9

A selective review of [YouTube Automation Agent](https://github.com/darkzOGx/youtube-automation-agent) added two safeguards to the ChatGPT daily handoff without importing its local Node/Chromium application, provider stack, scheduler or direct-publishing agents.

- **Metadata validation runs before scene generation.** YouTube titles are limited to 100 characters, descriptions to 5,000 characters, and tags are de-duplicated and capped at 30 tags / 450 combined characters. Category ID, language tag and privacy status are normalized and checked. Empty descriptions and short tag lists produce warnings; invalid required fields stop the run before it spends on visuals.
- **The GitHub release now includes two JSON handoff assets:** `publish-manifest.json` and `asset-provenance.json`, alongside the MP4. The manifest gives ChatGPT the normalized title, description, tags, privacy setting, synthetic-media disclosure, source references and publisher-preflight result.
- **The provenance record** identifies verified publisher articles and the exact quotes used to support narration sentences, and stores SHA-256 hashes and origin metadata for generated scene images, approved own-voice narration, soundtrack and final MP4 when production is re-enabled. It records the pinned CC0-1.0 sample-bank license and attribution when that violin soundtrack is used. AI-generated imagery and narration are labelled as synthetic; provider terms still apply.
- **Audience setting:** the existing channel-level confirmation says Violin Prince is **not made for kids**. The manifest records `made_for_kids: false` from that saved setting; ChatGPT must use it for Metricool and should not ask again. A future explicit boolean in the plan can override it. A malformed/non-boolean override is not silently coerced and places the release on hold.
- Unknown soundtrack origin/license metadata also places the release on hold. The provenance document is an origin-and-license record, not a legal opinion or blanket rights clearance.

The ChatGPT production plan can provide the publishing fields under `publish_metadata` (or use the compatible top-level fields):

```json
{
  "publish_metadata": {
    "title": "Why Violin Strings Vibrate",
    "description": "A short, sourced explanation of violin acoustics.",
    "tags": ["violin", "music", "acoustics"],
    "privacy_status": "public",
    "made_for_kids": false
  }
}
```

The boolean above is an example only; the daily operator must use the channel's actually confirmed audience classification. Existing evidence-first research and the separate encrypted YouTube SEO learning workflow remain in place.

### Legacy source-backed Pillow motion graphics and story coherence — version 10

The renderer now accepts optional structured graphic data per scene and turns it into animated explanatory graphics, driven by the existing narration-word timing:

- An arch-height chart displays measured values and labels. Values are rendered only when supplied by the verified plan; no interpolated or invented measurements are added.
- A process-flow graphic reveals the actual steps in a physical or musical mechanism.
- Scenes without a supported data structure retain their existing waveform, melody-map, comparison or performance visualiser.

The chart and process-flow stages use deterministic spring easing, colour-coded states, readable labels and a narration-following progress line. They are composited over the full-colour scene plate; they do not replace the violin hero image. The image prompt now explicitly requires a solid, fully formed amber-brown violin body and excludes hollow shells, transparent bodies, outline-only instruments and monochrome line art.

A second new gate checks **story coherence**, not just quote existence. Each publisher article cited by narration must independently share enough subject anchors with the same core claim (or the descriptive video title when no core claim is supplied). The run stops when a cited source is unrelated, even if its quote is exact and the publisher page is valid. This is a conservative deterministic relevance check, not a semantic fact checker; all source pages and exact quotes still have to pass the existing checks.

The former Cloudflare-based still-image service has been removed. Scene illustration generation is disabled in both routes until a non-Cloudflare provider is approved. Motion, HyperFrames, Pillow and FFmpeg remain the rendering targets once an illustration input exists. Neither route claims to generate AI video footage.

## Research basis and implementation choices

The current design borrows production patterns rather than another creator's identity:

- [Explainroo](https://github.com/vincentsch/explainroo) (MIT): measured speech timing, deterministic frame rendering, captions, motion and media QA.
- [Explainer Studio](https://github.com/pramodthe/explainer-studio) (MIT): structured scene templates and audio-first timing.
- [marketing-videos](https://github.com/sub-level/marketing-videos) (MIT): separate code-generated graphics from optional footage, use design tokens and verify final renders.
- [paper2video](https://github.com/edwardyen724-g/paper2video) (Apache-2.0): research-to-script-to-scene orchestration and Manim as a specialist educational-animation option. Its LLM-generated Python execution model is not copied.
- [aliberson/openmontage](https://github.com/aliberson/openmontage) (AGPL-3.0): reference-video analysis, motion-type classification, structured scene direction and capability reporting. Only the high-level reference-analysis pattern is adopted; no OpenMontage source code, provider integrations or Remotion runtime are copied or installed.
- [darkzOGx/youtube-automation-agent](https://github.com/darkzOGx/youtube-automation-agent) (MIT): verified production readiness, durable generation recovery, claim/media provenance, upload metadata validation and fail-closed publishing. We selectively adopt metadata/provenance handoff safeguards; its local Node/Chromium dashboard, local scheduler, paid-provider catalogue and direct YouTube/social publishers are not installed or substituted for ChatGPT + Metricool.
- [iart-ai/motion-skills](https://github.com/iart-ai/motion-skills) (MIT) and [Barty-Bart/motion-graphics](https://github.com/Barty-Bart/motion-graphics) (MIT): deterministic animation principles, speech-aware choreography, freeze-frame review, contact sheets and encoded-video probing; the relevant craft patterns are already represented in motion system version 7.

The daily implementation uses the separate Motion + HyperFrames 2D engine; the existing Python / Pillow / FFmpeg manual recovery route remains preserved. No repository implementation code or third-party assets are copied into the project.

Other candidates reviewed but not added to the daily engine:

- [Agnes Video Generator](https://github.com/lcy362/agnes-video-generator) (MIT) offers multi-scene AI video generation, but it is not a dependable zero-cost default for unattended daily production: remote inference access, model availability and request limits need a separate verified test before any integration.
- AI Content Studio was not imported as a complete application; its extra stack would duplicate orchestration without improving this engine's existing evidence-first daily path.
- The n8n YouTube-to-Shorts workflow repurposes an existing long video, while this channel's pipeline creates original music-fact stories and original violin payoffs.
- Paper2Video is aimed at turning research papers into presentation videos; its heavier research-animation workflow is not a fit for this short-form music channel.
- Chatterbox is not added as another voice engine. The production target is the creator's own tested voice through Qwen3-TTS, with GPT-SoVITS evaluated separately as a backup candidate.

The new OpenMontage repository is licensed under AGPL-3.0. This update is an independent implementation of a small workflow idea, not a copy or port of its code.

## Automated editorial quality gates

The standing Violin Prince channel direction is already approved. The workflow no longer asks for a second `story_approved` checkbox. Prepare must pass the direct-source, independent-publisher, date, freshness, narration and channel-fit checks. Visuals repeats the channel-fit and quality-control checks before generating any scene images. If a check fails, the run stops and records the reason; an unsuitable story is not forced through. Render verifies that the automated gate was recorded before assembling the MP4.

The daily ChatGPT route validates the same source/date/freshness/channel-fit gates before rendering. You can inspect `review.txt`, `quality_control.json` and `storyboard-preview.png` in the run artifacts; no manual download or approval is required to render.

## One-click production and stage recovery

The Full/Prepare/Visuals/Render stage choices remain in the workflow for recovery compatibility, but production is currently locked. The first step of each runner checks the own-voice approval gate and exits before research, narration, remote generation or rendering.

1. **Prepare** — intended to fetch research, select a sourced music-fact story and save a package. Currently blocked before research.
2. **Visuals** — intended to create scene plates and a storyboard. Currently disabled until an approved illustration provider is configured.
3. **Render** — intended to assemble a saved package. Currently blocked by the own-voice production gate.

After the own-voice sample is reviewed and approved, the text-planning and illustration providers must also be selected and tested before these stages can be re-enabled. A failed Full run ID can be used to recover preserved research with Prepare. Valid scene images are reused on partial Visuals retries.



## Evidence-first research and story selection

Prepare now uses a source-first sequence rather than choosing a topic from headlines and searching for evidence afterwards:

1. Broad research collects article leads from free discovery providers, including direct publisher links from DuckDuckGo.
2. Google News RSS article IDs are resolved to publisher destinations before article checks. The system fetches the publisher page, compares its headline with the discovery headline, and extracts readable article paragraphs. Aggregator pages and headlines remain discovery leads only.
3. Research grouping considers the full bounded discovery pool rather than silently truncating targeted results after the first 100 records. Category/section pages that merely advertise `og:type=article` are rejected unless the page title also matches the specific story.
4. Readable articles are grouped only when they share a distinctive named subject present in both article bodies. Broad genre overlap such as “film music”, roundup titles, or generic section language is not corroboration. A group must contain at least two independent publisher families. Same-family subdomains and substantially syndicated article copies do not count as independent corroboration.
5. The editorial planner can select only from those eligible groups. Its source IDs must belong to one selected group; it cannot combine unrelated groups or invent a new topic.
6. Publication freshness is flexible: sources published within 50 hours are preferred, but specific verified publisher articles up to **seven days (168 hours)** old remain eligible. Articles older than seven days, with unknown publication dates, or with future-dated metadata are excluded.
7. Topic-specific searches may enrich research, but final citations are locked to the exact sources in the selected story group. The narration evidence, timeline, event dates, and quality-control gates still run before a prepared package is created.

Publisher article metadata (including Article/NewsArticle structured data and publication timestamps) is preferred over discovery timestamps. Category, tag, topic, archive, directory, event-listing, aggregator and encyclopedia pages do not count as independent article sources. Timeline dates are also checked against explicit dates in the selected articles.

If a recovered research artifact contains only headlines, unverified pages, or stale articles, Prepare discards that cache and performs fresh discovery. The story_candidates.json diagnostic records article-page checks, publication timestamps, age in hours, the preferred/acceptable freshness status, exclusion reasons, eligible groups, publisher families, source IDs and evidence excerpts.

A story with fewer than two independent, readable, article-specific publisher sources inside the seven-day window is rejected. The source threshold is not relaxed to make a run succeed. A narration sentence must also be complete; a short script ending mid-phrase (for example, on a dangling preposition) is rejected before narration audio is generated.

## Add your real violin performance

The previous Cloudflare-backed Autopilot media dashboard has been removed. This repository currently has no remote creator-media upload service. Use the symbolic violin-performance visual until a safe, private creator-media input route is implemented.

Creator performance video and custom soundtrack upload are not currently available through the Autopilot dashboard. Do not commit private recordings to this public repository. The production path will use its approved symbolic fallback until a separately reviewed private input mechanism is implemented.

If no performance video is uploaded, Scene 3 uses its generated cinematic violin-performance visual. If no custom music bed is uploaded, the cloud runner creates a solo violin bed from the CC0 String Studio / VSCO 2 CE sample pack; if sample retrieval fails, it uses the ambient fallback.

An `.sf2` or `.sfz` file is an instrument bank, not a finished recording. Custom instrument-bank uploads are not supported.

## Running the workflow

Open **GitHub → Actions → Violin Prince Autopilot** to inspect the workflow and its run history.

### Current workflow status

The manual stage selector remains visible for recovery compatibility, but production is deliberately locked. Every production entry point first checks the own-voice approval gate and exits before research, soundtrack preparation, narration, scene generation or rendering.

The only currently runnable voice-related workflow is **Qwen3-TTS isolated voice preflight**. It downloads public model weights and checks package/API compatibility and CPU model loading; it does not use your recording or generate speech.

After the own-voice sample is reviewed and approved, text planning and scene illustration providers must still be selected, reviewed and tested before video production can resume. Until then, running **Full**, **Prepare**, **Visuals** or **Render** will not produce a video.

## Services, limits and privacy

- **GitHub Actions** runs the stages in the cloud. No local PC processing is required.
- **Cloudflare is not part of the current Autopilot.** Its former Worker, D1, R2, Workers AI and deployment workflow have been removed. The production workflow requires no Cloudflare secrets or account.
- **Voice:** production narration uses only the creator's tested and approved own voice. The current fail-closed gate prevents all production stages until the voice sample is approved. Kokoro and other generic narrator fallbacks are prohibited.
- **Text and illustration providers:** no provider is currently configured. These stages remain disabled until a non-Cloudflare option is selected, reviewed and tested.
- **Motion + HyperFrames** remain the intended renderer; **Pillow** remains in the legacy local/manual rendering path; **FFmpeg** performs final audio mixing, captions, MP4 encoding and QA once production is unlocked.
- GitHub Actions keeps direct publishing disabled (`PUBLISH_ENABLED=false`); ChatGPT hands a successful public release asset to Metricool for YouTube scheduling.
- There is no GitHub cron schedule. The separate ChatGPT daily automation owns the schedule and triggers this workflow by updating the request file.
- Do not put API tokens or passwords in prompts, files, source code or chat. Keep tokens in GitHub repository Actions secrets.

## Creative and editorial limits

- Scene illustrations are generated as still 2D artwork and animated with Motion. When separate original character layers are supplied, the rig connects joints, hands, poses, gestures and facial-expression images. The factory validates/stages these parts; it does not yet split one portrait into those layers automatically.
- Narration is locked pending approval of the creator's own voice. When no custom music bed is supplied, the intended workflow uses real recorded violin multisamples arranged into a fresh phrase; it is not a live performance or text-to-music AI model. Ambient fallback is only a music-bed fallback.
- The image prompts use a consistent illustrated visual direction, shared palette, layered depth and distinct scene roles.
- Visual-stage connection timeouts receive one bounded retry. Permission/quota/rate-limit errors stop clearly; no paid fallback is used.
- Automated tests validate narration length, scene timing, art-direction consistency, subtitle formatting, partial visual recovery behavior, creator-performance insertion and final FFmpeg rendering.
- The planner should only use supplied research, avoid unsupported claims and choose a family-friendly topic. If a story cannot be sourced, it should stop rather than invent details.
- No lyrics, copied scripts, third-party creator videos, identifiable living people, logos or copyrighted characters are requested in generated artwork.

## Repository files

- engine/run.py — legacy research/planning and the shared staged render engine.
- engine/ENGINE_WORKFLOW.md — canonical end-to-end production workflow, component map, current implementation status, quality gates, publishing/analytics boundaries and future development rules.
- engine/run_daily_plan.py — source-verifies ChatGPT-authored daily plans, stages illustration/character assets and invokes Motion + HyperFrames.
- engine/hyperframes_pipeline.py — builds the seekable HTML scene project, renders with HyperFrames and finishes with the existing FFmpeg audio/caption/QA stages.
- engine/character_rig.py and engine/illustration_asset_factory.py — validate and stage separated character art layers, joints, hands, poses and expressions.
- engine/animation2d/ — isolated JavaScript project containing Motion, the HyperFrames composition builder, and frame/keyframe tests.
- engine/voiceover.py — fail-closed own-voice production gate and timing helpers.
- engine/violin_sampler.py — checksum-verified CC0 sample download and solo-violin phrase rendering.
- engine/synth_audio.py — quiet ambient fallback used only if the recording and sample-instrument paths are unavailable.
- engine/tests/ — offline regression, model-contract, storyboard and FFmpeg render tests.
- .github/workflows/violin-prince-autopilot.yml — staged production and verified public-release workflow.
- .github/workflows/publisher-fallback.yml — separate push-triggered direct YouTube fallback after confirmed Metricool monthly quota exhaustion.
- engine/publisher.py — existing OAuth token-refresh and resumable YouTube upload adapter.
- engine/publisher_router.py — manifest/provenance validation, durable attempt guard and direct-upload receipt.
- engine/tests/test_publisher_router.py — offline regression tests for the fallback guard and receipts.
- .github/workflows/autopilot-checks.yml — offline code and workflow validation.

## ChatGPT-triggered 2D illustrated production architecture

The ChatGPT request file remains the only daily trigger. The main workflow now follows this order:

1. **ChatGPT Trigger** — `.autopilot/prepare-request.json` points to the current source-checked daily plan.
2. **AI Story & Scene Director** — the daily runner verifies publisher evidence, narration, scene order, and channel fit.
3. **Illustration & Character Asset Factory** — currently disabled until a non-Cloudflare image provider is selected and tested. The character asset factory can still validate and stage separate original character artwork.
4. **Character Rig** — torso, head, face, left/right upper arms, forearms and hands are separate layers. Normalised neck/shoulder/elbow/wrist joints provide pivot anchors. The plan can select poses, gestures and facial-expression artwork for each scene.
5. **Motion** — Motion for JavaScript generates deterministic spring-sampled keyframes for movement, gestures, entrances, transitions and expression changes. Animations are paused and seekable.
6. **HyperFrames** — the HTML composition is linted and rendered frame-by-frame with a fixed FPS and timeline. Motion's Web Animations are driven by HyperFrames' seek-based WAAPI adapter.
7. **Previews and MP4 output** — the workflow creates a storyboard preview and a final visual contact sheet, alongside the rendered MP4.
8. **Existing FFmpeg finishing and QA** — FFmpeg mixes narration/music, burns word-timed captions, encodes the final MP4, and ffprobe validates the media contract.

### Character artwork requirements

A detailed rig is not fabricated from generic circles or stick figures. A character plan must provide separate original image assets for the torso, head, face, both upper arms, forearms and hands; normalised joint anchors; and a neutral expression plus at least one alternate face expression. Each part needs its own position, size and pivot. Incomplete assets stop the character-rig stage instead of generating a misleading substitute.

The current asset factory stages and validates those separated illustration files; it does not yet turn a single character portrait into perfectly separated cut-out parts. Scene illustration plates are not generated at present; a non-Cloudflare provider must be selected before that stage is re-enabled.

### Frame-by-frame preservation

The existing `motion_graphics.py` Pillow renderer and its frame-by-frame animation tests are retained for the legacy manual recovery route. The ChatGPT daily route uses the isolated Motion + HyperFrames renderer.

### Safety and production gates

The GitHub workflow's `PUBLISH_ENABLED` setting remains `false`. The code-check workflow tests the rig contract, Motion spring sampling and HyperFrames HTML linting, but it does not run a full video production or publish a video.
