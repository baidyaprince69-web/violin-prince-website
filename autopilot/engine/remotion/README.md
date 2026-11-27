# Violin Prince — optional Remotion compositor

This is an isolated, opt-in **post-render compositor**. It is deliberately not imported by
`run_daily_plan.py`, `hyperframes_pipeline.py`, the daily GitHub Actions queue, or any
YouTube publishing module.

## Why it is separate

The current engine already uses Motion + HyperFrames for its animated scene and
character-rendering work, followed by FFmpeg finishing and media QA. Remotion is added
as an independent final-look experiment for optional title and brand overlays on a
copy of an existing MP4.

## Safety and compatibility rules

- The source MP4 is copied into Remotion's temporary public assets. The source file is
  never edited or overwritten.
- Input is checked before rendering: MP4 video and audio streams, portrait 720x1280,
  approximately 25 fps, and a duration between 2 and 180 seconds.
- The compositor preserves source audio and video duration. The title and subtitle are
  rendered directly over the footage. There is no card, panel, box, backing rectangle,
  or filled shape behind the text.
- The Midnight Resonance treatment uses expressive display-serif title typography,
  compact tracked brand typography, a cool-cyan supporting line, an animated gold/cyan
  accent rule, and soundtrack-reactive rhythm bars.
- The rhythm bars and accent glow respond to per-frame RMS loudness from the original
  soundtrack. This is time-domain loudness reactivity, not frequency-band analysis or
  beat detection.
- The output is a **candidate**, not a production-approved video. It is not put into the
  daily publish manifest and it is never sent to YouTube by this package.
- The existing daily queue and upload workflow are intentionally unchanged.

## Local use

Requirements: Node.js 22+, FFmpeg and FFprobe.

```bash
cd autopilot/engine/remotion
npm install --no-audit --no-fund
npm test
npm run render -- --input ../../../work/source.mp4 --output ../../../work/remotion-preview.mp4 --title "A Violin Performance" --subtitle "SOLO VIOLIN"
```

The generated MP4 and its adjacent `.report.json` are separate from the input.

## Review boundary

The motion-graphics behaviour and soundtrack-reactive accent have creator approval.
The no-card typography styling is an iterative visual treatment and remains subject to
creator review. Keep this PR open and draft until the typography and a separate
integration decision are approved. Never route this isolated compositor into the daily
production workflow or publisher as part of a visual-preview change.

## Dependency and licensing note

Remotion and `@remotion/cli` are pinned to the same exact version (`4.0.547`) to avoid
version skew. React and React DOM are pinned to `18.3.1`.

Review Remotion's current license terms before scaling deployment beyond an individual
or team of up to three people.
