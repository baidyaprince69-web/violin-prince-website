# Creator audio inputs for the full-body cinematic preview

## Accepted inputs

The cinematic timeline builder accepts a private creator-recorded narration WAV through
`--voice-wav`. It accepts a creator-recorded violin WAV through
`--music-wav ... --music-source creator_recording`.

The voice input is clipped to the eight-second review timeline. Use
`--voice-source-in-seconds` to select the beginning of a longer recording. The creator
violin take is not looped and must cover the complete eight-second preview.

Example, run only in a private workspace:

```bash
python autopilot/engine/create_cinematic_composition_preview.py \
  --character-video /private/render/full-body-violin-performance.mp4 \
  --voice-wav /private/audio/creator-narration.wav \
  --voice-source-in-seconds 0 \
  --music-wav /private/audio/creator-violin-take.wav \
  --music-source creator_recording \
  --output-dir /private/render/cinematic-composition

python autopilot/engine/cinematic_video_pipeline.py \
  --manifest /private/render/cinematic-composition/cinematic-timeline.json \
  --output /private/render/full-body-cinematic.mp4 \
  --report /private/render/full-body-cinematic-report.json
```

The `character-video` must already have been rendered from the same creator violin take
for the performance movement and soundtrack to stay synchronized. The compositor does
not retarget the body motion when an audio file is swapped.

For a creator recording, the full-body project builder decodes the WAV, checks beat-map
confidence, and runs monophonic violin note-event analysis. It refuses the build when the
beat map is low-confidence, fewer than two beats are found, note analysis does not pass,
or fewer than four in-range note events remain. It does not invent replacement pitches.
The resulting note events are mapped only against the current first-position G/D/A/E
fingering model; higher positions are explicitly reported for manual review.

Creator recordings are referenced in place, marked `private_source=true`, and are never
copied into the generated timeline folder. The render report then states
`private_media=true` and `public_artifact_allowed=false`. Do not upload that render,
its timeline, logs, or source WAV files to public repository artifacts.

## Full-body performance test with a creator-approved violin WAV

Run this stage on your own machine or another private workspace. Use an isolated
eight-second excerpt first; the analysis and motion project are built from the same WAV.

```bash
python autopilot/engine/character_autorig.py \
  --source autopilot/engine/assets/characters/violin-prince-performance/master-character-performance.webp \
  --reference-dir autopilot/engine/assets/characters/violin-prince-reference \
  --output /private/rig/full-body-rig-bundle \
  --id violin-prince \
  --allow-expression-fallback

python autopilot/engine/create_full_body_performance_preview.py \
  --bundle /private/rig/full-body-rig-bundle \
  --output /private/render/creator-performance \
  --audio /private/audio/creator-violin-take.wav \
  --duration-seconds 8

PROJECT_ROOT="$(pwd)"
cd "$PROJECT_ROOT/autopilot/engine/animation2d"
npm install --no-audit --no-fund
node build.mjs \
  --project /private/render/creator-performance/project.json \
  --out-dir /private/render/creator-performance/composition
./node_modules/.bin/hyperframes render \
  --project /private/render/creator-performance/composition/index.html \
  --output /private/render/creator-performance/video-only.mp4 \
  --fps 25 --quality standard

ffmpeg -hide_banner -loglevel error -y \
  -i /private/render/creator-performance/video-only.mp4 \
  -i /private/audio/creator-violin-take.wav \
  -map 0:v:0 -map 1:a:0 -t 8 -c:v copy -c:a aac -b:a 192k -shortest \
  /private/render/creator-performance/creator-performance-review.mp4
```

The bow remains attached to the bowing hand. The animated shoulder, elbow and wrist
chain moves the hand and bow together; the prop is never translated independently of
its grip. A source-derived bow-shaft axis is used for QA, which measures bow-tip travel
and verifies grip alignment against the hand at every sampled frame.

Measured MIDI notes map to G/D/A/E strings and first-position fingers. Open strings do
not activate a finger. Notes outside the modeled range are reported as
`manual_review_required`; they are not forced onto a guessed finger. This is not
score-aware bow distribution or a complete multi-position fingering engine.

Only after the character performance is reviewed should the same take be used as the
music layer in the cinematic composition step above. Keep the WAV, the render, the
timeline, and QA logs in the private workspace. The public GitHub Actions preview
continues to use CC0 fixtures only.

## Automated test mode

The public GitHub Actions rig workflow intentionally uses the CC0 violin sample and a
synthetic eSpeak narration **only** as non-publishing test fixtures. The synthetic voice
requires the explicit `--synthetic-voice-for-tests` switch; it is not an implicit fallback
when a creator recording is missing. The workflow must not receive private creator audio.

## Production voice identity

The separate daily production route uses the approved private Qwen3 own-voice bridge.
Its raw reference package and private transfer remain in the private voice repository;
the public render workspace receives only the validated narration output required by that
run. This eight-second rig smoke fixture does not invoke that 35-word production narration
bridge, and passing its workflow does not certify the creator's narration or violin take.
