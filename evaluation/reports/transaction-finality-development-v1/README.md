# Retained local transaction-finality regression

Measured source: `158d288252d348ca55e3d2a33e109de882196567`.
Eight synthetic cases, one mechanism, SQLite/API/worker execution, four supported
claims and four correct abstentions. No fresh companion/PostgreSQL/browser run.
The report preserves failed corpus minimums and undefined five-category macro F1.

`execution.zip` contains only corpus, safe replay data and the originating reports.
It excludes the SQLite database, private artifact storage, credentials and caches.
`retention.json` records exact digests. This archive does not certify later commits.
Use `evaluation.verify_snapshot.unpack_snapshot(..., allow_input_bundles=True)`
with the recorded digest, then `evaluation.campaign_harness.evaluate(corpus,
replay, enforce_minimums=False, score_split="development")` to independently
rescore. Offline verification is not fresh execution.
