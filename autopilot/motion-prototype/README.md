# Violin Prince V3 motion prototype

This directory contains an isolated HTML Canvas + Playwright renderer experiment.
It is not the production renderer.

## What it tests

- Native word-level caption timing from Kokoro's predicted phoneme durations.
- Nine caption treatments: bounce, editorial serif, outline, underline, tilt, typewriter, glow, editorial and impact.
- Multiple font families and phrase-aware word emphasis: technical terms, action words and emotional phrases receive different treatments rather than cycling styles by word index.
- A warm charcoal, antique-gold and copper art direction; the large blue information card has been removed.
- A compact editorial story header with staged infographic reveals: label, headline, detail, connectors, nodes and chart layers enter in sequence.
- Continuous atmosphere layers, floating light particles, orbital rings, directional transition sweeps and stronger scene-specific camera movement.
- A localized alternating bow-path highlight and subtle string vibration in the performance-detail scene, responding to sampled RMS energy from the music bed.
- A second story, "How a Violin Turns Motion into Music", rendered through the same pipeline to check layout and timing consistency.
- Deterministic frame capture followed by FFmpeg H.264 encoding.

## Visual scope

The three main scene illustrations remain still source images. The HTML renderer adds continuous camera motion, animated vector layers, dynamic typography, infographic components and a music-reactive bow/string motif over them. This is a stronger motion-graphics test, not full AI-generated character animation or a claim of anatomically exact hand performance.

## Safety and separation

- The existing Python/Pillow/FFmpeg renderer remains the production path.
- This prototype does not call Cloudflare AI, upload to public video services, or publish.
- It reads an existing prepared package and regenerates narration from the approved script to obtain native word timing.
- It creates both a V2 FFmpeg baseline and V3 HTML preview for the primary story, plus a second-story consistency render.
- The prototype is not promoted to production until visual inspection and regression tests pass.

## Local/cloud command

Install the pinned browser dependency and Chromium, then run:

~~~bash
npm install --prefix autopilot/motion-prototype --no-audit --no-fund
autopilot/motion-prototype/node_modules/.bin/playwright install chromium
python autopilot/engine/motion_prototype.py \
  --package work/package \
  --output work/output/motion-prototype
~~~

The dedicated GitHub Actions workflow performs these setup steps in the cloud. The creator's PC is not needed.

## Output

- ffmpeg-baseline.mp4 — current V2 FFmpeg renderer, using the same regenerated narration and prepared images.
- html-motion-prototype.mp4 — isolated V3 Canvas renderer for the original prepared story.
- second-story/html-motion-prototype.mp4 — second-story consistency preview.
- two-story-test-report.json — combined two-story result and production-separation flags.
- v3-comparison-report.json — dimensions, duration, word timing and renderer metadata for each story.
- qa-frames/ — sampled still frames from each HTML preview.
