# Architecture — first cloud iteration

```text
Browser
  |
  | opens public GitHub notebook
  v
GitHub (source code + notebook only)
  |
  | Colab reads notebook from this branch
  v
Google Colab temporary runtime
  - installs FFmpeg and Python dependencies in runtime
  - accepts a direct browser upload of the user's video
  - extracts audio and calculates music features
  - ranks non-overlapping candidate windows
  - lets user audition and select a candidate
  - renders a vertical 1080x1920 MP4
  |
  v
Temporary preview (optional manual download)
```

Current iteration does not mount Google Drive, persist the video, fetch YouTube Analytics, connect Metricool, publish or schedule. GitHub stores code; Colab provides temporary compute. Private recordings stay out of the repository.
