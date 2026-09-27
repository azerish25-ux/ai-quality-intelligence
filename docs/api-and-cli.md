# API and CLI

## Durable artifact ingestion

`POST /api/v1/projects/{project_id}/ingestions` supports two contracts:

1. `Content-Type: application/json` with no `filename` query parameter preserves the versioned normalized-observation API.
2. A raw request body plus `external_id` and `filename` stores and queues a supported standalone artifact or FailureLens ZIP bundle.

Raw upload example:

```bash
curl --request POST \
  --header 'Content-Type: application/zip' \
  --data-binary @failurelens-bundle.zip \
  'http://localhost:8000/api/v1/projects/<project-id>/ingestions?external_id=gha-901&filename=failurelens-bundle.zip&attempt=1&expected_inputs=3'
```

A raw upload returns `202 Accepted` with an `IngestionRead` resource. Parsing and automatic deterministic analysis happen in the database-backed worker, not in the HTTP request.

`expected_inputs` means expected **required artifacts/shards**, not test observations. For manifest `2.0`, the worker compares this optional outer declaration with the manifest’s required-input count and retains the larger expected scope. The number of parsed tests is stored separately as `source_metadata.observation_count`.

## Ingestion lifecycle operations

- `GET /api/v1/projects/{project_id}/ingestions`
- `GET /api/v1/ingestions/{ingestion_id}`
- `POST /api/v1/ingestions/{ingestion_id}/cancel`
- `POST /api/v1/ingestions/{ingestion_id}/retry`

States are `queued`, `running`, `succeeded`, `partial`, `failed`, `cancelled`, and `dead_lettered`. Permanent invalid-input errors are not retried. Transient worker failures use bounded delay and eventually dead-letter. A completed ingestion includes its `run_id`.

## Run input diagnostics

`GET /api/v1/runs/{run_id}/inputs` returns persisted input records ordered with required inputs first. Each record contains:

- manifest input ID, kind and path;
- required/optional flag;
- `accepted`, `restricted`, `missing`, `rejected`, or `unsupported` status;
- digest, size and media type when bytes were received;
- adapter/parser version;
- warnings and bounded safe metadata.

A required input can be received but still prevent completeness—for example a screenshot retained as restricted metadata, a digest mismatch, or an unsupported declared format.

## Evidence integrity and safe inspection

Every normalized observation is bound to its exact test execution and manifest input, then stored as an immutable content-addressed safe derivative. Analysis never queries all evidence from a run. It selects the current execution plus only explicitly labeled shared or same-input diagnostics.

Before an analysis revision is visible, the publication validator re-reads the derivative and checks its source/derivative digest chain, project/run/execution scope, locator bounds, exact excerpt, typed observation, approval/retention policy and typed claim support. Analysis responses include `validation_version` and `validation_results`, including accepted/rejected evidence IDs and claim-level reasons. Failed validation causes safe abstention rather than a reassuring category.

`GET /api/v1/evidence/{evidence_id}` returns only approved safe evidence metadata and sanitized content. It includes execution/input scope, locator and derivative digest/provenance, but never returns a filesystem path or restricted source bytes. Restricted, unapproved or expired derivatives return `403`.

## Explainable failure clusters

Clustering runs after normalized failures are persisted. It is deterministic and project-scoped; replaying the same inputs with the same algorithm/feature versions does not duplicate clusters or memberships.

- `GET /api/v1/projects/{project_id}/clusters?limit=50&offset=0` lists active project clusters. Add `include_superseded=true` to audit historical identities.
- `GET /api/v1/runs/{run_id}/clusters?limit=50&offset=0` lists active clusters containing a current member from the run.
- `GET /api/v1/clusters/{cluster_id}` returns the current revision, representative failure, member scores, component weights, matching/conflicting signals, candidate reasons, uncertainty and reviewed decisions.
- `GET /api/v1/clusters/{cluster_id}/revisions?limit=100&offset=0` returns revisions newest first; prior memberships remain immutable.
- `POST /api/v1/clusters/{cluster_id}/reviews` records a reviewed `confirm`, `split`, or `merge` with `expected_revision` optimistic concurrency.

Example reviewed split:

```json
{
  "actor": "reviewer@example.test",
  "decision": "split",
  "reason": "The selector and endpoint evidence identify a separate incident.",
  "expected_revision": 2,
  "failure_ids": ["<failure-id>"],
  "target_cluster_id": null
}
```

A split requires a non-empty proper subset of the current members. A merge requires another active cluster in the same project. Stale revisions, cross-project targets and attempts to review a superseded cluster return `409`. Human decisions create append-only revisions and never erase an earlier automatic grouping.

Cluster similarity is not a causal claim. The API exposes negative/conflicting signals and singleton/mixed uncertainty rather than hiding them, and cluster membership is not accepted as evidence for dismissing product risk.

## Prior-only test history

```http
GET /api/v1/tests/{execution_id}/history
```

The selected execution defines the exact logical test identity and maximum cutoff. Optional filters are `after`, `before`, `browser`, `branch`, `environment`, `run_scope`, `worker_count`, `shard_count`, `timezone`, `limit`, and `offset`. `before` may narrow the history window but cannot expose runs at or after the selected execution.

The response contains explicit first/final outcome counts, pass/fail and retry-recovery numerators/denominators, 95% Wilson intervals, sample-size status, browser/branch/environment/scope/worker/shard/time-bucket breakdowns, sequences, recurrence intervals, qualifying prior review events, safety reasons, a deterministic history digest and exact contributing run/execution IDs. Runs where the test was absent are reported separately and are not counted as passes. See `docs/history.md` for definitions and known-flake safety policy.

## Explainable change impact

Impact analysis is deterministic and advisory. It never executes or skips tests. A project first registers an immutable mapping snapshot, then requests a recommendation for a completed run containing changed-file evidence.

- `POST /api/v1/projects/{project_id}/impact-mappings` creates a versioned mapping snapshot with tests and typed edges.
- `GET /api/v1/projects/{project_id}/impact-mappings` lists snapshots newest first.
- `POST /api/v1/projects/{project_id}/impact-recommendations` validates the run, changed input, mapping snapshot and base/head comparison, then persists a deterministic recommendation.
- `GET /api/v1/projects/{project_id}/impact-recommendations` lists project recommendations.
- `GET /api/v1/impact-recommendations/{recommendation_id}` returns changed files, selected/excluded tests, reasons, confidence, safety state, provenance and override audit.
- `POST /api/v1/impact-recommendations/{recommendation_id}/overrides` appends an attributed include/exclude decision using `expected_revision` optimistic concurrency.

Mapping edges use explicit source kinds such as `file_to_test`, `coverage`, `api_ownership`, `ownership`, `historical_failure`, `dependency` and `mandatory`. Recommendations support renamed/deleted paths and bounded reverse-dependency traversal. Each selected item records score components, mapping edge IDs and human-readable reasons; excluded tests remain visible with exclusion reasons.

The current recommendation states are `FOCUSED_SUBSET` and `FULL_SUITE_REQUIRED`. The policy conservatively returns `FULL_SUITE_REQUIRED` for self-reported/untrusted comparisons, incomplete or truncated change lists, missing or unmapped paths, stale/mismatched base/head values and critical shared/auth/authorization/ledger/migration/dependency/CI/test-infrastructure changes. Mandatory critical tests are always included and cannot be excluded by an override.

A changed-file payload's own `trust` field is never authoritative. Raw ingestion accepts a separate `comparison_trust` transport value, defaulting to `self_reported`; the service stores the payload label as `declared_trust` and binds the effective trust from transport metadata. The composite Action validates and passes this field without evaluating artifact-controlled shell text.

Example request:

```json
{
  "run_id": "<run-id>",
  "mapping_snapshot_id": "<snapshot-id>",
  "changed_input_id": "<optional-run-input-id>",
  "base_sha": "<validated-base-sha>",
  "head_sha": "<validated-head-sha>"
}
```

Example override:

```json
{
  "actor": "reviewer@example.test",
  "action": "include",
  "test_key": "profile-e2e",
  "reason": "Profile storage is shared with the changed account module.",
  "expected_revision": 1
}
```

See `docs/impact.md` for the policy, ranking and evaluation boundaries.

## Manifest `2.0` ZIP contract

A root `manifest.json` declares every artifact:

```json
{
  "schema_version": "2.0",
  "inputs": [
    {
      "id": "pytest-results",
      "kind": "pytest-json",
      "path": "reports/report.json",
      "required": true,
      "media_type": "application/json"
    },
    {
      "id": "network",
      "kind": "har",
      "path": "evidence/network.har",
      "required": false
    },
    {
      "id": "trace",
      "kind": "playwright-trace",
      "path": "evidence/trace.zip",
      "required": true
    }
  ]
}
```

Supported canonical kinds are documented in `docs/input-compatibility.md`. Aliases such as `xml`, `junit`, `pytest`, `console`, `network`, `image`, `trace`, `github`, and `changes` resolve through the versioned adapter registry.

Schema `1.0` bundles with a single `report` path remain readable. A ZIP without a manifest remains a compatibility path only when it contains exactly one detectable report. New producers should emit schema `2.0`.

## Other API operations

- `GET /health/live`
- `GET /health/ready`
- `GET /api/v1/overview`
- `POST /api/v1/projects`
- `GET /api/v1/projects`
- `GET /api/v1/projects/{project_id}/runs`
- `POST /api/v1/projects/{project_id}/impact-mappings`
- `GET /api/v1/projects/{project_id}/impact-mappings`
- `POST /api/v1/projects/{project_id}/impact-recommendations`
- `GET /api/v1/projects/{project_id}/impact-recommendations`
- `GET /api/v1/impact-recommendations/{recommendation_id}`
- `POST /api/v1/impact-recommendations/{recommendation_id}/overrides`
- `GET /api/v1/runs/{run_id}`
- `GET /api/v1/runs/{run_id}/inputs`
- `GET /api/v1/projects/{project_id}/clusters`
- `GET /api/v1/runs/{run_id}/clusters`
- `GET /api/v1/clusters/{cluster_id}`
- `GET /api/v1/clusters/{cluster_id}/revisions`
- `POST /api/v1/clusters/{cluster_id}/reviews`
- `GET /api/v1/runs/{run_id}/failures`
- `GET /api/v1/tests/{execution_id}/history`
- `POST /api/v1/failures/{failure_id}/analyses`
- `GET /api/v1/analyses/{analysis_id}`
- `POST /api/v1/analyses/{analysis_id}/reviews`
- `GET /api/v1/evidence/{evidence_id}`
- `GET /api/v1/evaluations/latest`
- `POST /api/v1/demo/seed` in demo mode

FastAPI generates the authoritative OpenAPI schema at runtime.

## CLI

```bash
failurelens doctor
failurelens ingest report.xml --project checkout --external-id gha-901 --run-scope full_suite --environment ci-linux --timezone America/Halifax --worker-count 4 --shard-count 2
failurelens ingestion-status --ingestion <ingestion-id>
failurelens ingest failurelens-bundle.zip --project checkout --external-id gha-902 --expected-inputs 3 --process
failurelens report --run <run-id> --format markdown
failurelens impact --project checkout --run <run-id> --mapping-snapshot <snapshot-id>
```

Without `--process`, `ingest` queues work for `failurelens-worker`. `--process` claims one job using the same worker implementation and exits nonzero when no run is published. The complete differentiated quality-gate/operational exit-code contract remains future work.
