# Phase 3 — GitHub Actions artifact handoff

## What happens
1. The V3 workflow finishes rendering and uploads its review artifact (`v3-motion-prototype-<run-id>`).
2. A dependent, reusable Phase 3 workflow downloads that exact artifact by run ID and artifact name.
3. Phase 3 verifies the recovery manifest, QC report, final MP4 filename, file size, SHA-256 and QC timestamp relationship. Every individual QC check must pass.
4. Phase 3 prepares one `READY` release record per selected destination (YouTube, Facebook and Instagram). It does not call a publisher, upload media or publish anything.
5. The SQLite release ledger is uploaded as the `phase3-release-ledger` Actions artifact. The next run restores that ledger before creating records, so the same approved asset reuses its prior release IDs.

## Persistent state and retention
The ledger artifact is retained for 90 days and replaced with an updated snapshot after each successful Phase 3 handoff. This is rolling persistence: normal runs refresh it before expiry. If the latest ledger artifact is expired, incomplete or cannot be queried, Phase 3 stops instead of silently creating an empty database.

This is not an eternal database. If the pipeline is inactive for longer than the 90-day artifact retention window, an owner must restore a saved ledger before the pipeline can resume. No Google Drive, Metricool, Cloudflare D1, local PC or publishing credentials are used by this handoff.

## Video retention
The Phase 2 MP4 remains in its original GitHub Actions artifact. Phase 3 stores only release metadata, fingerprints and event history in SQLite; it does not copy, move, mutate or delete the MP4. The video artifact's existing 14-day retention remains unchanged. Phase 4 must preserve video availability until every selected native-platform upload is authoritatively confirmed; only then may a separate cleanup step delete the video artifact.

## Safety
- `PUBLISH_ENABLED=false` is forced in the workflow and checked by the handoff module.
- No YouTube, Facebook or Instagram API calls occur.
- A release starts in `READY`; this does not mean it was uploaded.
- SQLite writes use transactions and an integrity check.
- The idempotency key is based on the source artifact/video fingerprint, destination and metadata fingerprint.
- A missing or mismatched MP4, manifest or QC report fails closed.

## Verification
The feature-branch workflow first tests approved V3 run `43463908965`. A second branch run uses the exact same artifact again, restores the first run's ledger and verifies that all three release IDs are reused and the release row count remains three. Both runs must finish with zero provider requests.
