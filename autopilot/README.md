# Violin Prince Autopilot

A GitHub-native daily production pipeline for Violin Prince Shorts. ChatGPT prepares the research-backed production plan; GitHub Actions runs narration, original scene-art generation, motion graphics, FFmpeg rendering and media QA; GitHub stores the finished MP4 and publisher handoff.

## Operating model

1. **Plan preparation:** ChatGPT writes a verified plan to \`.autopilot/daily-production-plan.json\` and a request record to \`.autopilot/prepare-request.json\`.
2. **Execution:** the push to \`main\` triggers \`.github/workflows/violin-prince-autopilot.yml\`. The workflow validates the plan, installs the free/local production dependencies and runs \`autopilot/engine/run_daily_plan.py\`.
3. **Audio and narration:** Kokoro-82M synthesizes narration with native word timings. The CC0 sample library provides the violin bed, with the existing local ambient fallback retained.
4. **Visuals:** \`procedural_visuals.py\` creates original, deterministic, full-colour scene artwork locally with Pillow. It creates violin-focused hero art, waveforms, mechanism diagrams, melody maps, lighting and particles. It does not download stock images or call an image-generation API.
5. **Motion and render:** the existing motion-graphics engine, timing system, Pillow composition and FFmpeg renderer assemble the final 9:16 video. FFprobe and the existing video QA validate the result.
6. **Handoff:** GitHub Actions creates a release containing the MP4, \`publish-manifest.json\` and \`asset-provenance.json\`; it also uploads the MP4 and diagnostics as workflow artifacts.

## Infrastructure

This project requires no external infrastructure account, service registration, database, object-storage bucket, AI provider token or vendor deployment workflow.

The production route uses GitHub Actions, Python, Pillow, FFmpeg, Kokoro, the bundled CC0 violin sample library and the ChatGPT-prepared plan. The Autopilot page is a static control-room page linking to GitHub Actions, releases and source code.

## Daily operator and manual recovery

ChatGPT remains the sole daily production operator. The GitHub workflow has no cron schedule. Its push trigger listens only for \`.autopilot/prepare-request.json\` on \`main\`.

A manual \`workflow_dispatch\` run accepts a \`plan_path\` inside \`.autopilot/\` and uses the exact same production route. It does not enable another scheduled operator.

## Publishing boundary

\`PUBLISH_ENABLED=false\` remains set in the workflow. A GitHub release and publisher manifest are a handoff, not social publication. The existing ChatGPT/Metricool/vidIQ operator handles external publishing separately when authorized.

No social publishing credential or permission is added by this pipeline change.

## Visual-art trade-off

Removing the hosted image-generation service also removes its photorealistic image-generation capability. The replacement renders original stylized artwork locally; it is not photorealistic AI imagery. It avoids new accounts, provider keys, paid APIs and stock-photo licensing dependencies. The procedural backgrounds are then enhanced by the existing synchronized typography, diagrams, waveforms, camera motion, transitions, glow and FFmpeg composition.

## Important files

- \`engine/run_daily_plan.py\` — verifies and renders the ChatGPT-prepared plan.
- \`engine/procedural_visuals.py\` — local original scene-art renderer.
- \`engine/motion_graphics.py\` — synchronized animated diagrams, waveforms, melody maps and ambient effects.
- \`engine/creative_direction.py\` — creative-quality and channel-fit rules.
- \`engine/visual_reference.py\` — visual reference, camera choreography and transitions.
- \`engine/publish_handoff.py\` — media provenance and publisher-ready manifest.
- \`../.github/workflows/violin-prince-autopilot.yml\` — GitHub production workflow.
- \`../.github/workflows/autopilot-checks.yml\` — offline tests and deployment-contract checks.

## Local validation

Install the Python requirements from \`engine/requirements.txt\`, install FFmpeg and fonts, then run:

\`\`\`bash
python -m py_compile engine/*.py
python -m unittest discover -s engine/tests -v
\`\`\`
