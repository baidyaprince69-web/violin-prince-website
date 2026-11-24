# Violin Prince Engine — Canonical Workflow

**Document type:** Source-of-truth workflow and implementation map  
**Version:** 1.0  
**Recorded:** 2026-11-17  
**Repository:** `baidyaprince69-web/violin-prince-website`  
**Location:** `autopilot/engine/ENGINE_WORKFLOW.md`

This document records the complete intended Violin Prince production lifecycle and maps it to the implementation that exists in this repository. Use it as the baseline when explaining the workflow, planning milestones, debugging stages, or implementing upgrades. When code changes, update this document so the architecture and implementation status stay aligned.

## Current operating truth — updated 24 November 2026

This section is authoritative and supersedes older commissioning and private-preview descriptions later in this document.

- **Publishing policy:** direct public YouTube publishing only. The creator explicitly authorised `privacy_status=public` and no private preview is required. The scheduled workflow uses `upload_public_short_uploadpost.py` after the public creator-approval and production gates pass.
- **Schedule:** four Asia/Kolkata cron events are declared at 05:30, 11:30, 17:30 and 23:30. The shared non-cancelling queue lock prevents overlapping runs from claiming the same slot.
- **Per-trigger research:** each scheduled event maps to one fixed category and invokes `scheduled_story_builder.py`. It performs live feed discovery, direct-publisher article grouping, freshness/source verification and Copilot-assisted story/narration planning. A research identity is committed before network discovery; the resulting four-slot batch and topic/source ledger are committed before the production selector runs. Exact slot selection prevents one cron from consuming another category.
- **Research boundary:** story and narration text planning is connected to the isolated Copilot CLI adapter and requires `COPILOT_GITHUB_TOKEN`; the model receives only verified publisher text and has no repository, shell, web or MCP tools. The Master Creative Director shot-led visual direction remains manually dispatched and is not yet wired into every scheduled cycle.
- **No-repeat controls:** the queue checks prior date-batches for topics and core claims, including blocked plans; the public uploader checks YouTube title history, date/slot attempt records and exact MP4 SHA-256 values across all prior attempts and receipts. Uncertain uploads are never blindly retried.
- **Genuine-animation gate:** public release still requires the real animation-production approval, tested Motion/HyperFrames character coverage, verified final MP4 and creator review. Do not fabricate approval, substitute a still-image slideshow, or bypass the gate. The Real Performance category additionally requires a validated creator-recorded violin WAV; it cannot fall back to sampled/generated audio.
- **Daily target:** four distinct completed videos and four independently verified public upload receipts per production day. Cron triggers and ready batch plans alone do not satisfy that target.

## 1. How to read implementation status

- **Implemented — daily route:** Part of the ChatGPT-triggered cloud production path.
- **Implemented — support/recovery path:** Exists in the repository, but is invoked separately or manually.
- **Available / optional:** Implemented capability that is not required for every video.
- **Target / future integration:** Part of the intended complete system, but not yet proven to run as one fully autonomous closed loop.
- **Operator action:** Requires ChatGPT, Upload-Post, a creator-provided asset, or human review.

Do not describe a target capability as operational merely because its architecture is documented or a related test passes.

## 2. Product objective

The engine should turn one production request into a sourced, scripted, illustrated and animated vertical video; validate the actual encoded result; prepare a trustworthy publishing handoff; publish through the authorised channel workflow; measure audience response; and use the findings to improve future production.

The system has two connected but distinct loops:

1. **Video production loop:** request → research → plan → assets → animation → render → quality gates → release handoff.
2. **Development and learning loop:** inspect → implement → test → review real output → merge → update the workflow; after publication, collect analytics and use them to inform later plans.

The complete creative/production architecture is broader than the currently automated daily path. In particular, automated character separation and rig validation are a separate support workflow; the daily renderer consumes validated separated character assets when they are supplied in the plan package.

## 3. High-level system map

```text
ChatGPT daily operator / explicit production request
                    |
                    v
       .autopilot production plan + request
                    |
                    v
          GitHub Actions cloud runner
                    |
                    v
       Research, evidence and editorial gates
                    |
                    v
       Script, narration and scene direction
                    |
                    v
     Soundtrack + scene illustration generation
                    |
                    v
       Character asset staging and validation
          |                         |
          |                 Optional separate path
          |                 master artwork -> auto-rig
          |                 -> rig proof -> visual review
          v
       Motion + HyperFrames 2D animation
                    |
                    v
       FFmpeg finishing, captions and encoding
                    |
                    v
         Media QA + provenance + manifest
                    |
                    v
        Verified PRIVATE YouTube preview
                    |
                    v
       Creator reviews at night / weekly
                    |
                    v
    Separate explicit public-publishing approval
                    |
                    v
      Future public schedule (disabled in commissioning)
                    |
                    v
      YouTube analytics and performance review
                    |
                    +------> next production plan
```

## 4. Production triggers and orchestration

### 4.1 Daily trigger — implemented

- ChatGPT is the daily scheduler and production operator.
- ChatGPT prepares the source-checked JSON production plan.
- The plan is saved on `main` and `.autopilot/prepare-request.json` is updated.
- A push affecting that request file triggers `.github/workflows/violin-prince-autopilot.yml`.
- Do not introduce an additional scheduler; ChatGPT is the operator and its request-file push is the only automatic trigger.

### 4.2 Manual/recovery trigger — implemented

The same GitHub Actions workflow exposes `workflow_dispatch` with four stage choices:

- `full`: legacy Prepare → Visuals → Render sequence.
- `prepare`: research, story, narration and soundtrack preparation.
- `visuals`: generate scene art and storyboard using an earlier prepared package.
- `render`: render an earlier saved package without repeating AI generation.

Visuals and Render recovery require the earlier GitHub Actions run ID. Preserve successful run IDs while their artifacts are needed. Artifacts are retained for 14 days.

### 4.3 Production job record

Each run should retain, as applicable, its run ID, source plan, stage, topic, title, narration, scene definitions, source evidence, visual references, asset references, quality reports, final video, publishing manifest and provenance record.

## 5. Research, intelligence and editorial selection

**Status: Implemented in Prepare and the ChatGPT daily-plan validator.**

The research sequence is evidence-first:

1. Discover candidate publisher articles.
2. Resolve discovery/aggregator links to original publisher pages.
3. Fetch readable publisher article content and compare the discovery headline with the publisher headline.
4. Group articles only when they share a distinctive subject found in their article bodies.
5. Require at least two independent publisher families for a supported story.
6. Prefer sources published within 50 hours; allow verified articles up to seven days old. Reject unknown, future-dated or older source records.
7. Lock narration evidence to the selected source group.
8. Verify exact evidence quotes, publication dates, timeline claims, story coherence, channel fit and narration completeness.
9. Stop rather than force a story when the evidence or editorial gates fail.

Approved channel territory: violin physics, instrument design, sound and perception, melody and composition, song anatomy, music production, music technology, and violin-cover breakdowns. Individual musician biographies, career profiles, competition-result stories and celebrity profiles are not accepted as the main subject under the current editorial direction.

The ChatGPT daily route validates the supplied plan's claims, evidence and story coherence before production. The legacy Prepare route performs the full discovery and story-selection sequence.

**Outputs:** source/research records, validated story, narration script, scene plan, review notes and quality-control record.

## 6. Script, narration and storyboard

**Status: Implemented.**

The plan defines a concise vertical explainer, scene order, scene titles/captions, visual modes, image prompts, visual guidance, narration-to-scene mapping and any character actions. The production entry points now enforce the own-voice gate before research, soundtrack preparation, scene illustration, or rendering.

Current daily creative contract:

- Approximately 24 seconds.
- Vertical 720 × 1280 output.
- Three illustrated scenes as the normal daily format.
- Exactly four sentences and exactly 35 spoken English words, with a natural private Qwen3 delivery accepted from 20–24 seconds.
- Production narration is approved through the private Qwen3 worker only; the gate requires the checked-in voice-approval record.
- The private worker handoff validates the exact transcript, all 35 word timings, the 20–24-second natural duration, metadata and WAV SHA-256 checksum. A context-assisted Whisper retry may resolve a first-pass recognition error, but exact transcript matching remains mandatory.
- No preset, generic, third-party or fallback voice is permitted; missing credentials or invalid output stop production.
- Word-synchronised karaoke captions.
- The final scene is the musical/violin payoff and should explain how the violin phrase demonstrates the story's idea.

Scene plans must map narration sentences to scenes explicitly and completely. Missing/invalid word timing or incomplete narration blocks rendering rather than being silently guessed.

**Outputs after own-voice approval:** validated plan JSON, private-Qwen3 narration WAV and verified word-timing data, scene timeline and storyboard preview. **Current state:** narration is approved through private Qwen3, and the tested local illustration style has creator approval for public YouTube use. However, PR #118 places the scheduled route in private-preview commissioning: ready slots upload only as private previews after source, narration, soundtrack, media-quality, channel-identity and duplicate checks pass. The creator reviews the accumulated previews before a separate future public-schedule activation.

## 7. Audio and music preparation

**Status: Implemented; source is selected by the applicable route and available assets.**

1. Resolve the configured music/performance asset for the run.
2. Prepare the audio file in the private working package.
3. Analyse BPM, beats, downbeats and onsets when available.
4. Generate the solo-violin phrase from the checksum-verified CC0 sample path when no creator recording is supplied and that route is enabled.
5. Use the ambient fallback only when the sample-instrument route is unavailable.
6. Synthesise narration only through the approved private Qwen3 worker. **Current status: approved, with exact transcript, word-timing and audio-checksum validation; no substitute narrator is allowed.**
7. Align narration timing with the scene plan.
8. Mix narration, music and any permitted creator-performance audio during final finishing.

A creator-recorded violin take may be used when uploaded and authorised. Where no creator take is deliberately attached to the daily plan, the final scene is a symbolic violin-performance visual. Do not describe synthetic/sample violin audio as a live performance by the creator.

The former external media dashboard and remote media library have been removed. The current workflow does not upload or fetch creator media from an external storage service; a creator performance asset must be supplied through a future approved private input route.

## 8. Scene illustration and visual asset generation

**Status: Local deterministic vector illustrator tested and creator-approved for public YouTube artwork; scheduled commissioning currently uploads its renders as private previews.**

- `autopilot/engine/local_vector_illustrator.py` renders six fixed scene modes locally with Pillow; it makes no network calls, needs no API key and creates 1024 × 1792 JPEG plates.
- The renderer is gated by `autopilot/engine/illustration-approval.json`, which records the successful six-mode test and the creator's explicit `public_youtube` approval for the tested deterministic illustration style.
- The generated plates provide a consistent navy, teal, ivory and antique-gold editorial style. They are vector-style explanatory illustrations, not photorealistic AI artwork or story-specific factual diagrams.
- The normal story uses three scene plates with consistent editorial direction, palette and distinct visual roles.
- Structured visual modes include illustrated macro detail, mechanism cutaway, waveform, melody map, comparison and performance payoff.
- Optional structured charts/process-flow graphics may be rendered only from supplied, verified values. Never invent measurements or imply illustrative geometry is measured data.
- Optional visual-reference guidance can specify visual language, pacing, motion profile, shot type, bounded camera movement and transition. Reference analysis is only used when the reference was actually reviewed.
- The current system animates still illustrations; it must not claim that it generated new AI video footage.

The local renderer is deterministic and contains fixed scene compositions. It must not invent source-specific measurements, dates or physical claims. The creator must inspect the complete rendered preview before the visuals are used in any published video. Do not silently fall back to a remote image service or a paid provider.

**Outputs:** validated scene image files, storyboard preview and scene media-verification report.

## 9. Character generation, separation and articulated rig

This is a dedicated subsystem with its own acceptance gates. It is connected to daily rendering through the character asset contract, but the isolated auto-rig proof is not the same thing as a fully automatic daily character-generation step.

### 9.1 Character artwork and layer contract

A production-ready character package may contain:

- Torso, head and face.
- Left/right upper arms.
- Left/right forearms.
- Left/right hands.
- Required legs/feet where the selected character design uses them.
- Normalised neck, shoulder, elbow and wrist joint anchors.
- Layer positions, sizes, pivots and z-order.
- Neutral and alternate expression artwork.
- Pose/gesture artwork where large pose changes are needed.

Missing required parts must fail validation. Do not replace missing body parts with generic geometric shapes or misleading placeholders.

### 9.2 Automatic separation — implemented as a separate candidate-generation workflow

The optional auto-rig workflow accepts a master character image and reference directory, then prepares candidate transparent parts. The current parser path uses CPU ONNX Runtime with SCHP/Pascal Person Part and ATR parsing checkpoints. The tool creates segmentation masks/layers, estimates joint anchors, prepares face/expression and pose assets when references are supplied, and writes a separation preview and report.

The separation output is a **candidate**, not automatically approved artwork. Stylised illustrations may produce imperfect segmentation; hands/fingers, hairline, face alignment, shoulder overlaps and hidden areas require inspection. Optional LaMa reconstruction can be used for larger hidden torso regions when enabled. If reconstruction or quality checks fail, stop for correction rather than fabricate missing details.

Expected bundle outputs include transparent layer PNGs, joint anchors, `character.json`, `separation-report.json` and `separation-preview.png`. Exact contents depend on the source artwork and supplied references.

### 9.3 Rig construction and actual rig test — implemented as an isolated proof workflow

The Character Auto-Rig Test workflow:

1. Checks out the repository and installs Python/CPU parsing dependencies.
2. Runs raster-space layer/joint/occlusion diagnostics and offline character contract tests.
3. Separates the supplied master character and writes the transparent candidate bundle.
4. Builds the isolated rig-preview project and the daily-pipeline integration test project.
5. Installs Node.js 22 and the Motion + HyperFrames dependencies.
6. Runs animation, character-layout and articulated-rig regression tests.
7. Builds and lints the isolated composition.
8. Renders an actual rig-generated preview MP4.
9. Builds, lints and renders a second portrait integration proof using the daily composition path.
10. Saves the candidate rig bundle to the configured character-assets location only when the run succeeds, the source branch has not advanced, the separation report is candidate-ready, the character spec validates and referenced assets exist.
11. Uploads test evidence as a GitHub Actions artifact.

### 9.4 Required actual rig validation

The rig must be assessed using its own layers and transforms, not an AI-generated animation demonstration. Validate:

- Head rotation and neck alignment.
- Torso movement.
- Upper-arm, elbow and forearm articulation.
- Wrist and hand alignment.
- Coordinated left/right arm movement.
- Pose changes and open-palms / explaining gestures.
- Blink and alternate face expressions.
- No duplicate faces, detached parts, bad seams, layer-order defects or unexplained jumps.

A successful preview render proves that a candidate composition can be rendered; it does not by itself prove perfect segmentation or production readiness. Review the actual MP4 and frame/contact-sheet evidence. The known areas requiring especially careful visual review include blink expression, two-arm gestures and open-palms gestures.

### 9.5 Daily integration

The daily plan's character asset factory validates and stages supplied separated character artwork. The daily renderer checks character visuals and includes the character layers, expressions and pose assets in the Motion + HyperFrames project. A complete automatic conversion from any arbitrary single portrait into approved production-ready character layers should not be claimed as part of every daily run; the auto-rig candidate-generation and review process remains a separate gate.

## 10. Motion, scene composition and animation

**Status: Implemented in the ChatGPT daily route using Motion + HyperFrames; legacy Pillow renderer remains available for manual recovery.**

1. Build a project manifest containing canvas, frame rate, duration, scenes and staged assets.
2. Build a seekable HTML scene composition.
3. Use Motion for JavaScript to generate deterministic spring/keyframe motion for entrances, gestures, expressions, transitions and visual overlays.
4. Keep scene animation seekable and reproducible at an exact frame time.
5. Map each scene to its assigned narration sentences and timing.
6. Composite background illustration, diagrams, character layers, foreground graphics and kinetic typography in their intended z-order.
7. Apply scene-specific visual grammar and transitions.
8. Lint the HyperFrames composition.
9. Capture each scene at a fixed frame rate and assemble the continuous sequence.

Motion + HyperFrames is the current daily renderer. The separate legacy manual recovery route retains Pillow frame-by-frame graphics and FFmpeg finishing. Do not conflate those two rendering implementations.

## 11. Rendering and finishing

**Status: Implemented.**

- Render independent scene clips using HyperFrames.
- Use scene checkpoints/fingerprints to reuse valid renders when safe.
- Verify each scene clip's file integrity, H.264 codec, dimensions and frame rate.
- Join scene clips using the planned transitions.
- Mix narration and music/performance audio.
- Burn word-timed captions.
- Encode the final vertical MP4 using FFmpeg.
- Generate a visual contact sheet from the encoded MP4.
- Preserve scene, audio, timing and rendering diagnostics.

Current daily production target: 720 × 1280, approximately 25 fps, approximately 24 seconds, H.264 video with a valid audio stream.

**Primary output:** `work/output/violin-prince-short.mp4`.

## 12. Quality control and fail-closed gates

A successful process exit alone is not enough. Apply these gates before release:

### Editorial and factual
- At least two independent, readable, article-specific sources.
- Source dates and freshness verified.
- Exact narration evidence quotes verified.
- Story coherence and channel fit pass.
- No unsupported claims.
- Narration is complete and matches the approved script.
- Scene-to-narration mapping is complete.

### Asset and visual
- Every scene image exists and passes independent image checks.
- Character package and every referenced image exist.
- Character layers, joints, expressions and pose assets validate.
- Scene media timing matches the narration contract.
- Contact sheet is generated from the encoded video and visually reviewed where required.
- Typography, gestures, visual continuity and scene transitions are acceptable.

### Media and technical
- Final MP4 exists and is non-empty.
- H.264 video stream exists.
- Dimensions, frame rate and duration match the output contract.
- Valid audio stream exists.
- Audio/video sync and word-timed captions are checked.
- FFprobe/media verification passes.

### Publishing handoff
- Title, description, tags and privacy metadata pass publisher preflight.
- Source and asset provenance files exist.
- Final video hash matches the provenance record.
- Synthetic narration/imagery and soundtrack provenance are identified honestly.
- Any unresolved rights, source, audience-setting or metadata blocker stops release.

## 13. Release handoff and YouTube publishing

### 13.1 Scheduled private YouTube previews — active on `main` after PR #118

- The four cron slots on `main` remain at 00:00, 06:00, 12:00 and 18:00 UTC (05:30, 11:30, 17:30 and 23:30 Asia/Kolkata). Each ready slot uses its own date/slot workspace and proceeds independently.
- The batch path in `run_daily_plan.py` forces `publish_metadata.privacy_status=private` before publisher metadata validation and writes a manifest whose `youtube_privacy` is `private`. The public-only plan metadata is not allowed to override this setting.
- After the existing renderer completes and the manifest/provenance/MP4 pass validation, the workflow invokes `autopilot/engine/upload_private_preview.py`.
- The private uploader reuses `publisher.py`'s existing OAuth/resumable YouTube adapter and the read-only uploads-playlist audit. It requires `YOUTUBE_PRIVACY_STATUS=private`, the configured Violin Prince channel ID, explicit private visibility in both plan and manifest, two independent publisher sources, the exact 35-word/four-sentence narration evidence, accepted soundtrack and illustration provenance, and a matching final-video SHA-256/MP4 probe.
- An exact-title scan includes private uploads. Before calling YouTube, the uploader commits a slot/run-specific attempt marker to `.autopilot/private-preview-attempts/`; after YouTube confirms `privacyStatus=private`, it commits a receipt to `.autopilot/private-preview-receipts/`. An uncertain response or visibility mismatch is recorded as a no-retry state.
- The workflow never invokes `publish_daily_short.py` for scheduled slots. Legacy requests with `publish_to_youtube=true` are rejected while preview-only commissioning is active. The standalone public publisher remains separate and does not form part of the scheduled route.
- No public GitHub Release asset or Upload-Post queue entry is created by this private-preview flow. Private YouTube video IDs and URLs are not written to the public repository or Actions summary. Review previews in YouTube Studio → Content → Private, matching each title and production date.
- The creator can inspect the accumulated previews together at night or during a weekly review; there is no per-video manual approval step in the scheduled production loop.

### 13.2 Public publishing — separately authorised future stage

Public publishing is intentionally disabled during commissioning. The scheduled private-preview path must first demonstrate four complete previews, pass visual/audio review, and verify the private uploader and publisher route. A separate explicit authorisation is required before any future change enables scheduled public visibility. Do not change approval records or secrets as part of private-preview commissioning.

## 14. Analytics and feedback loop

**Status: Partial / optional support implemented; fully autonomous performance-driven optimisation is a target.**

The repository contains an optional read-only YouTube Analytics collector. When OAuth credentials and the internal endpoint are configured, it can collect channel-level metrics for the previous seven complete days, including views, watch time, average view duration, subscribers gained, likes, comments and shares, then store the report through the authenticated internal endpoint. Missing credentials or an unavailable analytics service should skip analytics without failing a production run.

For a true learning loop:

1. Retrieve video-specific YouTube performance, including retention where available, impressions and CTR.
2. Compare the result with relevant previous videos and the intended audience.
3. Identify the strongest supported improvement (hook, pacing, scene clarity, captions, thumbnail/title or topic).
4. Record the finding with the video/run ID and evidence.
5. Feed the specific improvement into a later ChatGPT-authored production plan.
6. Do not claim that the engine autonomously changes its strategy unless that automated decision and persistence path is implemented and tested.

## 15. Failure recovery

- **Research/story failure:** repair or rerun Prepare; do not force unsupported content.
- **Visual generation failure:** rerun Visuals using the previous run ID and visual feedback; reuse valid images where safe.
- **Render failure:** rerun Render from the successful saved package; avoid repeating research or paid/provider calls.
- **Character separation/rig failure:** inspect the separation report and actual preview; correct the source/reference artwork or segmentation, then rerun the isolated rig proof. Do not pass a visually defective pose/expression into the daily pipeline.
- **Publisher preflight failure:** fix the exact metadata/provenance blocker and regenerate the handoff; do not bypass the gate.
- **Temporary network issue:** use only the bounded retry already supported by the relevant stage.
- **Quota, permission or rate-limit failure:** stop with a clear diagnostic. No placeholder output or unapproved paid fallback.

## 16. Development workflow for engine changes

Every engine upgrade follows this lifecycle:

1. Define the precise requirement and acceptance criteria.
2. Inspect current implementation, tests, branches, workflow files and previous decisions before changing code.
3. Identify the smallest affected subsystem and regression surface.
4. Implement on the intended feature branch.
5. Run focused unit/contract tests.
6. Run integration tests and relevant GitHub Actions workflows.
7. Generate real artifacts where the change affects output (MP4, contact sheet, manifests or rig bundle).
8. Inspect visual outputs, not just green checks.
9. Fix defects and rerun the relevant checks.
10. Review the diff and confirm no unrelated changes or secrets are included.
11. Merge only when required checks and acceptance criteria pass.
12. Synchronise local `main` and verify the merged commit.
13. Update this workflow document when the actual system or status changes.

For rig/character changes, the actual rig preview and visual review are mandatory evidence in addition to automated tests. AI-generated reference previews are not substitutes for the actual rig.

## 17. Canonical component map

| Component | Responsibility |
|---|---|
| `.autopilot/daily-batches/YYYY-MM-DD.json` | ChatGPT-authored four-slot daily production batch |\n| `.autopilot/prepare-request.json` | Legacy single-plan push request; public upload requests are rejected during commissioning |
| ChatGPT production plan JSON | Story, narration, scenes and visual direction |
| `.github/workflows/violin-prince-autopilot.yml` | Four-slot schedule, readiness gates, cloud production and private YouTube preview upload |
| `autopilot/engine/daily_readiness.py` | Cheap scheduled readiness gate; prevents stale plans and closed providers from launching production |
| `autopilot/engine/upload_private_preview.py` | Verifies the final bundle, duplicate status and channel, then uploads and receipts a private YouTube preview |
| `autopilot/engine/run.py` | Legacy staged Prepare / Visuals / Render workflow |
| `autopilot/engine/run_daily_plan.py` | Validates and executes ChatGPT-authored daily plans |
| `autopilot/engine/creative_direction.py` | Standing channel and creative direction |
| `autopilot/engine/voiceover.py` | Private Qwen3 own-voice narration gate, transcript/timing/checksum validation and caption helpers |
| `autopilot/engine/violin_sampler.py` | CC0 sampled violin phrase generation |
| `autopilot/engine/audio_analysis.py` | Beat, onset and timing analysis |
| `autopilot/engine/illustration_asset_factory.py` | Character asset staging and validation |
| `autopilot/engine/character_autorig.py` | Candidate character separation and auto-rig preparation |
| `autopilot/engine/character_rig.py` | Character specification and rig contract |
| `autopilot/engine/character_rig_test.py` | Isolated rig preview project |
| `autopilot/engine/character_visual_validation.py` | Visual/raster validation of character layers and joints |
| `autopilot/engine/animation2d/` | Motion + HyperFrames 2D composition, contract and rig tests |
| `autopilot/engine/scene_timeline.py` | Stable scene identity and narration mapping/timing |
| `autopilot/engine/hyperframes_pipeline.py` | Scene rendering, transitions, FFmpeg finishing and media checks |
| `autopilot/engine/media_verification.py` | Image, scene and final-media verification |
| `autopilot/engine/local_vector_illustrator.py` | Deterministic no-network 2D scene plates for the approved preview-only provider |
| `autopilot/engine/publish_handoff.py` | Metadata preflight, manifest and provenance generation |
| `autopilot/engine/analytics.py` | Optional read-only YouTube Analytics collection |
| `.github/workflows/character-rig-test.yml` | Separate actual character auto-rig and integration proof |
| `.github/workflows/autopilot-checks.yml` | Code, test and workflow validation |

## 18. Working rules for future conversations

When asked for the workflow or an implementation based on it:

1. Read this file first.
2. Check the current branch, current workflow files and relevant implementation before asserting present status.
3. Combine this canonical architecture with the latest code and any newer user-approved decisions.
4. Preserve the distinction between daily production, legacy manual recovery, isolated rig validation, publishing handoff and analytics.
5. State what is implemented, optional, operator-controlled, blocked or planned.
6. For implementation requests, follow the development workflow in Section 16 and update this document after material architecture changes.

This file is the canonical workflow baseline; newer verified code and explicitly approved user decisions supersede outdated implementation-status statements, and should be reflected here in a new revision.


---

## Addendum — private own-voice enrollment (2026-11-18)

**Status:** Private browser enrollment UI and client-side AES-GCM encryption are merged and deployed on GitHub Pages. The user confirmed that an encrypted `.vprvoice` package was saved to their private Google Drive and that the Drive privacy check passed. Qwen voice cloning has not yet used this package.

The new `voice-vault/` page can record through the browser microphone or accept an existing audio recording. It retains the original input, derives a 24 kHz mono PCM16 WAV locally, and requires the exact spoken transcript. It packages the original recording, model-ready WAV, and transcript and encrypts them in the browser using AES-256-GCM with a passphrase-derived key (PBKDF2-SHA256, 600,000 iterations) before sending ciphertext to the owner's Google Drive.

Google OAuth requests only the `drive.file` scope. The short-lived access token remains in JavaScript memory. The page only reuses a folder created by this application and stops if Google reports that folder as shared. It creates no public sharing permissions. The Drive folder remains subject to the owner's Google Drive account and sharing settings.

No plaintext voice recording, normalized WAV, transcript, passphrase, OAuth token, voice embedding, or model profile may be committed to GitHub or uploaded as an Actions artifact/release asset. Recovery decrypts locally in the browser; the passphrase cannot be recovered if lost.

**Deployed enrollment route:** `https://baidyaprince69-web.github.io/violin-prince-website/voice-vault/`

The Voice Vault is an enrollment and private-storage boundary, not a public voice service. Production narration uses only the approved private Qwen3 worker. The public repository stores approval/test metadata only; the private worker retains voice-reference processing and performs exact transcript, alignment and audio-integrity checks. Missing credentials, failed checks or unavailable private service stop narration. Never substitute Kokoro, a preset speaker, or another person's voice.

## Addendum — private own-voice test boundary (2026-11-18)

- The Voice Vault is merged and deployed; the owner confirmed that the encrypted `.vprvoice` package was saved to private Google Drive.
- The public Qwen3-TTS preflight tested package/API compatibility and loaded the 0.6B Base model on CPU. It did not read the user's recording or generate audio.
- The actual Qwen voice test is a separate, manually triggered workflow template under `.github/voice-tests/private-runner/`. It must be copied into a dedicated private repository before any personal voice data is processed.
- The private test repository holds the encrypted package. The passphrase is an Actions secret; decrypted reference audio and transcript exist only in the temporary runner workspace. The generated sample is a one-day artifact in the private repository. The public repository and its Actions artifacts never receive personal voice material.
- Cloudflare Worker, Workers AI, R2, D1 and deployment-workflow integrations have been removed from the Autopilot repository in this change. The main GitHub Actions workflow no longer reads Cloudflare or Worker credentials.
- Automated text planning remains disabled until an approved text provider is selected. The local vector illustrator is approved only for a one-video preview; it does not call Cloudflare or any remote image provider.
- The public Autopilot workflow currently exposes only the complete one-shot preview path. Stage-by-stage public artifacts and downloads are disabled because the package can contain narration text and private audio.

Production narration is approved through private Qwen3 after the creator-authorized sample and end-to-end handoff passed. The private worker run, public bridge run and cleanup run are recorded in `voice-approval.json`. The local vector renderer passed six general modes plus three Audient studio-story scenes (run `44524124774`) and has creator-approved public-artwork scope in `illustration-approval.json`; PR #118 independently forces all scheduled commissioning uploads to private visibility.

## Addendum — private video preview delivery (2026-11-19)

- The public renderer must not upload a voice-bearing MP4, narration WAV, narration transcript or stage diagnostic package as a public GitHub Actions artifact or public release.
- For the one-video preview, the ephemeral public runner creates a temporary **draft release in the private** `violin-prince-private-voice` repository containing the final MP4 only, then pushes a small temporary marker branch with the source run ID, file size and SHA-256.
- The private workflow `.github/workflows/private-video-preview-intake.yml` downloads that draft asset inside the private repository, verifies its exact size and SHA-256, stores the MP4 as a one-day private Actions artifact and deletes the temporary release/tag and transfer branch after a successful upload.
- The public workflow offers only the complete `full` stage while private intermediate-stage handoff is unavailable. It has no public video or diagnostic-artifact upload step. `PUBLISH_ENABLED` remains `false`; there is no public GitHub release, Upload-Post queue submission or YouTube upload in this preview path.
- The private artifact is for creator inspection of the completed render. It is not publication approval; the full video must be reviewed before any later publishing decision.


## Addendum — Metricool quota fallback to the official YouTube API (2026-11-20)

**Status:** Implemented in the feature branch `feat/publisher-failover-chain-20261120`; not active on `main` until reviewed and merged.

The production workflow remains unchanged: it performs the video production gates, creates the verified public GitHub Release and leaves `PUBLISH_ENABLED=false`. ChatGPT remains the only daily scheduler and uses the connected Metricool brand as the primary YouTube publisher.

If and only if Metricool confirms that its monthly post limit has been reached, ChatGPT writes `.autopilot/publisher-fallback-request.json` to `main`. The push triggers the separate `.github/workflows/publisher-fallback.yml` workflow. That workflow:

1. Downloads the exact release identified by the request's numeric production run ID.
2. Revalidates `publish-manifest.json`, `asset-provenance.json`, release URL, public audience setting, synthetic-media declaration, duration/format contract, MP4 size and SHA-256.
3. Writes `publisher-attempt.json` to the GitHub Release **before** calling YouTube. Existing attempt or receipt records block a new workflow attempt, including retries with a different GitHub Actions attempt number.
4. Calls the already-existing `youtube_upload()` function in `engine/publisher.py`. This refreshes the saved Google OAuth refresh token and uses YouTube's resumable video-upload endpoint. The separate fallback workflow sets public privacy, while the production job itself remains publishing-disabled.
5. Saves `publisher-receipt.json` to the same release with the returned YouTube video ID and URL. If the upload outcome is uncertain, the receipt records `outcome_unknown` and automatic retry is blocked to prevent accidental duplicate uploads.

The request schema is illustrated by `.autopilot/publisher-fallback-request.example.json`. The live request must use `mode=metricool_quota_fallback`, `reason=metricool_monthly_limit_reached`, the exact release tag and a unique request ID. Temporary Metricool outages, unknown post state or an unverified quota do **not** trigger fallback. If Metricool has already queued a post, the ChatGPT operator must verify it rather than creating another one.

The production workflow's trigger and scheduler are not changed: there is no new cron. The fallback workflow is push-triggered only by the dedicated request file. It does not call Buffer, Publer, vidIQ publishing, Upload-Post or a second social-media scheduler.

The default YouTube Data API quota documents 100 `videos.insert` calls per day for the upload method; the pipeline's intended one or two uploads daily are within that published default, subject to the project's actual quota and YouTube channel-specific restrictions. This is a quota reference, not a guarantee that an upload will succeed.

**Required secrets:** the fallback workflow reuses `YOUTUBE_CLIENT_ID`, `YOUTUBE_CLIENT_SECRET` and `YOUTUBE_REFRESH_TOKEN` already used by the repository's OAuth publishing adapter. Never commit these values or include them in request files, logs or release receipts.


## Addendum — ChatGPT director plus six-hour slot cron (2026-11-21)

**Status:** Merged to `main` through PR #115. The first date-specific batch for 2026-11-22 is committed.

- `engine/slot_registry.py` validates exactly four same-date plans, canonical slot IDs, unique slots and explicit ready/blocked states; it creates per-date/per-slot workspace paths and receipts.
- `run_daily_plan.py --batch --slot-id --workspace-root` verifies the entire batch SHA-256, materializes one immutable selected plan, verifies plan and narration hashes, and runs with separate `work`, `package`, `images` and `output` directories.
- The final manifest, provenance and receipt record `slot_id`, `production_identity` and the batch SHA-256. The private Voice Vault handoff receives only the selected slot's MP4 and identity.
- Upload-Post request IDs, external IDs and idempotency keys include date and slot. GitHub Actions uses a run-specific concurrency group with `cancel-in-progress: false`.
- The four cron events run at 00:00, 06:00, 12:00 and 18:00 UTC, corresponding to 05:30, 11:30, 17:30 and 23:30 Asia/Kolkata. Each selects one content slot.
- The ChatGPT Global Director automation prepares the next day's batch at approximately 18:00 Asia/Kolkata. It commits only `.autopilot/daily-batches/YYYY-MM-DD.json`, a path that is not a push trigger.
- The first batch `.autopilot/daily-batches/2026-11-22.json` has two ready plans and two blocked plans. The two blocked slots will be skipped; no placeholder content will be generated.

**Publishing gate:** scheduled runs are private previews only. The checked-in trigger still sets `publish_to_youtube: false`, and PR #118 forces `privacy_status=private` regardless of the artwork approval's public-artwork scope. Public releases/YouTube uploads require successful commissioning, actual visual/audio review, one confirmed publisher route and a separate explicit publishing-workflow activation. Never present sampled/symbolic audio as the creator's live violin recording.
## Addendum — scheduled public publishing deferred during commissioning (2026-11-21)

**Status:** The separate direct-public scheduled route is not active on `main`. PR #118 merged the private-preview-only route and supersedes the public-scheduled implementation described in the earlier feature-branch work.

- The four existing cron triggers remain at 05:30, 11:30, 17:30 and 23:30 Asia/Kolkata.
- Each ready scheduled slot runs production and verification, then `autopilot/engine/upload_private_preview.py` with YouTube privacy explicitly set to `private`.
- The scheduled workflow does not invoke `publish_daily_short.py`, does not create a public GitHub Release or Upload-Post queue entry, and does not persist private video IDs or URLs in public receipts or logs.
- Blocked slots and failed production, provenance, media-quality, channel-identity or upload-visibility checks stop that slot's upload.
- Public publishing remains the final operating goal, but enabling scheduled public visibility requires a separate implementation change after the commissioning cycle and nightly review.

---

## Addendum — full-body multi-layer cinematic composition preview (2026-11-25)

**Status:** Implemented in the isolated full-body preview branch; end-to-end GitHub Actions validation is pending.

The full-body performance MP4 is now a supported visual layer in a separate preview-only composition stage. autopilot/engine/cinematic_video_pipeline.py consumes a versioned JSON timeline and supports:

- A full-frame base video, including the current Violin Prince full-body animation.
- Additional independently timed video or still-image layers with position, dimensions, fit mode and opacity.
- Transparent animation clips for motion graphics, plus timed text/caption layers.
- Separate narration/voice, music and sound-effect audio tracks with trim points, start offsets, gain, fades and optional looping.
- Voice compression, music side-chain ducking, SFX mixing and a final limiter.
- FFprobe validation of the final MP4 dimensions, duration, frame rate, H.264 video, AAC audio and audio sample rate.

create_cinematic_composition_preview.py prepares a safe CI fixture using the current full-body preview, a transparent animated accent layer, a synthetic eSpeak NG narration, the generated CC0 sampled-violin guide and a generated whoosh. The public-branch smoke test does **not** use the creator's private voice recording.

**Privacy and publishing boundary:**
- The timeline must state preview_only=true and publish_enabled=false; the compositor rejects any other configuration.
- Any audio source marked private_source=true sets private_media=true and public_artifact_allowed=false in the render report.
- The public Actions preview has a fail-closed artifact check. A private-voice render must not be copied into a public repository artifact.
- The compositor has no uploader, release, scheduler or publisher integration. PUBLISH_ENABLED=false and AUTOPILOT_ENABLED=false remain set in the preview workflow.

The synthetic narration is only an integration fixture. It proves that a voice track can be positioned and mixed with music/SFX; it is not a test of the creator's actual voice timbre, transcript alignment or final voice approval. Use an approved private voice source only in a private/local rendering path.

**Acceptance for this stage:** the combined 8-second MP4 must contain at least the full-body character layer and a separate animated graphic layer, separate voice/music/SFX tracks, music ducking, and valid H.264/AAC streams. The combined render is sampled by the existing dense pose-range QA. This stage demonstrates video composition; it does not grant visual-quality approval to the underlying character artwork or enable publishing.


### Source-faithful body-connection backplate

The segmented performance rig adds a low-z-index source-motion backplate behind its moving arm and leg sprites. It is built from the preserved character source, limited to the neck/shoulder/arm, hip/pelvis/leg corridors and joint overlaps, and feathered only in alpha. It does not invent replacement clothing pixels or replace the articulated layers. CI verifies that every visible backplate RGB pixel is byte-for-byte identical to the preserved source and that its alpha never exceeds source alpha. The backplate is rendered below the independently animated sprites so it can restore source artwork at disconnected seams.

A passing FFmpeg/HyperFrames render is an engineering result, not visual approval. The rig report's `premium_character_quality_gate.status` remains a separate release gate; a blocked character-art reconstruction status must not be described as production-ready. Cinematic approval also requires a multi-shot sequence with visible camera/scene changes and deliberate stagecraft, not merely adding titles or graphic overlays to one uninterrupted character clip.


### Multi-shot camera edit in the preview compositor

The preview timeline now supports per-layer normalized camera crops, validated framing labels, per-shot colour grading and camera-shot metadata in its render report. The CI cinematic fixture uses a full-body establishing frame, a medium performance frame, a violin/bow/hands close-up, a face/upper-body close-up and a return to the full-body hero frame. The shot layers overlap with alpha fades for dissolves. CI requires all four framing types and at least five declared shots; a title or graphic overlay on one unchanged wide shot is no longer sufficient evidence of a cinematic edit. These shots are a camera edit of the existing character performance, not newly generated source footage.
