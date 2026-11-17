# Violin Prince Engine — Canonical Workflow

**Document type:** Source-of-truth workflow and implementation map  
**Version:** 1.0  
**Recorded:** 2026-11-17  
**Repository:** `baidyaprince69-web/violin-prince-website`  
**Location:** `autopilot/engine/ENGINE_WORKFLOW.md`

This document records the complete intended Violin Prince production lifecycle and maps it to the implementation that exists in this repository. Use it as the baseline when explaining the workflow, planning milestones, debugging stages, or implementing upgrades. When code changes, update this document so the architecture and implementation status stay aligned.

## 1. How to read implementation status

- **Implemented — daily route:** Part of the ChatGPT-triggered cloud production path.
- **Implemented — support/recovery path:** Exists in the repository, but is invoked separately or manually.
- **Available / optional:** Implemented capability that is not required for every video.
- **Target / future integration:** Part of the intended complete system, but not yet proven to run as one fully autonomous closed loop.
- **Operator action:** Requires ChatGPT, Metricool, a creator-provided asset, or human review.

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
         GitHub Release handoff assets
                    |
                    v
       ChatGPT operator -> Metricool -> YouTube
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
- Do not introduce a second GitHub Actions or Cloudflare cron scheduler; the GitHub cron was intentionally removed.

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

The plan defines a concise vertical explainer, scene order, scene titles/captions, visual modes, image prompts, visual guidance, narration-to-scene mapping and any character actions.

Current daily creative contract:

- Approximately 24 seconds.
- Vertical 720 × 1280 output.
- Three illustrated scenes as the normal daily format.
- Four-sentence, approximately 40–44-word English narration.
- Production narration is locked until a tested and user-approved clone of the creator's own voice is available.
- No synthetic, preset, generic, or third-party voice fallback is permitted.
- The voiceover module may provide caption helpers, but narration generation must stop while the own-voice gate is locked.
- Word-synchronised karaoke captions.
- The final scene is the musical/violin payoff and should explain how the violin phrase demonstrates the story's idea.

Scene plans must map narration sentences to scenes explicitly and completely. Missing/invalid word timing or incomplete narration blocks rendering rather than being silently guessed.

**Outputs:** validated plan JSON, narration WAV, narration timing data, scene timeline and storyboard preview.

## 7. Audio and music preparation

**Status: Implemented; source is selected by the applicable route and available assets.**

1. Resolve the configured music/performance asset for the run.
2. Prepare the audio file in the private working package.
3. Analyse BPM, beats, downbeats and onsets when available.
4. Generate the solo-violin phrase from the checksum-verified CC0 sample path when no creator recording is supplied and that route is enabled.
5. Use the ambient fallback only when the sample-instrument route is unavailable.
6. Synthesise narration only through the creator's tested and approved own-voice provider. **Current status: blocked by the fail-closed own-voice gate; no substitute narrator is allowed.**
7. Align narration timing with the scene plan.
8. Mix narration, music and any permitted creator-performance audio during final finishing.

A creator-recorded violin take may be used when uploaded and authorised. Where no creator take is deliberately attached to the daily plan, the final scene is a symbolic violin-performance visual. Do not describe synthetic/sample violin audio as a live performance by the creator.

The dashboard's private media library stores uploads in Cloudflare R2. Raw uploads are fetched only into a temporary private Render workspace and must not be exposed in downloadable diagnostic artifacts.

## 8. Scene illustration and visual asset generation

**Status: Implemented in the daily route.**

- Cloudflare Workers AI generates original still scene illustrations; the daily route uses FLUX.1-schnell.
- The normal story uses three scene plates with consistent editorial direction, palette and distinct visual roles.
- Structured visual modes include illustrated macro detail, mechanism cutaway, waveform, melody map, comparison and performance payoff.
- Optional structured charts/process-flow graphics may be rendered only from supplied, verified values. Never invent measurements or imply illustrative geometry is measured data.
- Optional visual-reference guidance can specify visual language, pacing, motion profile, shot type, bounded camera movement and transition. Reference analysis is only used when the reference was actually reviewed.
- The current system animates still illustrations; it must not claim that it generated new AI video footage.

If original scene art generation fails due to permissions, quota or rate limits, stop with a clear diagnostic. Do not silently substitute placeholder art or an unapproved paid service.

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

### 13.1 GitHub release handoff — implemented

After a successful daily production run, the workflow validates the publisher manifest, provenance and final MP4, then creates a public GitHub Release containing:

- `violin-prince-short.mp4`
- `publish-manifest.json`
- `asset-provenance.json`
- Release notes/source references

The release is a handoff package, not proof of YouTube publication.

### 13.2 YouTube scheduling — operator/ChatGPT + Metricool

- ChatGPT reads the successful release and publishing manifest.
- Confirm the configured channel audience setting and use the recorded value unless a valid plan override is supplied.
- Submit the video and metadata through the connected Metricool brand.
- Use automatic publishing only when the connected publisher configuration is enabled and the handoff passes preflight.
- Verify the resulting YouTube post, visibility, title, description and thumbnail after scheduling/publication.

GitHub Actions does not directly upload the daily video to YouTube. Do not describe release creation as YouTube publishing.

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
| `.autopilot/prepare-request.json` | Daily production trigger |
| ChatGPT production plan JSON | Story, narration, scenes and visual direction |
| `.github/workflows/violin-prince-autopilot.yml` | Cloud production stages and release handoff |
| `autopilot/engine/run.py` | Legacy staged Prepare / Visuals / Render workflow |
| `autopilot/engine/run_daily_plan.py` | Validates and executes ChatGPT-authored daily plans |
| `autopilot/engine/creative_direction.py` | Standing channel and creative direction |
| `autopilot/engine/voiceover.py` | Fail-closed own-voice narration gate and caption helpers; provider integration pending |
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

**Status:** Private browser enrollment UI and client-side encryption implemented on the isolated feature branch. Live HTTPS/OAuth/microphone/Drive integration testing is still required. The page is not live until the change is merged and GitHub Pages deploys it.

The new `voice-vault/` page can record through the browser microphone or accept an existing audio recording. It retains the original input, derives a 24 kHz mono PCM16 WAV locally, and requires the exact spoken transcript. It packages the original recording, model-ready WAV, and transcript and encrypts them in the browser using AES-256-GCM with a passphrase-derived key (PBKDF2-SHA256, 600,000 iterations) before sending ciphertext to the owner's Google Drive.

Google OAuth requests only the `drive.file` scope. The short-lived access token remains in JavaScript memory. The page only reuses a folder created by this application and stops if Google reports that folder as shared. It creates no public sharing permissions. The Drive folder remains subject to the owner's Google Drive account and sharing settings.

No plaintext voice recording, normalized WAV, transcript, passphrase, OAuth token, voice embedding, or model profile may be committed to GitHub or uploaded as an Actions artifact/release asset. Recovery decrypts locally in the browser; the passphrase cannot be recovered if lost.

**Enrollment route after deployment:** `https://baidyaprince69-web.github.io/violin-prince-website/voice-vault/`

This is an enrollment UI, not a running voice-cloning system. The production `voiceover.py` now fails closed: narration cannot be generated until Qwen3-TTS and GPT-SoVITS have each been tested with the creator's own voice, hosting/quota/licence and alignment are validated, and the creator approves a production provider. The approved identity must remain the creator's own voice. If neither provider can produce acceptable narration, keep production stopped; never substitute Kokoro, a preset speaker, or another person's voice.


## Addendum — encrypted voice package handoff to private R2 (2026-11-18)

**Implementation status:** dashboard and Worker routes are on the isolated feature branch for review. They are not live until merged and the Cloudflare deployment workflow succeeds.

- The dashboard accepts only the encrypted `.vprvoice` package. It checks the public package header but never decrypts it and never asks for the passphrase.
- `POST /api/voice-packages` requires the existing dashboard bearer token and accepts only a `.vprvoice` file up to 50 MB. The Worker checks the package magic and PBKDF2 iteration header, then stores the ciphertext in the existing private R2 bucket under a random opaque ID. It does not add the package to D1 or produce a public/signed URL.
- `GET /internal/voice-packages/{package_id}` requires the internal job bearer token and streams the encrypted bytes with `Cache-Control: private, no-store`. `DELETE /api/voice-packages/{package_id}` requires the dashboard bearer token.
- A scheduled cleanup removes copied encrypted voice packages from R2 after 30 days. The owner's encrypted Google Drive copy remains the durable backup.
- This is only a ciphertext handoff. No decryption, model inference, voice sample generation, or private GitHub Actions test-runner integration is included yet.
- The public website repository contains implementation code only. It must never contain the encrypted package, raw recording, normalized WAV, transcript, passphrase, OAuth token, voice embedding, or generated voice sample.

The separate private GitHub Actions repository and the approved secret-input process must be established before a real Qwen voice-cloning test. The passphrase remains in the creator's Notepad unless the creator independently chooses to enter it into an approved GitHub Actions secret after reviewing the data-processing arrangement with a parent or guardian. Never use a workflow input or log for the passphrase.
