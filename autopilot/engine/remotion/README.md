# Violin Prince — optional Remotion compositor

This is an isolated, opt-in **post-render compositor**. It is deliberately not imported by
`run_daily_plan.py`, `hyperframes_pipeline.py`, the daily GitHub Actions queue, or any
YouTube publishing module.

## Why it is separate

The current engine already uses Motion + HyperFrames for its animated scene and
character-rendering work, followed by FFmpeg finishing and media QA. Remotion is added
as an independent final-look experiment for optional title and brand overlays on a
copy of an existing MP4.

The boundary is:

```text
Existing Motion + HyperFrames + FFmpeg production
                  |
                  v
          Existing verified MP4
                  |
          (manual opt-in only)
                  v
       Remotion compositor candidate
                  |
          separate review artifact
                  |
        creator review / approval
                  |
       existing publisher remains separate
```

Remotion does not replace the articulated Violin Prince rig, create realistic violin
performance from a still image, change story research, alter the existing audio mix, or
make publishing decisions.

## Safety and compatibility rules

- The source MP4 is copied into Remotion's temporary public assets. The source file is
  never edited or overwritten.
- Input is checked before rendering: MP4 video and audio streams, portrait 720x1280,
  approximately 25 fps, and a duration between 2 and 180 seconds.
- The compositor preserves the source audio and video duration. It adds only the optional
  Violin Prince opening title treatment.
- The output is a **candidate**, not a production-approved video. It is not put into the
  daily publish manifest and it is never sent to YouTube by this package.
- The separate GitHub Actions workflow is manually dispatchable after it reaches the
  default branch. Its feature-branch push check uses a synthetic local video only.
- The existing daily queue and upload workflow are intentionally unchanged. There is no
  new schedule, no automatic dependency installation in the daily job, and no shared
  concurrency group with the daily queue.

## Local use

Requirements: Node.js 22+, FFmpeg and FFprobe.

```bash
cd autopilot/engine/remotion
npm install --no-audit --no-fund
npm test
npm run render -- --input ../../../work/source.mp4 --output ../../../work/remotion-preview.mp4 --title "A Violin Performance" --subtitle "VIOLIN PRINCE"
```

The generated MP4 and its adjacent `.report.json` are separate from the input.

## Cloud review

The workflow `.github/workflows/remotion-compositor-preview.yml` has two modes:

1. A feature-branch push creates a short synthetic MP4 and verifies that Remotion can
   render and validate an isolated candidate.
2. A manual dispatch accepts a GitHub Actions run ID and artifact name. It downloads
   the selected MP4 artifact, renders a separate candidate, and uploads the result as a
   new review artifact. This mode does not invoke the publisher.

For the current full-body rig test, the initial manual-dispatch defaults point to run
`46047995951` and artifact `full-body-character-only-review-863`. GitHub artifact
retention is finite; supply a newer run ID and matching artifact name after that test
artifact expires.

## Dependency and licensing note

Remotion and `@remotion/cli` are pinned to the same exact version (`4.0.547`) to avoid
version skew. React and React DOM are pinned to `18.3.1`; Remotion's package metadata
declares React and React DOM peer dependencies of `>=16.8.0`.

Review Remotion's current license terms before scaling deployment beyond an individual
or team of up to three people.
