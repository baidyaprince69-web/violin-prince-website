# Violin Prince — Narrated explainer renderer

Motion + HyperFrames is the mandatory production renderer for Violin Prince narrated explainers. Production is 2D-only: Blender, 3D asset acquisition and 3D rendering are disabled.

## Intended production flow

1. A ChatGPT-authored production plan selects a specific explainable subject and supplies the researched explanation, scene direction, source URLs and sentence-level evidence.
2. The runner re-fetches the publisher pages and validates source independence, dates, exact sentence evidence, freshness and channel fit.
3. Kokoro-82M generates the spoken explanation with the `af_heart` voice. Its native word-level timestamps are mandatory and are retained for the renderer.
4. Motion + HyperFrames animates three approved explanation scenes using original native SVG illustration systems: a layered listening room with an animated listener and sound reflections, a DSP signal-chain illustration with moving signal pulses, and a stylised violin/performer illustration with independently animated bow, strings, notes and waveform accents. Scene changes and captions follow Kokoro's sentence and word timings.
5. FFmpeg mixes Kokoro as the primary audio with an optional CC0 sampled-violin bed at low gain, sidechain-ducked under the narration. Set `MOTION_HYPERFRAMES_MUSIC_BED_ENABLED=false` to omit the violin bed completely.
6. The renderer verifies the MP4 streams, frame size/rate, duration against the narration, audio presence, word timing metadata and seek behaviour. The output is a GitHub Actions artifact; publishing stays disabled.

The manual Motion request consumes `.autopilot/daily-production-plan.json` through:

```bash
python autopilot/engine/run_daily_plan.py --plan .autopilot/daily-production-plan.json
```

That path does not call Cloudflare, Workers AI, R2, FLUX or a remote image service. It uses the existing local Kokoro engine and the ChatGPT-prepared plan. The sampled violin is only an optional background bed; it is never treated as the explanation or the primary audio.

## Renderer capabilities and limits

- 1080 × 1920 vertical output at 30 fps.
- Motion JavaScript provides seekable animation; HyperFrames handles frame capture and FFmpeg encoding.
- Native SVG art is generated from the approved scene type and bounded story data; no stock image, external image API, or fabricated measurement is used. Illustrated signal curves are labelled as conceptual when they are not measured values.
- Captions follow Kokoro's native word timestamps. Each active word is highlighted with nearby words for readable context.
- The timeline is driven by the narration duration; it does not repeat a fixed ten-second visual loop.
- This renderer is HTML/CSS/SVG and layered 2D motion graphics. It intentionally uses illustrated subjects rather than photorealistic 3D models. Blender and 3D model rendering are disabled for production and are not fallback paths.

## Local development

Requires Node.js 22+, FFmpeg, Python dependencies from `autopilot/engine/requirements.txt`, and locally cached Kokoro model weights.

The test fixture workflow validates the browser composition independently from the full story pipeline. It checks 1080 × 1920 at 30 fps, audio/video duration equality, random-access seeking and deterministic decoded frames.

## Publishing and external services

`PUBLISH_ENABLED=false` is enforced for this production route. The rendered MP4 and diagnostic reports are uploaded only as GitHub Actions artifacts. The Motion route does not upload to the website, create a release, or publish to YouTube.

`BLENDER_RENDER_ENABLED=false` and `MOTION_HYPERFRAMES_RENDER_ENABLED=true` are enforced by the production workflow. The daily-plan runner also rejects Blender or legacy still-image renderer selection.
