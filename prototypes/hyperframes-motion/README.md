# Motion + HyperFrames — Violin Prince

This is the portrait-native 2D motion-graphics renderer used by Violin Prince Autopilot.

## What it does

- Builds original scenes with HTML, CSS and SVG illustrations.
- Animates scene elements, diagrams, labels and word-synchronised reveals with Motion.
- Uses HyperFrames for deterministic timeline seeking and frame capture.
- Exports the full narration-driven timeline and review previews.

It is a 2D illustration and motion-graphics pipeline. It does not acquire external models or image/video assets.

## Render contract

- Canvas: 1080 × 1920 portrait
- Frame rate: 30 FPS
- Scene count: five story-specific scenes
- Timing: Kokoro native word cues and the narration audio duration drive the visual timeline
- Output: MP4 plus contact sheet, phone preview and seek-verification report

The final video duration is driven by narration audio plus the configured final-scene hold; the renderer does not use a fixed 10-second demo duration.

## Development

Motion and HyperFrames versions are pinned in \`package.json\`.

\`\`\`bash
npm install
npm run prepare:motion
npx hyperframes browser ensure
npm run lint
npm run verify:seeking
npm run render
npm run verify
\`\`\`

The Autopilot runner is responsible for providing the composition data, narration audio, native word cues and background music. The production workflow uploads review artifacts only; publishing is a separate, disabled step.
