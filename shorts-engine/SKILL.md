---
name: violin-prince-shorts
description: >
  Free-first, music-aware workflow for analysing the user's own violin performances,
  ranking candidate Shorts using audio signal features, auditioning passages and
  rendering vertical MP4 clips in a temporary Google Colab runtime.
license: MIT
---

# Violin Prince Shorts Engine

## Core workflow

1. Use the GitHub-hosted Colab notebook linked in README.
2. Run FFmpeg and Python dependency setup in Colab's temporary runtime only.
3. Ask the user to upload an exported video they own or have permission to edit.
4. Rank candidate windows using audio signal features. Never use transcript-based podcast clipping to identify instrumental violin moments.
5. Offer balanced, lyrical and energetic ranking modes.
6. Explain that the scores are heuristics, not an objective judgement of beauty or musical meaning.
7. Let the user audition the candidates and choose a timestamp range.
8. Render the selected passage as a 1080×1920 MP4 using a full-frame blurred background layout by default.
9. Require the user to inspect the full render before publishing.
10. Do not publish or schedule anything without explicit approval.

## No-cost and privacy requirements

- Do not use paid APIs, paid video-generation services or subscriptions.
- Do not require software to be installed on the user's computer.
- Do not require Google Drive or permanent cloud storage for the first test.
- Upload user media to the temporary Colab runtime only. Never commit video or audio media to this repository.
- Never commit API keys, passwords, OAuth tokens or private audience analytics.
- Do not promise an always-on or unattended service from Colab Free.

## Analysis limitations

Use audio features such as RMS energy, onset strength, spectral centroid variation, chroma movement and beat alignment. These features can identify changes and dynamic passages, but cannot reliably infer emotion, musical phrasing, taste or whether a phrase resolves properly. Human audition is mandatory.

## Later integrations (not active yet)

- YouTube Analytics: owner-authorised OAuth using official API scopes, retrieving only metrics returned by YouTube and mapping elapsedVideoTimeRatio to timestamps.
- Metricool: use the user's connected account to prepare a YouTube Short only after approval of the exact clip, title, destination and schedule.
- Recurring production: only after a persistent scheduler and a safe, free media-storage path are verified. A temporary Colab runtime alone is not a scheduler.
