# Violin Prince Shorts Engine — free cloud workspace

The source code and notebook live in GitHub. The analysis and rendering run in a temporary Google Colab session. **No software needs to be installed on your PC, and no Google Drive folder or ZIP setup is required.**

## Open the workspace

[Open the Violin Prince Short Analyzer in Google Colab](https://colab.research.google.com/github/baidyaprince69-web/violin-prince-website/blob/shorts-engine/shorts-engine/Violin_Prince_Short_Analyzer.ipynb)

1. Sign in to Google if prompted.
2. Run the notebook cells from top to bottom.
3. Upload one of your own exported violin-performance videos when the browser upload control appears.
4. Review and audition candidate moments.
5. Select a candidate and render a vertical Short.
6. Optionally download the rendered MP4. The file stays in the temporary runtime unless you choose to download it.

## What this first version does

- Installs FFmpeg and free Python libraries only inside the temporary Colab runtime.
- Analyses RMS energy, onset strength, spectral centroid variation, chroma movement and beat alignment.
- Ranks candidate 18–45 second windows in balanced, lyrical or energetic mode.
- Lets you listen to shortlisted passages.
- Renders the selected passage as a 1080×1920 MP4 while preserving the full original frame over a blurred background.

## What it does not do yet

- It does not automatically fetch private YouTube audience-retention data.
- It does not publish to YouTube or schedule through Metricool.
- It does not run continuously in the background. Colab Free sessions are temporary and may disconnect.
- It does not generate AI music or full AI music videos.

These are deliberate limits for the first test. The goal is to verify that it finds musically useful passages before adding account connections or automation.

## Privacy and storage

The video is uploaded directly from your browser to the temporary Colab runtime. It is **not** committed to GitHub or saved to Google Drive. Runtime files can disappear when the session ends. Do not place private videos, credentials or OAuth tokens in this public repository.

## Important notes

Scores are signal-processing heuristics, not an AI judgement of musical beauty. Always listen to the candidates and inspect the finished video before publishing. A short violin cover is not automatically copyright-free; Content ID claims may still apply.

## Repository layout

- `Violin_Prince_Short_Analyzer.ipynb` — the cloud workspace.
- `SKILL.md` — the reusable workflow specification.
- `references/architecture.md` — current system architecture.
