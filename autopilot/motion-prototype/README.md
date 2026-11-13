# Violin Prince V3 motion prototype

This directory contains an isolated HTML Canvas + Playwright renderer experiment.
It is not the production renderer.

## What it tests

- Word-level caption timing from Kokoro's native predicted phoneme durations.
- Five original caption motion treatments: slide, rise, snap, pop and impact.
- Animated source-grounded graphic cards.
- A side-by-side comparison layout that only appears when both comparison sides are explicitly present in a scene.
- Deterministic frame capture followed by FFmpeg H.264 encoding.

## Safety and separation

- The existing Python/Pillow/FFmpeg renderer remains the production path.
- This prototype does not call Cloudflare AI, upload to public video services, or publish.
- It reads an existing prepared package and regenerates narration from the same approved script to obtain native word timing.
- It produces both an FFmpeg baseline and an HTML-rendered MP4 for comparison.
- The prototype is not promoted to production until visual inspection and regression tests pass.

## Local/cloud command

Install the pinned browser dependency and Chromium, then run:

```bash
npm install --prefix autopilot/motion-prototype --no-audit --no-fund
autopilot/motion-prototype/node_modules/.bin/playwright install chromium
python autopilot/engine/motion_prototype.py \
  --package work/package \
  --output work/output/motion-prototype
```

The dedicated GitHub Actions workflow performs these setup steps in the cloud. The creator's PC is not needed.

## Output

- `ffmpeg-baseline.mp4` — current V2 FFmpeg renderer, using the same regenerated narration and prepared images.
- `html-motion-prototype.mp4` — isolated HTML Canvas renderer.
- `v3-comparison-report.json` — dimensions, duration, timing method and renderer metadata.
- `qa-frames/` — sampled still frames from the HTML prototype.
