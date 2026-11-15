# Violin Prince — Motion + HyperFrames prototype

A self-contained 10-second vertical motion-graphics test. It is isolated from the production Autopilot renderer.

## What this tests

- Motion JavaScript for deterministic, seekable typography, waveforms, particles and parallax.
- HyperFrames for frame-by-frame browser capture and MP4 encoding.
- 1080 × 1920 at 30 fps.
- A cloud-render job on GitHub Actions.
- No Blender, AI video service, external media downloads or publishing credentials.

## Blender is optional

This prototype is a 2D/2.5D composition. It does not install, import, invoke or require Blender.

For the wider Autopilot, `BLENDER_RENDER_ENABLED` is the explicit opt-in for the existing full-frame 3D route. The regular Autopilot workflow is being changed in this draft PR to default that flag to `false`, including on pushes. Set the repository Actions variable `BLENDER_RENDER_ENABLED=true` only when a run specifically requires a real 3D instrument/scene. The dedicated first-production Blender workflow remains separately and intentionally 3D-only.

The 2D route uses HTML/CSS/SVG and Motion in Chromium, then HyperFrames/FFmpeg for video capture and encoding. It still uses cloud CPU resources; the goal is to avoid the much heavier software-rendered Blender 3D path for flat graphics, titles and 2.5D elements. Rendering speed will be measured rather than assumed.

## Render locally

Requires Node.js 22+ and FFmpeg.

`npm install`

`npm run prepare:motion`

`npm run lint`

`npm run check`

`npm run verify:seeking`

`npm run render`

`npm run verify`

The MP4 is written to `output/violin-prince-motion-10s.mp4`.

## Motion is an external module

The HTML import map points to the installed, pinned Motion ESM file under `node_modules`. The composition script stays a small native browser module; the Motion package is not bundled into it or copied into a file that HyperFrames scans. The preparation script reads Motion's own package export map and checks that its local ESM entry exists. No runtime CDN request is needed.

The timeline is paused. HyperFrames controls its registered timeline adapter, and every requested time is applied directly to Motion's timeline. The seek test asks for 5.25 s, then 1.25 s, then both again, and compares decoded RGBA pixels for the repeated requests. This tests random-access order as well as repeatability.

## Safety boundary

This prototype does not connect to YouTube, has no upload step and does not alter production publishing settings. The existing Blender production path and benchmark branch remain separate. The PR stays draft until the video, determinism test and cloud render timing are reviewed.

## Next step

Review the MP4 and contact sheet from the GitHub Actions artifact. Only after visual approval should the Motion/HyperFrames renderer be considered for production integration. Real 3D violin shots remain optional and separate from the 2D/2.5D composition path.
