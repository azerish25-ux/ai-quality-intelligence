# API and CLI

## Authentication and project roles

Except for liveness/readiness, `POST /api/v1/auth/login`, and one-time-token redemption at `POST /api/v1/auth/recovery`, API operations require an authenticated principal. Browser sessions use an `HttpOnly` cookie; API clients may send the same session secret as `Authorization: Bearer <session-token>`. A project ingestion credential is sent as either a bearer token or `X-FailureLens-Token` and is limited to creating an ingestion in its assigned project.

```bash
curl --request POST \
  --header 'Content-Type: application/json' \
  --data '{"username":"admin@example.test","password":"<password>"}' \
  'http://localhost:8000/api/v1/auth/login'
```

The login response includes a bearer token and also sets the browser cookie. `GET /api/v1/auth/me` returns the verified identity and project memberships; `POST /api/v1/auth/logout` revokes the current session.

Project permissions are cumulative:

- `viewer`: read runs, analyses, approved evidence, history, clusters, performance, and audit-backed results;
- `reviewer`: viewer access plus analysis reviews, cluster corrections, impact overrides, and persisted analytical comparisons; and
- `administrator`: reviewer access plus project memberships, ingestion credentials, mappings, policies, and artifact ingestion.

An administrator manages identities and project access through:

- `GET`/`POST /api/v1/users` for system-administrator user provisioning;
- `GET`/`POST /api/v1/projects/{project_id}/members`;
- `PATCH`/`DELETE /api/v1/projects/{project_id}/members/{membership_id}`;
- `GET`/`POST /api/v1/projects/{project_id}/ingestion-tokens`;
- `POST /api/v1/projects/{project_id}/ingestion-tokens/{token_id}/revoke`; and
- `GET /api/v1/projects/{project_id}/audit-events` for reviewers and administrators.

The raw secret from an ingestion-token creation response is shown once. Only its digest and display prefix are retained. Client payloads never select the actor for a review or override; actor identity comes from the authenticated principal.

## Durable artifact ingestion

`POST /api/v1/projects/{project_id}/ingestions` supports two contracts:

1. `Content-Type: application/json` with no `filename` query parameter preserves the versioned normalized-observation API.
2. A raw request body plus `external_id` and `filename` stores and queues a supported standalone artifact or FailureLens ZIP bundle.

Raw upload example:

```bash
curl --request POST \
  --header 'X-FailureLens-Token: <project-ingestion-token>' \
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

## Human review queue and decisions

`GET /api/v1/projects/{project_id}/review-queue` returns the latest analysis for each failure, with optional `status=pending|reviewed|all`, category and pagination filters. Each row includes the test identity, machine category, severity, evidence completeness, policy flags, and latest human decision/version.

Reviewers submit append-only decisions through `POST /api/v1/analyses/{analysis_id}/reviews` and read the full history through `GET /api/v1/analyses/{analysis_id}/reviews`. The request uses `expected_version` optimistic concurrency and may:

- accept or reject the machine analysis;
- request more evidence;
- propose a category correction;
- cite same-project supporting or contradictory evidence;
- record hypothesis dispositions and an investigation outcome; and
- record advisory release language.

```json
{
  "decision": "category_correction",
  "proposed_category": "test_defect",
  "reason": "The approved locator shows an obsolete selector rather than a product response.",
  "expected_version": 0,
  "supporting_evidence_ids": ["<evidence-id>"],
  "contradictory_evidence_ids": [],
  "hypothesis_decisions": [
    {"hypothesis": "product regression", "status": "rejected"}
  ],
  "investigation_outcome": "Update the test selector and rerun the full browser project.",
  "release_advice": "INVESTIGATE"
}
```

The server records the authenticated reviewer; an `actor` field is rejected. `NO_BLOCKER_IDENTIFIED_IN_OBSERVED_SCOPE` is blocked when evidence is incomplete, the machine result still carries unresolved product risk, or safety policy flags remain active. Human decisions never overwrite the original analysis or execute an external release/quarantine action.

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

## Infrastructure events and prior-only correlations

Infrastructure events are independently persisted project records. A test artifact cannot self-promote its own infrastructure claim into trusted corroboration.

- `POST /api/v1/projects/{project_id}/infrastructure-events` validates and idempotently records an event.
- `GET /api/v1/projects/{project_id}/infrastructure-events` lists project events with optional `event_kind`, `before`, `after`, `limit`, and `offset`.
- `GET /api/v1/infrastructure-events/{event_id}` returns one event and its trust/digest provenance.
- `POST /api/v1/tests/{execution_id}/infrastructure-correlations` creates an immutable prior-only snapshot.
- `GET /api/v1/infrastructure-correlations/{snapshot_id}` returns the persisted snapshot and exact run members.

The history endpoint also returns a non-persisted `infrastructure_correlations` section calculated with the same cohort filters. Correlation requests accept optional `after`, `before`, browser, branch, environment, run scope, timezone, worker/shard counts, event kind, overlap window and minimum support. `before` is clamped to the selected run.

Responses disclose accepted events, rejected events and reasons, exposed/unexposed outcomes, exact denominators, Wilson intervals, absolute rate difference, relative risk where defined, per-kind associations, confounders and immutable provenance. Statuses are `AVAILABLE`, `INSUFFICIENT_DATA`, `NO_MATCHING_EVENTS`, `INCOMPATIBLE_CONTEXT`, `UNTRUSTED_EVENT_SOURCE`, `CONFOUNDED`, or `TRUNCATED`. Every response explicitly denies causal or independent classification authority. See `docs/infrastructure.md`.

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
  "action": "include",
  "test_key": "profile-e2e",
  "reason": "Profile storage is shared with the changed account module.",
  "expected_revision": 1
}
```

See `docs/impact.md` for the policy, ranking and evaluation boundaries.

## Compatible performance intelligence

Performance observations are normalized during ingestion and remain linked to approved safe evidence. Test durations use the final attempt for each logical test/browser pair; k6 `handleSummary` values retain the exported statistic, unit, sample count, threshold state, producer/version and workload dimensions.

- `POST /api/v1/projects/{project_id}/performance-policies` registers an immutable versioned compatibility/tolerance policy.
- `GET /api/v1/projects/{project_id}/performance-policies` lists policies newest first.
- `GET /api/v1/runs/{run_id}/performance-observations` lists normalized current observations and evidence IDs.
- `POST /api/v1/projects/{project_id}/performance-baselines` creates an immutable prior-only baseline for one observation.
- `GET /api/v1/performance-baselines/{baseline_id}` returns accepted members, rejected candidates/reasons, provenance, aggregation and support.
- `POST /api/v1/runs/{run_id}/performance-comparisons` compares all or selected run observations with compatible baselines.
- `GET /api/v1/runs/{run_id}/performance-comparisons` lists persisted findings.
- `GET /api/v1/performance-comparisons/{comparison_id}` returns one finding with its baseline snapshot.

Example comparison request:

```json
{
  "policy_id": "<optional-immutable-policy-id>",
  "observation_ids": ["<optional-observation-id>"]
}
```

Omitting `policy_id` uses or creates the project’s strict default policy. Omitting `observation_ids` compares every normalized observation in the run. Results are `REGRESSION`, `IMPROVEMENT`, `WITHIN_TOLERANCE`, `INCONCLUSIVE`, `BASELINE_UNAVAILABLE` or `INCOMPATIBLE_BASELINE`. A missing or unsafe cohort never becomes a reassuring zero. The response includes exact current/baseline evidence IDs, run/sample counts, tolerances, compatibility reasons, confounders and next-measurement guidance. See `docs/performance.md`.

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
- `POST /api/v1/auth/login`
- `POST /api/v1/auth/logout`
- `GET /api/v1/auth/me`
- `GET`/`POST /api/v1/users`
- `GET /api/v1/overview`
- `POST /api/v1/projects`
- `GET /api/v1/projects`
- `GET`/`POST /api/v1/projects/{project_id}/members`
- `PATCH`/`DELETE /api/v1/projects/{project_id}/members/{membership_id}`
- `GET`/`POST /api/v1/projects/{project_id}/ingestion-tokens`
- `POST /api/v1/projects/{project_id}/ingestion-tokens/{token_id}/revoke`
- `GET /api/v1/projects/{project_id}/audit-events`
- `GET /api/v1/projects/{project_id}/review-queue`
- `GET /api/v1/projects/{project_id}/runs`
- `POST /api/v1/projects/{project_id}/impact-mappings`
- `GET /api/v1/projects/{project_id}/impact-mappings`
- `POST /api/v1/projects/{project_id}/impact-recommendations`
- `GET /api/v1/projects/{project_id}/impact-recommendations`
- `GET /api/v1/impact-recommendations/{recommendation_id}`
- `POST /api/v1/impact-recommendations/{recommendation_id}/overrides`
- `GET /api/v1/runs/{run_id}`
- `GET /api/v1/runs/{run_id}/inputs`
- `POST /api/v1/projects/{project_id}/performance-policies`
- `GET /api/v1/projects/{project_id}/performance-policies`
- `GET /api/v1/runs/{run_id}/performance-observations`
- `POST /api/v1/projects/{project_id}/performance-baselines`
- `GET /api/v1/performance-baselines/{baseline_id}`
- `POST /api/v1/runs/{run_id}/performance-comparisons`
- `GET /api/v1/runs/{run_id}/performance-comparisons`
- `GET /api/v1/performance-comparisons/{comparison_id}`
- `GET /api/v1/projects/{project_id}/clusters`
- `GET /api/v1/runs/{run_id}/clusters`
- `GET /api/v1/clusters/{cluster_id}`
- `GET /api/v1/clusters/{cluster_id}/revisions`
- `POST /api/v1/clusters/{cluster_id}/reviews`
- `GET /api/v1/runs/{run_id}/failures`
- `GET /api/v1/tests/{execution_id}/history`
- `POST /api/v1/projects/{project_id}/infrastructure-events`
- `GET /api/v1/projects/{project_id}/infrastructure-events`
- `GET /api/v1/infrastructure-events/{event_id}`
- `POST /api/v1/tests/{execution_id}/infrastructure-correlations`
- `GET /api/v1/infrastructure-correlations/{snapshot_id}`
- `POST /api/v1/failures/{failure_id}/analyses`
- `GET /api/v1/analyses/{analysis_id}`
- `GET /api/v1/analyses/{analysis_id}/reviews`
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
failurelens performance --run <run-id>
failurelens performance --run <run-id> --policy <policy-id> --observation <observation-id>
failurelens infrastructure-event infrastructure-event.json --project checkout
failurelens infrastructure-correlate --execution <execution-id> --event-kind service_outage --window-seconds 900 --minimum-support 3
```

Without `--process`, `ingest` queues work for `failurelens-worker`. `--process` claims one job using the same worker implementation and exits nonzero when no run is published. The complete differentiated quality-gate/operational exit-code contract remains future work.

## M5.3 operational endpoints

See [Operational lifecycle](operations-lifecycle.md) for policies, concrete API routes,
CLI recovery, immutable decision versus expired-evidence semantics, and verification
limits. The dashboard uses `/review-queue/page` and `/audit-events/page`; existing
list routes remain compatibility interfaces. Audit CSV is generated only by the
administrator-authorized `/audit-events/export` endpoint, not from a client-side
recent-record window.
