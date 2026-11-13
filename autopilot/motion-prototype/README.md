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

The three scene images are generated as still artwork by Cloudflare Workers AI (FLUX.1-schnell). Each generated image is inspected by a separate vision model (Moondream 3.1) against the actual scene brief. A rejected scene receives one targeted regeneration; if it still fails, the visual stage stops before video rendering. The violin macro is now an AI-generated photographic brief, not a Python/Pillow drawing. AI review is a quality gate, not a guarantee: the storyboard and final encoded video still require human visual approval.

The HTML renderer adds camera movement, transitions, animated vector layers, phrase-aware word captions, kinetic typography, infographic components and music-reactive visual details. FFmpeg encodes these into an MP4. This is a video rendered from still images, not text-to-video or image-to-video footage: the violinist, hands and bow are not independently animated as moving footage.

## Safety and separation

- The existing Python/Pillow/FFmpeg renderer remains the production path; the HTML renderer is still isolated for evaluation.
- The fresh-art checkpoint calls FLUX.1-schnell for all three scene images and Moondream 3.1 for visual inspection; it does not call a text-to-video model or publish.
- The isolated rendering step reads saved still images and does not make AI calls.
- AI image prompts are capped at 1,800 characters; transient network/5xx failures receive one bounded retry, while quota and permission failures stop without a paid fallback.
- A rejected scene receives one targeted regeneration using the vision model's feedback. If it still fails, the pipeline rejects the package instead of rendering defective artwork.
- Image reuse requires 720×1280 dimensions, a passing review record and a matching SHA-256 digest. Old images without review evidence are regenerated.
- The violin macro is a photorealistic image-generation brief requiring a complete bridge, four strings, a distinct fingerboard and one correctly constructed bow.
- It reads an existing prepared package and regenerates narration from the approved script to obtain native word timing.
- The V3 workflow automatically selects the newest successful V2 run with both required, unexpired visual and diagnostic artifacts; an explicit source-run override is optional.
- It creates both a V2 FFmpeg baseline and V3 HTML preview for one primary story.
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
- single-story-test-report.json — one-story prototype result and production-separation flags.
- v3-comparison-report.json — dimensions, duration, word timing and renderer metadata for each story.
- final-encoded-qa-frames/ — sampled still frames decoded from the final MP4.
- fresh-visual-test-manifest.json — scene generation models, image-review records and human sign-off status.


## Prompt design

- Image prompts use a five-part structure: subject/action, recurring asset anchor, style/material, lighting/camera, and background/atmosphere.
- The opening image is composed as a readable two-second hook; the second scene is deliberately framed as a controlled photorealistic macro; the final scene resolves by widening back out.
- Performance prompts specify the violin/bow/fingerboard relationship, the focal contact point, and a single dominant action. The prompt avoids forcing both hands into one anatomically impossible macro frame.
- Camera intent is explicit (push-in, lateral follow, pull-back) and matches the Canvas renderer's scene-specific camera arcs.
- Reference techniques are adapted into the original Violin Prince charcoal/walnut/oxblood/gold palette; the pipeline does not imitate another creator's branded look.
- External text-to-video/image-to-video providers are not called by this prototype. The current free-first path still generates still artwork and animates it locally in the cloud renderer; the prompt design is ready for a future optional provider adapter.
