# Violin Prince — Motion-first prototype

This isolated prototype tests a 10-second, 9:16 motion-graphics sequence without Blender or any AI-video service.

## What it renders

- Editorial kinetic typography using the existing DM Sans and DM Serif Display typefaces.
- A deterministic animated waveform with a moving scan line.
- Parallax grid, orbital rings, particles, glow and scene transitions.
- The existing midnight-navy, muted-teal, antique-gold and ivory visual language.
- A branded Violin Prince end card.

Output contract: **720 × 1280, 30 fps, 10 seconds, H.264 MP4**.

## Rendering architecture

- **Motion 14.14.0** owns the visible animation. Its paused Web Animations API controls expose a seekable `.time` value.
- **HyperFrames 0.9.52** owns the render clock and dispatches `hf-seek` for each requested frame. The prototype seeks every Motion control from that exact timestamp; it does not start a second clock.
- **esbuild** bundles Motion locally, so the rendered page makes no CDN or font-network requests.
- Local font files are copied from the existing Autopilot font assets during the build, together with their OFL notices.
- No GSAP, Blender, or paid video service is required for this prototype.

## Run locally

From this directory:

~~~bash
npm install
npm run build
npm test
npm run render
~~~

The MP4 is written to renders/violin-prince-motion-prototype.mp4.

## Cloud verification

The dedicated GitHub Actions workflow runs only for this prototype branch (or its pull request / manual dispatch). It installs Node.js 22 and FFmpeg, builds and renders the video, verifies the encoded stream with ffprobe, and uploads the MP4 plus a five-frame contact sheet.

No production workflow is edited. There is no YouTube credential, publishing step, production dispatch, Blender dependency, paid model, or change to main.
