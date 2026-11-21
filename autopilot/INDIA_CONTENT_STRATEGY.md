# Violin Prince — India-first four-pillar content strategy

**Prepared:** 21 November 2026  
**Status:** Editorial strategy approved for planning. Four-a-day production and public publishing are NOT enabled by this document.

## Channel positioning

**Violin Prince** is an India-first, globally understandable music channel built around four connected ideas:

1. Discover something surprising about music and instruments.
2. Understand how music is recorded, mixed and produced.
3. Feel and understand why melodies work.
4. Hear the creator's real violin playing.

The channel should feel like one creator brand, not four unrelated channels. Explainers can use cinematic editorial graphics; actual performance posts must centre genuine creator recordings.

## The four daily content pillars

### 1. Secrets of Music & Violin

**Purpose:** Discovery and education.

**Subjects:** violin physics, instrument design, acoustics, sound perception, Indian instruments, bowing, resonance, vibrato, gamaka, meend, rhythm and other music concepts when the claim can be checked.

**Example angles:**
- Why can a violin sound almost like a human voice?
- What makes a string vibrate?
- Why does changing bow pressure change the sound?
- How do resonance and harmonics shape an instrument's tone?

**Production pattern:** one clear question, one simple explanation, one audible or visual demonstration. Define specialist terms instead of assuming the audience knows them.

### 2. Music Production & Audio Technology

**Purpose:** Reach musicians, home-recordists, producers and curious listeners.

**Subjects:** EQ, compression, reverb, delay, distortion, recording, microphones, audio interfaces, mixing decisions, plugins and music technology.

**Example angles:**
- What does reverb actually add to a violin recording?
- EQ versus compression: what does each one change?
- How can a transient be shaped without losing the note's body?
- Why can a close microphone sound harsh?

**Production pattern:** demonstrate the sound or signal path; distinguish a real test from a general explanation; name the plugin or product only when the video actually tests or explains it.

### 3. Melody Breakdown & Musical Stories

**Purpose:** Emotional connection and broad music discovery.

**Subjects:** melody, rhythm, harmony, arrangement, song structure, musical tension, phrase shape, Indian film-music ideas and Bengali or other regional-music examples where the analysis is accurate.

**Example angles:**
- Why does a particular melodic phrase feel nostalgic?
- How does a change in one note alter the mood?
- What makes a film melody memorable?
- How can rhythm change the emotional feel of the same tune?

**Production pattern:** use a short original demonstration or an appropriately cleared example. Explain the musical idea rather than reproducing copyrighted lyrics, sheet music or a full commercial recording.

### 4. Real Violin Performance

**Purpose:** Build the recognisable artist identity of Violin Prince and give viewers a reason to return for the music itself.

**Subjects:** genuine creator-recorded moments from covers, original violin pieces, Bengali/Hindi/English repertoire, expressive phrases, melodic hooks, gamaka and vibrato passages, and longer-video highlights.

**Production pattern:**
1. Start from a real video/audio recording supplied or explicitly selected by the creator.
2. Review intonation, rhythm, bow control, tone, phrasing and expression.
3. Find a self-contained 15–45 second passage with a strong musical beginning and payoff.
4. Make a clean vertical edit: preserve the real performance audio, use restrained titles/captions, and avoid overlays that hide the instrument or hands.
5. Show the proposed cut and metadata to the creator for review before publishing.

**Authenticity rule:** never present generated violin imagery, sampled violin audio or an illustrated character as a live performance by the creator. The real-performance pillar needs a separate creator-recording intake and clip-extraction workflow; the current symbolic performance scene is not a substitute.

## Daily publishing target

The intended mix is **one video from each pillar per day: four distinct Shorts, approximately six hours apart**.

Provisional test slots in Asia/Kolkata:
- 06:00 — Secrets of Music & Violin
- 12:00 — Music Production & Audio Technology
- 18:00 — Melody Breakdown & Musical Stories
- 00:00 — Real Violin Performance

These are planning placeholders, not a claim that the times are optimal. Once enough channel data exists, compare slot-level engaged views, viewed-versus-swiped-away, average view duration, retention, returning viewers and subscriber conversion. Adjust times based on the channel's own audience data.

## India audience and language plan

- Start with clear, natural Indian English while the existing production plan and voice checks are English-based.
- Use familiar Indian examples where relevant: film melodies, regional music, instruments and musical vocabulary. Keep every factual statement specific and checked.
- Test Hindi/Hinglish packaging and Bengali localization as separate variants after the actual narration, spelling, subtitles and pronunciation have been quality-checked. Do not silently mix languages or assume every Indian viewer prefers the same language.
- Preserve a global-friendly visual explanation so a viewer can understand the idea even without local cultural context.

YouTube's 8 December 2025 India trends recap reported that 77% of surveyed Gen Z in India had watched translated content/creators and 68% used language picked up from online videos. This supports testing localization; it does not prove which language or slot will work best for this channel. Source: [YouTube/Google India — 2025's biggest trends on YouTube](https://blog.google/intl/en-in/products/platforms/2025s-biggest-trends-on-youtube-that-gave-india-a-new-shared-vernacular/).

## Editorial and production rules

- Keep each upload genuinely distinct. Do not repackage one script or video four times.
- For factual explainers, retain the current evidence-first rule: at least two independent, directly readable publisher sources for claims that depend on external reporting. For basic music theory, use a reputable reference or a demonstrable musical example and record the evidence.
- The opening should communicate one specific promise quickly. The middle should explain one idea. The ending should deliver an audible, visual or conceptual payoff.
- Keep narration understandable on a phone. Captions must be proofread, synchronised and inside mobile-safe margins.
- Use original demonstrations, creator-owned material, properly licensed material or YouTube's permitted Shorts audio tools. Do not assume that recording a cover yourself clears the composition rights.
- Music used outside the in-product Shorts audio library can be subject to standard Content ID claims. Rights holders may monetise, track or block claimed videos. YouTube states that an active claim on a 1–3 minute Short blocks that Short; eligible cover videos may share revenue only when the relevant publisher makes them eligible. Sources: [YouTube — copyright claims](https://support.google.com/youtube/answer/6013276) and [YouTube — monetising eligible cover videos](https://support.google.com/youtube/answer/3301938).
- No claim of guaranteed reach, monetisation or copyright clearance. Check each upload's restrictions and rights status in YouTube Studio.
- Mark synthetic elements honestly where required. Never claim that AI-generated images or sampled audio show a live recording.

## Required automation changes before four-a-day publishing

The current repository is not yet configured for this target. Before enabling public uploads, the implementation needs all of the following:

1. **Four-plan batch model:** replace the single daily-plan assumption with four immutable slot plans. Each must carry a unique production_id, production_date, slot_id, content_pillar, source list, script, asset references and quality report. A failed slot must not overwrite another slot's plan.
2. **Four triggers in Asia/Kolkata:** add a scheduler/orchestrator that starts one independent production for each slot. The current GitHub workflow has no active cron schedule and the current architecture is ChatGPT-triggered; a daily single plan is not a four-slot scheduler.
3. **Duplicate protection by slot:** replace the current production-date-only Upload-Post request_id / external_id / idempotency design with unique per-production/per-slot identifiers. Keep a hard daily ceiling of four confirmed uploads and reconcile uncertain results before retrying.
4. **Publishing provider decision:** reconcile the repository's differing references to Metricool and Upload-Post before wiring the queue. Do not run two schedulers against the same slots.
5. **Real performance intake:** accept a creator-selected recording, preserve its audio/video provenance, create a clip candidate with timecodes, and require creator approval of the edit. This is separate from the explainer renderer.
6. **Release gates:** restore a production-ready illustration path, validate the full rendered video and audio, keep the private Qwen3 voice proof intact, confirm synthetic-media metadata and channel settings, and only then permit public publishing.
7. **Analytics loop:** store a receipt for every slot and measure results per content pillar and time slot. Use those observations to change one variable at a time.

## Verified repository status on 21 November 2026

- The current daily production request has publish_to_youtube set to false.
- The main Autopilot workflow is push/workflow-dispatch driven; no active four-slot cron has been configured.
- The checked-in illustration approval is approved_for_preview, scoped to preview_video_only, with publishing_enabled set to false.
- The main daily plan is a single file, .autopilot/daily-production-plan.json.
- autopilot/engine/upload_post_handoff.py derives its request and idempotency identifiers from production_date, so it must be redesigned before multiple same-day uploads can be safely enqueued.
- autopilot/engine/ENGINE_WORKFLOW.md describes a single 19:00 Asia/Kolkata queue slot, while autopilot/README.md describes Metricool as the primary publisher. Resolve this documentation/implementation drift before enabling the scheduler.
- Private fallback preview retention is configured separately in violin-prince-private-voice; the retention change to six hours does not schedule production or YouTube uploads.

**Bottom line:** this document establishes what Violin Prince should publish. It does not switch on four-a-day production, create public releases, or upload anything to YouTube.
