# Upload-Post publishing handoff

The Autopilot publisher submits a final, validated MP4 directly from the ephemeral GitHub Actions runner to the Upload-Post API. It targets only the `default` profile's YouTube connection and requests `add_to_queue=true`; the Upload-Post queue supplies the configured next slot (daily, 7:00 PM, `Asia/Kolkata`).

## Required secret

Create a repository Actions secret named `UPLOAD_POST_API_KEY` in the private/public Autopilot repository's Settings → Secrets and variables → Actions. Use the API key from the same Upload-Post account that owns the `default` profile. Never paste the key into a chat, source file, workflow input, commit, or log.

Optional variable: `UPLOAD_POST_PROFILE` (defaults to `default`). The profile name is not a secret.

## Runtime behavior

1. The workflow produces and validates the Short as usual.
2. The existing publish manifest must say `status=rendered`, `publish_ready=true`, `publisher_preflight.status=ready`, and contain no blockers.
3. The adapter reads the Upload-Post queue configuration and verifies the 7 PM Asia/Kolkata daily slot.
4. It submits only to YouTube using the Upload-Post queue and a deterministic idempotency key derived from the GitHub run ID.
5. It stores a non-secret receipt at `work/output/upload-post-queue-receipt.json`.

The adapter never changes the own-voice approval gate or the text/illustration-provider gates. It does not upload raw voice recordings, transcripts, the encrypted voice package, or the generated voice reference sample.

## Current activation blockers

- The Qwen sample still needs a successful private artifact upload and the creator's listening/approval.
- Production narration and illustration generation remain fail-closed pending approved providers.
- The repository secret `UPLOAD_POST_API_KEY` must be added before automated queue handoff can run.

The GitHub daily production trigger must not be enabled until the daily plan source can create fresh, source-verified plans and all production gates pass. A stale static plan must not be reused each day.
