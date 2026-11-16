# Violin Prince Autopilot — 2D Production

The Autopilot production route turns a ChatGPT-authored plan into a narrated 2D explainer. GitHub Actions is the cloud execution runner. ChatGPT remains the planner and intended daily scheduler.

## Production flow

1. ChatGPT writes \`.autopilot/daily-production-plan.json\`.
2. The plan is checked for the fields needed by the five-scene composition.
3. Kokoro-82M generates the narration and its native word timings.
4. The repository's CC0 sampled-violin renderer creates a quiet music bed.
5. Motion builds the portrait-native scenes from original HTML, CSS and SVG artwork.
6. HyperFrames performs deterministic timeline seeking and renders the full track.
7. FFmpeg prepares/mixes the audio and extracts phone-review frames.
8. The MP4 and QA reports are uploaded as a GitHub Actions artifact.

## Plan format

The plan is authored by ChatGPT and supplied directly to the runner. It does not go through an automatic publisher-research, article-date, source-quote, claim-coherence or narration-evidence verification stage.

Required fields:

- \`title\`, \`topic\`, and \`narration_script\`
- Exactly five \`scenes\`, each with a short \`caption\`
- Optional scene fields: \`graphic_label\`, \`graphic_detail\`, \`graphic_data\`, and \`visual_mode\`

Supported visual modes are 2D illustration, mechanism diagram, waveform, full-screen 2D, melody map, comparison and illustrated violin performance. Scene content is story-specific.

There is no fixed narration word-count or 24-second narration cap. The final timeline follows the generated narration audio plus a configurable final-scene hold. Kokoro's native word timings are checked for valid, ordered caption synchronisation; they are not used to verify factual claims.

## Rendering configuration

The production workflow is \`.github/workflows/violin-prince-autopilot.yml\`.

- Renderer: Motion + HyperFrames only
- Portrait composition: 1080 × 1920
- Frame rate: 30 FPS
- Default final-scene hold: 3 seconds; configurable from 0 to 3 seconds
- Maximum accepted full-track duration: 600 seconds
- Node.js: 22
- Audio/video encoding and inspection: FFmpeg and FFprobe

Motion and HyperFrames dependencies are pinned in \`prototypes/hyperframes-motion/package.json\`.

## Run

A normal run uses the current saved plan:

\`\`\`bash
python autopilot/engine/run_daily_plan.py --plan .autopilot/daily-production-plan.json
\`\`\`

The workflow can also be dispatched manually with a different plan file inside \`.autopilot/\`. Plan files must remain inside that directory.

## Outputs

The canonical video filename is:

\`\`\`text
work/output/violin-prince-explainer.mp4
\`\`\`

The output bundle includes metadata with the render report, narration timing summary, video dimensions/duration and MP4 SHA-256. Motion contact sheets, phone previews and seek-verification reports are retained when produced.

## Publishing boundary

Publishing and YouTube upload are disabled. The workflow creates a GitHub Actions artifact only. It does not schedule, upload or publish videos. Do not enable publishing until a separate approved handoff and publishing workflow is specified.

## Current scope

This branch's intended production is entirely 2D. It has no 3D scene renderer, no 3D model discovery or download step, and no external image-generation dependency. The production runner does not call the old research/staged pipeline.
