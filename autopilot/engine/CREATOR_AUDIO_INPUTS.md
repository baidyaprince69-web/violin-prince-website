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
not retarget the body motion when an audio file is swapped. The full-body project builder
supports decoded creator WAV analysis and note-event extraction; ambiguous or low-confidence
takes fail closed rather than receiving invented notes.

Creator recordings are referenced in place, marked `private_source=true`, and are never
copied into the generated timeline folder. The render report then states
`private_media=true` and `public_artifact_allowed=false`. Do not upload that render,
its timeline, logs, or source WAV files to public repository artifacts.

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
