# Violin Prince — Motion + HyperFrames prototype

A variable-duration vertical motion-graphics renderer. The supplied music file determines the exported video length; the ten-second animation is only the repeating visual motif, not the MP4 limit.

## What this tests

- Motion JavaScript for seekable typography, waveform bars, particles and parallax.
- HyperFrames for frame-by-frame browser capture, source-audio playback and MP4 encoding.
- 1080 × 1920 at 30 fps.
- Full-track audio/video duration matching.
- A cloud-render job using a 37.5-second fixture to prove the output exceeds ten seconds.
- No Blender, AI video service, external media downloads or publishing credentials.

## Full-track duration

The preparation step probes the supplied audio file with FFprobe, copies it to the local generated asset folder, and writes its exact duration into the HyperFrames composition. The same source is attached as a timed audio clip. HyperFrames uses the complete audio file when no shorter clip duration is set.

The current 10-second typography/wave/orbit motif repeats across the music bed so the visual composition continues for the entire track. The progress line and duration label use the full track duration. The music is not cut off at ten seconds. This is the first full-track foundation; editorially varied story chapters, lyric/caption synchronization and optional real 3D violin shots are later visual layers, not duration restrictions.

Supported input extensions: MP3, WAV, M4A, AAC, FLAC and OGG. Track length is limited to 20 minutes in this prototype to keep cloud render jobs bounded.

## Run with a real music file

Requires Node.js 22+ and FFmpeg.

\`\`\`bash
npm install
npm run prepare:composition -- --audio /path/to/your-cover.wav
npm run prepare:motion
npm run lint
npm run check
npm run verify:seeking
npm run render
npm run verify
\`\`\`

The output is \`output/violin-prince-motion-full-track.mp4\`. The generated \`index.html\`, \`assets/music-bed.*\` and \`output/\` are local build files and are ignored by Git.

## Cloud verification

GitHub Actions generates a 37.5-second audio fixture, builds the composition from the detected duration, checks frame seeking at an early and a late time, renders the complete track, and verifies:
- the MP4 contains both video and audio streams;
- the video is 1080 × 1920, 30 fps, H.264;
- the final MP4 duration matches the source audio within 250 ms;
- repeated random-access requests produce the same decoded pixels.

## Optional Autopilot integration

The regular Autopilot renderer remains the default. Set the repository Actions variable **MOTION_HYPERFRAMES_RENDER_ENABLED=true** to select this full-track 2D/2.5D route for a Render or Full stage. The variable defaults to **false**; Node.js 22 and Motion/HyperFrames dependencies are installed only when this route is enabled.

The selected uploaded/creator violin recording is passed from Autopilot's existing Render-stage audio selection into the composition. The composition also receives the already-approved plan title, hook, topic and up to three scene captions. The existing Prepare, Visuals and editorial approval stages still run. The full-track route requires real uploaded/creator audio, refuses generated fallback audio, and is limited to ten minutes in this initial integration. It is intended for the regular staged Render pipeline (or its standard Full run). The separate ChatGPT daily-plan route is deliberately excluded because it creates a Shorts-specific publisher handoff with a generated short soundtrack. The Motion route is mutually exclusive with **BLENDER_RENDER_ENABLED** for now; select Blender for the existing 3D scene route. Full-track output is blocked whenever **PUBLISH_ENABLED=true**, because the current publisher is designed for Shorts rather than full-length music videos. The bridge ensures the pinned HyperFrames Chrome browser before validation and rendering.

The renderer writes into the normal Autopilot output, storage and reporting path. Its feature flag remains off by default, so ordinary production runs are unchanged.

## Blender is optional

This prototype is a 2D/2.5D composition. It does not install, import, invoke or require Blender.

For the wider Autopilot, \`BLENDER_RENDER_ENABLED\` is the explicit opt-in for the existing full-frame 3D route. The regular Autopilot workflow is being changed in this draft PR to default that flag to \`false\`, including on pushes. Set the repository Actions variable \`BLENDER_RENDER_ENABLED=true\` only when a run specifically requires a real 3D instrument/scene. The dedicated first-production Blender workflow remains separately and intentionally 3D-only.

The 2D route uses HTML/CSS/SVG and Motion in Chromium, then HyperFrames/FFmpeg for video capture and encoding. It still uses cloud CPU resources; the goal is to avoid the heavier software-rendered Blender 3D path for flat graphics, titles and 2.5D elements. Rendering speed is measured rather than assumed.

## Motion module and deterministic rendering

The HTML import map points to the pinned Motion ESM package and local browser dependencies under \`node_modules\`; the Motion implementation is not bundled into HyperFrames' scanned script. The timeline is paused and exposes a seek adapter to HyperFrames. The adapter maps full-track time onto the repeating visual cycle while keeping progress tied to the complete audio duration.

## Safety and scope

YouTube publishing remains disabled. This prototype has no upload step or publishing credentials and does not alter production publishing settings. The existing Blender production route and benchmark branch remain separate. PR #57 stays draft until the full-track output is reviewed and the renderer is ready for a controlled Autopilot integration.
