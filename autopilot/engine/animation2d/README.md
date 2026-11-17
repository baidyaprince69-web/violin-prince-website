# Violin Prince 2D Animation Engine

This isolated engine powers the ChatGPT-triggered daily production route. It does not use Blender, Frame By Plane, Sketchfab or a 3D renderer.

## Production chain

1. ChatGPT Trigger — the existing request file in .autopilot triggers the main production workflow.
2. AI Story & Scene Director — the existing daily runner validates sources, story evidence, narration and scene direction.
3. Illustration & Character Asset Factory — the existing image service creates scene illustration plates; the asset factory validates and stages separate, original character art layers.
4. Character Rig — the rig contract defines torso, head, face, both upper arms, forearms and hands, plus joint anchors, poses, gestures and expression plates.
5. Motion — Motion for JavaScript samples spring/keyframe animations during the Node build. The browser uses paused native Web Animations (WAAPI), which HyperFrames seeks at exact frame times for movement, gestures, transitions and facial expressions.
6. HyperFrames — HyperFrames lints and renders the HTML composition frame-by-frame at the requested FPS.
7. Preview and MP4 output — the encoded picture is sampled into a visual contact sheet.
8. Existing FFmpeg finishing and QA — FFmpeg mixes narration/music, burns word-timed captions, encodes the final MP4, and ffprobe verifies the video contract.

## Character illustration contract

A character is animated only when the plan supplies original separated artwork layers: torso, head, face, both upper arms, forearms and hands. Every part has its own image, position, size and pivot. Joint anchors are normalised canvas coordinates. At least two face images are required: neutral and one alternate expression. Optional poses, gestures and scene actions direct its movement in each scene.

The asset factory does not draw a substitute geometric body or silently invent missing hands or facial artwork. Incomplete character layers fail validation. A plan may contain no characters when the subject does not call for a human character; scene illustration plates are still rendered through the same Motion + HyperFrames engine.

## Development checks

Node.js 22 or later is required. Install the pinned dependencies from package.json, then run npm test, node build.mjs and hyperframes lint. Motion is a build-time spring/keyframe generator; it is deliberately not bundled into the browser runtime. Browser animation uses paused native WAAPI tracks so the rendered bundle remains deterministic. The validation job does not render a production video or publish anything.
