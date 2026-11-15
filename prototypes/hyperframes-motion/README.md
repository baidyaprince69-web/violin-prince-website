# Violin Prince — narrated explainer renderer

Motion + HyperFrames is the animation and video-rendering engine for Violin Prince explainer videos. It does not replace research, scriptwriting or narration.

## Intended production

1. Research a specific violin, sound, music or music-production fact and verify it against independent publisher sources.
2. Write the short explanation script and pass the existing editorial, factual and freshness gates.
3. Generate the spoken explanation using Kokoro-82M with the `af_heart` voice and retain the model-native word timestamps.
4. Animate the three scene plan: the question, the explanatory mechanism and the takeaway. Use the approved scene captions, graphic labels, source-backed process steps or measurements; never invent data.
5. Render through Motion + HyperFrames. Kokoro is the primary audio. The repository's CC0 sampled-violin audio is an optional, quiet, side-chain-ducked background bed.
6. Verify narration/video duration, word-timed captions, deterministic seeking, video/audio streams, H.264, 1080 × 1920 and 30 fps.

The current planner is intentionally short-form (approximately 24 seconds of narration). This integration does not yet generate long-form three-minute documentaries.

## Renderer implementation

- Motion JavaScript provides seekable scene transitions, typography, animated infographic nodes, particles and progress.
- The composition receives the approved research-backed scene plan and Kokoro's native word timings from Autopilot.
- HyperFrames captures the full narration timeline and FFmpeg encodes the final MP4.
- The voice is mixed at full level. The optional violin bed is reduced and ducked under speech. Setting `MOTION_HYPERFRAMES_MUSIC_BED_ENABLED=false` removes the bed entirely.
- The renderer refuses to create a Motion output without Kokoro-82M `af_heart` audio and passed word timestamps. Old narration-free music-video packages are rejected.
- The current Motion route is 2D/2.5D animation and infographic graphics. It does not yet provide a realistic 3D violin model.

## Local commands

Requires Node.js 22+ and FFmpeg.

```bash
npm install
npm run prepare:composition -- --audio /path/to/narration-first-explainer-mix.wav --content-json /path/to/content-context.json
npm run prepare:motion
npm run lint
npm run check
npm run verify:seeking
npm run render
npm run verify
```

The workflow exports the final explainer to the GitHub Actions artifact. The prototype's internal temporary filenames retain legacy naming but do not change the production type.

## Scope and safeguards

- Manual Motion production uses the existing researched Prepare pipeline; Kokoro is not skipped.
- The old music-only Prepare entry point fails closed.
- The optional Blender route remains separate; it is not a Motion fallback.
- No Cloudflare media-storage route is used by the Motion renderer.
- YouTube publishing remains disabled during this integration. PR #57 stays draft and unmerged until the narrated output is reviewed.
