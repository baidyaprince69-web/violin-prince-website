# Violin Prince 2D Animation Engine

This isolated engine powers the ChatGPT-triggered daily production route. It does not use Blender, Frame By Plane, Sketchfab or a 3D renderer.

## Production chain

1. ChatGPT Trigger — the existing request file in .autopilot triggers the main production workflow.
2. AI Story & Scene Director — the existing daily runner validates sources, story evidence, narration and scene direction.
3. Illustration & Character Asset Factory — the scene image service creates story plates; the optional auto-rig tool can prepare a single master character image into candidate transparent parts.
4. Character Rig — torso, head, face, upper arms, forearms and hands are placed as separate layers with pivots and joint anchors.
5. Motion — Motion for JavaScript samples spring/keyframe animations during the Node build. The browser uses paused native Web Animations (WAAPI), which HyperFrames seeks at exact frame times.
6. HyperFrames — HyperFrames lints and renders the HTML composition frame-by-frame.
7. Preview and MP4 output — the isolated rig-test workflow stores its video and inspection artefacts as a GitHub Actions artifact.
8. Existing FFmpeg finishing and QA — the daily video pipeline retains its existing audio mix, word-timed captions, MP4 encoding and ffprobe verification.

## Automatic character separation and rig preview

The optional automatic preparation tool uses two SCHP human-parsing checkpoints:
- Pascal Person Part (7 labels) identifies head, torso, upper-arm and lower-arm regions.
- ATR (18 labels) identifies face, hair, and anatomical left/right arm regions. Those arm masks are mapped to viewer screen-left and screen-right.

The ONNX checkpoints are loaded on CPU through ONNX Runtime. Hugging Face AutoImageProcessor is used for model-specific preprocessing. The checkpoints and model descriptions are available from the MIT-licensed SCHP model cards:
- https://huggingface.co/pirocheto/schp-pascal-7
- https://huggingface.co/pirocheto/schp-atr-18
- https://github.com/pirocheto/schp-human-parsing

From the repository root, install only the optional parsing dependencies:

    python -m pip install -r autopilot/engine/requirements-character.txt

Create the candidate separated layer bundle:

    python autopilot/engine/character_autorig.py --source autopilot/engine/assets/characters/violin-prince-reference/master-character.jpg --reference-dir autopilot/engine/assets/characters/violin-prince-reference --output work/character-autorig/violin-prince

Build the isolated rig-preview project:

    python autopilot/engine/character_rig_test.py --bundle work/character-autorig/violin-prince --output work/character-rig-test

Then build and lint it with the pinned Motion + HyperFrames dependencies from autopilot/engine/animation2d. The GitHub Actions workflow named Character Auto-Rig Test performs these steps and renders an isolated MP4 artefact. It is a manual workflow and becomes dispatchable after the workflow is present on the repository default branch.

## Output bundle

- Nine transparent PNG layers: torso, head, face, upper arms, forearms and hands.
- Seven normalised joint anchors: neck, shoulders, elbows and wrists.
- Separate neutral, blink, speaking, smiling, shocked and sad face plates when all references exist.
- Transparent full-body pose plates for resting hands, one arm raised, two-hand explaining, open palms, point left and point right. Scenes can select a pose plate while retaining the separated rig for blink and other subtle motion.
- separation-preview.png, character.json and separation-report.json.
- A separate Motion + HyperFrames character-rig-preview.mp4 from the manual test workflow.

## Quality gates and limitations

- SCHP models were trained on human-parsing datasets. They can make mistakes on stylised or illustrated artwork; the preview and report always require visual review.
- The models do not provide a dedicated hand class. The first implementation estimates the wrist/hand boundary from the distal lower-arm mask. Check finger silhouettes and wrist seams before accepting the rig.
- Small shoulder overlaps are repaired by local neighbour propagation. Larger hidden areas use the optional LaMa backend. If LaMa is unavailable or reconstruction fails, the pipeline stops for manual review rather than fabricating pixels.
- Face-expression plates are re-segmented and aligned to the master face bounding box. Review glasses, hairline, mouth and eye alignment.
- Full-body pose plates use the supplied authored pose references with a near-white background removed. Use these for large gesture changes; continue to use the separated master layers for smaller articulated movement and expression changes.
- A successful MP4 proves that the candidate rig can be rendered. It does not prove perfect segmentation or final production readiness.

## Existing character contract

A character is animated only when all required separated illustration layers are present. The factory refuses missing parts instead of inventing geometric placeholders. A plan may still contain no characters when the story does not call for a presenter.

## Development checks

Node.js 22 or later is required. Run npm test, node build.mjs and hyperframes lint. The validation job does not render a production video or publish anything.
