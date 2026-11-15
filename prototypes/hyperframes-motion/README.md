# Violin Prince — Motion + HyperFrames prototype

A self-contained 10-second vertical motion-graphics test. It is isolated from the production Autopilot renderer.

## What this tests

- Motion JavaScript for deterministic, seekable typography, waveforms, particles and parallax.
- HyperFrames for frame-by-frame browser capture and MP4 encoding.
- 1080 × 1920 at 30 fps.
- A single cloud-render job on GitHub Actions.
- No Blender, AI video service, external media downloads or publishing credentials.

## Render locally

Requires Node.js 22+ and FFmpeg.

`npm install`

`npm run build`

`npx hyperframes lint`

`npx hyperframes check`

`npm run render`

`npm run verify`

The MP4 is written to `output/violin-prince-motion-10s.mp4`.

## Motion seek adapter

HyperFrames owns the render clock and requests exact timeline positions. Motion's paused timeline is exposed through a small adapter with the `pause()`, `time()`, `totalTime()` and `duration()` methods expected by the composition timeline registry.

The adapter does not play animations in wall-clock time. A render request for time `t` sets Motion's timeline time to `t`, so repeated and out-of-order frame seeks can be checked by HyperFrames.

## Safety boundary

This prototype does not connect to YouTube, has no upload step and does not alter production workflow settings. The existing Blender production path and benchmark branch remain untouched.

## Next step

Review the MP4 and contact sheet from the GitHub Actions artifact. Only after visual approval should the Motion/HyperFrames renderer be considered for integration into the wider pipeline. The real 3D violin remains a separate optional visual layer and is not included in this 2D/2.5D proof of concept.
