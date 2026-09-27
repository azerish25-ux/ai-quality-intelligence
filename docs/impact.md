# Explainable change-impact recommendations

FailureLens change-impact analysis is deterministic, advisory, and fail-safe. It produces an inspectable proposed test subset from a validated base/head comparison and an immutable mapping snapshot. It does **not** skip tests, change branch protection, approve a release, or treat a smaller subset as proof of safety.

## Trust boundary

Changed-file JSON is untrusted artifact content. A payload may declare a `trust` value for audit, but that declaration cannot elevate itself. During ingestion FailureLens stores it as `declared_trust`, then binds the effective `trust` from validated transport metadata:

- `self_reported` — default for ordinary uploads and untrusted pull-request artifacts;
- `authenticated_lookup` — comparison obtained through an authenticated repository lookup;
- `trusted_workflow` — comparison supplied by a trusted workflow using reviewed code and metadata.

The raw API query parameter and CLI flag are both named `comparison_trust` / `--comparison-trust`. Replaying identical bytes with conflicting provenance is an idempotency conflict. The GitHub Action defaults to `self_reported`; a workflow must explicitly opt into a stronger value only when its trust model justifies it.

A focused recommendation requires all of the following:

1. an accepted changed-files input;
2. a complete, non-truncated file list;
3. trusted comparison provenance;
4. valid, distinct base and head SHAs consistent with run metadata when present;
5. an immutable trusted mapping snapshot;
6. declared complete mapping coverage;
7. every changed file represented by a mapping path; and
8. no critical broad-execution policy trigger.

Any missing condition produces `FULL_SUITE_REQUIRED`. There is no optimistic default.

## Mapping snapshots

A mapping snapshot contains a versioned test catalogue plus explainable edges. Snapshot version names are immutable within a project: submitting the same version with different content fails instead of silently replacing history.

Supported edge kinds are:

- `file_to_test` — reviewed direct mapping;
- `coverage` — source-to-test coverage relationship;
- `api_ownership` — contract/API ownership relationship;
- `ownership` — reviewed component ownership relationship;
- `historical_failure` — reviewed prior failure relationship, treated as association rather than causal proof; and
- `dependency` — file-to-file reverse dependency traversal.

Each edge records source path, target, confidence, mapping source and mapping version. Dependency traversal is bounded to four edges, cycle-safe, and applies a confidence decay before reaching tests.

Each test definition records a stable key, human-readable identity, optional source path, criticality, mandatory flag, tags, optional estimated duration, and metadata. A test is mandatory when it is explicitly marked mandatory, is critical, or carries a `smoke`, `security`, `transaction`, or `critical` tag.

## Broad-execution policy

FailureLens requires broad execution when a change touches critical shared or operational areas, including:

- authentication or authorization;
- security policy;
- ledger or transaction code;
- migrations or schemas;
- shared/common modules;
- dependency manifests and lockfiles;
- Docker/Compose build configuration;
- CI workflows; and
- test-infrastructure configuration.

Renamed and deleted files retain their old paths for mapping. Added, modified, copied, renamed, and deleted files are supported. An unmapped old or new path is visible and forces full-suite execution.

## Ranking and explanations

The engine combines independent mapping confidences deterministically. Selected tests expose:

- rank and score;
- confidence label;
- reason codes;
- changed and matched paths;
- dependency chain, where applicable;
- mapping source/version;
- exact mapping-edge IDs; and
- mandatory-policy inclusion.

Tests not selected by a focused recommendation remain visible with an explicit exclusion reason. When safety fallback applies, every test is selected and tests without a direct mapping carry `full_suite_safety_fallback`.

Estimated durations are catalogue metadata. FailureLens labels derived duration fields as estimates and does not claim observed runtime savings unless an executed benchmark supplies them.

## Persistence and audit

The relational model persists:

- immutable mapping snapshots;
- test definitions and mapping edges;
- recommendation inputs and digests;
- exact changed-file records;
- base/head revisions;
- engine and policy versions;
- safety reasons and calculation metrics;
- one decision row per catalogue test; and
- append-only reviewer overrides.

Recommendation identity includes the project, run manifest, changed-input digest, mapping snapshot digest, base/head values, normalized changes, engine version and policy version. Repeating identical analysis returns the existing recommendation.

An override requires an actor, action, test key, concrete reason, and expected recommendation revision. Optimistic concurrency prevents stale updates. A mandatory critical test cannot be excluded. No test can be excluded while a full-suite fallback is active.

## API

Representative operations:

```http
POST /api/v1/projects/{project_id}/impact-mappings
GET  /api/v1/projects/{project_id}/impact-mappings
POST /api/v1/projects/{project_id}/impact-recommendations
GET  /api/v1/projects/{project_id}/impact-recommendations
GET  /api/v1/impact-recommendations/{recommendation_id}
POST /api/v1/impact-recommendations/{recommendation_id}/overrides
```

Create a recommendation:

```json
{
  "run_id": "<run containing changed-files input>",
  "mapping_snapshot_id": "<immutable mapping snapshot>",
  "changed_input_id": null
}
```

Apply an override:

```json
{
  "action": "include",
  "test_key": "checkout-e2e",
  "reason": "Reviewed release-risk coupling missing from the current coverage export.",
  "expected_revision": 0
}
```

The API derives the actor from the authenticated reviewer session; clients cannot
submit or override reviewer identity.

## CLI

After ingesting a changed-file artifact or bundle and registering a mapping snapshot through the API/dashboard:

```bash
failurelens impact \
  --project my-project \
  --run <run-id> \
  --mapping-snapshot <snapshot-id>
```

To bind comparison provenance during ingestion:

```bash
failurelens ingest changes.json \
  --project my-project \
  --external-id pr-42 \
  --repository owner/repo \
  --base-sha <base-sha> \
  --commit-sha <head-sha> \
  --comparison-trust authenticated_lookup \
  --process
```

Do not use `trusted_workflow` merely because a file was uploaded by a workflow. Fork code, artifact fields, PR text, filenames, and downloaded metadata remain untrusted data.

## Dashboard workflow

The **Change impact** workspace supports:

1. selecting a run and mapping snapshot;
2. registering an immutable mapping manifest;
3. generating a persisted recommendation;
4. inspecting safety fallbacks, changed files, selected/excluded tests and reasons;
5. including or excluding non-mandatory tests with actor/reason attribution; and
6. inspecting the append-only override audit.

The Chromium E2E journey creates a trusted controlled comparison through the API, waits for the durable worker, registers a mapping in the real dashboard, generates a focused subset, and records a reviewer inclusion.

## Controlled evaluation

`evaluation/generate_impact_corpus.py` generates 12 synthetic cases across 11 scenario families. `evaluation/impact_harness.py` measures:

- defect-revealing-test recall;
- mandatory critical-test recall;
- expected focused/fallback status accuracy;
- deterministic repeat consistency;
- focused selected fraction; and
- missed-defect examples.

The committed controlled fixture reports 1.000 defect-revealing-test recall, 1.000 mandatory critical-test recall, 1.000 expected-status accuracy, and no missed examples. All cases, mappings, labels, and durations are agent-authored synthetic fixtures. Durations are estimates, no production runtime savings are claimed, and the fixture does not satisfy the prompt-required actual LedgerGuard execution count.
