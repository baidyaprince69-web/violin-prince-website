# Violin Prince — Narrated explainer renderer

Motion + HyperFrames is the default visual renderer for the researched Violin Prince explainer pipeline. It is not an instrumental-only music-video route.

## Intended production flow

1. A ChatGPT-authored production plan selects a specific explainable subject and supplies the researched explanation, scene direction, source URLs and sentence-level evidence.
2. The runner re-fetches the publisher pages and validates source independence, dates, exact sentence evidence, freshness and channel fit.
3. Kokoro-82M generates the spoken explanation with the `af_heart` voice. Its native word-level timestamps are mandatory and are retained for the renderer.
4. Motion + HyperFrames animates the three approved explanation scenes. The composition builds process-flow or measured-value graphics only from supplied plan data, changes scene content at the relevant narration sentence, and highlights the spoken words using Kokoro's timestamps.
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
- Sourced process-flow and measured-value diagrams are built from the story plan. When a story has no suitable numeric graphic, the renderer displays its approved scene caption and supporting detail rather than inventing data.
- Captions follow Kokoro's native word timestamps. Each active word is highlighted with nearby words for readable context.
- The timeline is driven by the narration duration; it does not repeat a fixed ten-second visual loop.
- This renderer is HTML/CSS/SVG and 2D/2.5D motion graphics. It does **not** create a photorealistic 3D violin model. Blender remains a separate optional, explicitly enabled 3D renderer; it is not installed or invoked as an automatic fallback when Motion fails.

## Local development

Requires Node.js 22+, FFmpeg, Python dependencies from `autopilot/engine/requirements.txt`, and locally cached Kokoro model weights.

The test fixture workflow validates the browser composition independently from the full story pipeline. It checks 1080 × 1920 at 30 fps, audio/video duration equality, random-access seeking and deterministic decoded frames.

## Publishing and external services

`PUBLISH_ENABLED=false` is enforced for this production route. The rendered MP4 and diagnostic reports are uploaded only as GitHub Actions artifacts. The Motion route does not upload to the website, create a release, or publish to YouTube.

The optional Blender route continues to use its separately configured licensed model and Frame By Plane workflow. It is selected only when `BLENDER_RENDER_ENABLED=true`; it is never a fallback for a failed Motion render.
