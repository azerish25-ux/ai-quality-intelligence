# FailureLens
## Evidence-Grounded Test Failure Triage and AI Evaluation

FailureLens is a self-hosted quality-intelligence platform that turns automated-test artifacts into evidence-linked failure investigations. Its mandatory analysis path is deterministic and CPU-only: no paid model API, cloud account, GPU, or runtime model download is required.

> **Current delivery status: M1 and the M3 deterministic analytical core are complete; M2 remains partial; M4 now has working prior-only historical intelligence, explainable change-impact recommendations, and compatibility-gated performance regression analysis. Separately modeled infrastructure-event correlation remains open. The full master specification is incomplete.**
>
> This revision adds normalized evidence-linked performance observations, immutable versioned policies and prior-only baseline snapshots, strict workload/environment/unit/trust compatibility, conservative regression classification, typed API/CLI operations, an API-backed dashboard workflow, Chromium coverage and a controlled 20-case performance safety benchmark. Safe binary derivatives, producer-pinned integration fixtures, project-scoped roles, infrastructure-event correlation, actual LedgerGuard evaluation cases, and live idempotent PR publication remain open.

## What works

### Durable execution path

- FastAPI API with typed OpenAPI schemas and separate liveness/readiness endpoints.
- SQLAlchemy/Alembic relational model for projects, durable ingestions, runs, per-run input scope, test executions, artifacts, evidence, failures, analyses, reviews and leased jobs.
- Raw streamed uploads with content-addressed restricted storage, digest/size revalidation, bounded files and safe filenames.
- Durable states: `queued`, `running`, `succeeded`, `partial`, `failed`, `cancelled`, and `dead_lettered`.
- PostgreSQL job claiming with leases, heartbeats, stale-lease recovery, bounded retry, permanent-input failure handling, cancellation safety and idempotent replay.
- Automatic deterministic analysis after parsing; the normal flow requires no second analysis request.

### Manifest `2.0` and honest completeness

A FailureLens ZIP may declare multiple artifacts through a root `manifest.json`. Each input has a stable ID, format kind, path, required/optional flag, optional expected digest/media type and producer metadata. The worker persists each input as:

- `accepted`;
- `restricted`;
- `missing`;
- `rejected`; or
- `unsupported`.

Completeness is calculated from declared required **artifacts/shards**, not the number of tests inside a report. A single report containing 500 test observations is still one received input. Missing, digest-mismatched, unsupported and restricted required artifacts cannot silently produce a reassuring complete run.

Schema `1.0` single-report bundles and one-report implicit ZIPs remain readable for compatibility.

### Evidence adapters

The versioned registry includes working foundations for:

- JUnit XML;
- Playwright JSON reporter output;
- `pytest-json-report`;
- REST Assured/JUnit plus sanitized exchange evidence;
- k6 `handleSummary` JSON;
- console UTF-8 text and JSONL;
- HAR and normalized network JSONL;
- PNG/JPEG metadata with pixel limits and restricted-original state;
- bounded Playwright trace metadata/indexing with restricted-original state;
- GitHub commit/workflow metadata with explicit trust provenance; and
- changed-file/base-head metadata with completeness warnings.

Support depth and known limits are documented in [`docs/input-compatibility.md`](docs/input-compatibility.md). Adapter presence is not represented as universal producer compatibility.

### Safety and analysis

- DTD/entity rejection; archive traversal/symlink/encryption/collision/nesting/compression controls.
- Terminal-control removal and redaction of declared secret/PII classes, including token fields and URL query values.
- Stable versioned failure fingerprints and idempotent analysis revisions keyed to effective evidence/history/validation input.
- Each normalized observation produces an immutable safe JSON derivative with a digest, redaction provenance, source map, execution ID and manifest-input ID.
- Analysis selects only the failure's execution evidence plus explicitly labeled shared/input diagnostics; ambiguous legacy evidence is not guessed into scope.
- A separate publication validator re-reads derivative bytes and independently checks authorization scope, digest, locator bounds, quotation accuracy, typed observation equality, semantic claim support and policy safety.
- Invalid or irrelevant citations are withheld; unsupported classifications safely degrade to `insufficient_evidence` and retain an audit result.
- Exactly five categories: `product_defect`, `test_defect`, `infrastructure_failure`, `known_flake`, and `insufficient_evidence`.
- Conservative policy that blocks unsupported flake/infrastructure reassurance when product-risk evidence conflicts or required scope is incomplete.
- Prior-only historical aggregation that collapses retries per run/browser cohort, preserves skipped/cancelled/unknown outcomes, exposes exact denominators and Wilson intervals, and never counts an absent test as a pass.
- Versioned known-flake safety policy requiring compatible same-browser/branch/environment/parallelism full-suite history, observed passes and failures, minimum support, a qualifying prior review decision, and no contradictory current-run product-risk signal.
- Traceable test-history API and dashboard with branch/browser/environment/scope/time-bucket breakdowns, sequences, recurrence intervals, calculation definitions, contributing execution IDs and explicit insufficient-data states.
- Immutable, project-scoped impact mapping snapshots with explicit test catalogues, coverage/ownership/history edges and bounded reverse dependencies.
- Deterministic change-impact recommendations that validate base/head provenance, support renamed/deleted paths, rank every selected test with inspectable reasons and retain explicit exclusions.
- Safety policy that forces full-suite execution for untrusted, incomplete, truncated, critical or unmapped comparisons; artifact bytes cannot self-elevate their own trust.
- Append-only attributed include/exclude overrides with optimistic revisions; mandatory critical tests and full-suite fallbacks cannot be weakened.
- Final-attempt test durations and bounded k6 summary statistics are persisted as normalized, evidence-linked performance observations with original/canonical units, producer provenance, workload and compatibility dimensions.
- Immutable project-scoped performance policies define tolerances, minimum support, maximum age, trust requirements, required dimensions and metric-direction overrides.
- Prior-only baseline snapshots reject cross-project/repository/workload/environment/producer/unit/statistic/run-scope mismatches, incomplete or untrusted runs, stale observations, future data and duplicate run contributions.
- Deterministic findings report `REGRESSION`, `IMPROVEMENT`, `WITHIN_TOLERANCE`, `INCONCLUSIVE`, `BASELINE_UNAVAILABLE` or `INCOMPATIBLE_BASELINE` with exact current/baseline evidence, run/sample counts, deltas, tolerances, confounders and next-measurement guidance. Exported percentiles are never averaged or presented as aggregate percentiles, and the engine never claims statistical significance from one summary pair.
- A two-stage deterministic clustering engine: bounded candidate generation followed by explainable multi-signal scoring.
- Conservative complete-link membership checks that prevent transitive A–B–C bridge merges and retain singleton outliers, mixed signals and uncertainty.
- Persisted cluster identities, representative failures, score components, matching/conflicting signals and append-only revision history.
- Human-reviewed cluster confirmation, split and merge decisions with optimistic revision checks; prior memberships are never overwritten.
- Append-only human review events with optimistic version checks.
- React/Vite dashboard with uploads, live ingestion status, cancellation/retry, run navigation, per-input completeness diagnostics, explainable impact selection/overrides, compatible performance baselines/findings, cluster inspection/correction, failure inspection, prior-only historical intelligence and evaluation results.
- Composite GitHub Action using the same durable ingestion and deterministic report path.
- Versioned 200-case synthetic corpus with group-preserving splits and explicit limitations.
- Separate 24-case/13-incident clustering fixture measuring pairwise precision/recall, false merges, false splits and adjusted Rand index.
- Separate 12-case/11-family impact fixture measuring defect-revealing and mandatory-critical recall, fallback correctness, selected proportion and deterministic repeatability.
- Separate 20-case performance fixture measuring regression recall, compatibility-selection accuracy, evidence linkage, future-data isolation, percentile anti-aggregation and deterministic repeatability.

## Verification for this checkpoint

```text
156 backend tests passed
85.26% branch-aware backend coverage (75% gate)
Python source, tests and evaluation harnesses compile successfully
SQLite migration upgrade/downgrade/re-upgrade passed through the performance-intelligence head
Impact benchmark: 12/12 status decisions correct, 1.000 defect-revealing and mandatory-critical recall
Performance benchmark: 20/20 status decisions correct, 1.000 regression recall and compatibility-selection accuracy, 0/5 dangerous false negatives
```

The frontend source was updated and strict TypeScript source checking completed with the available local compiler, but the isolated implementation container could not restore the locked npm dependency graph because registry DNS failed (`EAI_AGAIN`). The committed GitHub workflow remains the required evidence for locked dependency resolution, frontend unit/build checks, PostgreSQL migration integration, Chromium E2E, evaluation and Docker execution on the exact delivered SHA. Do not treat workflow source alone as a pass.

Synthetic benchmark results apply only to the committed public synthetic corpus; they are not deployment guarantees and do not satisfy the requirement for actual executed LedgerGuard cases.

## Start the stack

```bash
docker compose up --build
```

Open:

- Dashboard: `http://localhost:8080`
- API documentation: `http://localhost:8000/docs`

Use **Load synthetic demo** to create a clearly labeled project, then upload a supported standalone artifact or manifest `2.0` ZIP from the **Durable pipeline** panel. The dashboard polls the persisted ingestion and exposes the resulting run and its per-input diagnostics.

For Python development:

```bash
python -m pip install -e './backend[dev]'
make test
make evaluate
```

CLI examples:

```bash
failurelens doctor
failurelens ingest path/to/junit.xml --project my-project --external-id run-123 --run-scope full_suite --environment ci-linux --timezone America/Halifax
failurelens ingest path/to/changes.json --project my-project --external-id pr-42 --base-sha <base> --commit-sha <head> --comparison-trust authenticated_lookup --process
failurelens ingestion-status --ingestion <ingestion-id>
failurelens ingest path/to/failurelens-bundle.zip --project my-project --external-id run-124 --expected-inputs 3 --process
failurelens impact --project my-project --run <run-id> --mapping-snapshot <snapshot-id>
failurelens performance --run <run-id> --policy <performance-policy-id>
failurelens report --run <run-id> --format markdown
```

Raw API upload example:

```bash
curl --request POST \
  --header 'Content-Type: application/zip' \
  --data-binary @failurelens-bundle.zip \
  'http://localhost:8000/api/v1/projects/<project-id>/ingestions?external_id=run-123&filename=failurelens-bundle.zip&expected_inputs=3&run_scope=full_suite&comparison_trust=self_reported&environment=ci-linux&timezone=America%2FHalifax'
```

The response is `202 Accepted` with stable ingestion/job IDs and eventually a `run_id`. Query `GET /api/v1/ingestions/{ingestion_id}` or let the dashboard poll it. Inspect persisted scope with `GET /api/v1/runs/{run_id}/inputs`, generate an impact plan with `POST /api/v1/projects/{project_id}/impact-recommendations`, inspect run-scoped clusters with `GET /api/v1/runs/{run_id}/clusters`, and inspect cutoff-safe history for an execution with `GET /api/v1/tests/{execution_id}/history`, and create compatible performance findings with `POST /api/v1/runs/{run_id}/performance-comparisons`. Artifact-declared trust is retained only for audit; effective comparison trust comes from validated transport metadata.

## Manifest `2.0` example

```json
{
  "schema_version": "2.0",
  "inputs": [
    {
      "id": "test-results",
      "kind": "playwright-json",
      "path": "reports/playwright.json",
      "required": true
    },
    {
      "id": "browser-console",
      "kind": "console-jsonl",
      "path": "logs/console.jsonl",
      "required": false
    },
    {
      "id": "failure-trace",
      "kind": "playwright-trace",
      "path": "traces/failure.zip",
      "required": true
    }
  ]
}
```

## Repository map

```text
backend/src/failurelens/    API, storage, adapters, evidence, rules, clustering, history, impact, performance, jobs, CLI
backend/migrations/         Versioned relational schema
backend/tests/              Unit, adversarial, API and durable integration tests
evaluation/                 Corpus generator, labeled corpus, harness, reports
frontend/                   React/Vite dashboard, unit tests, Chromium E2E
integrations/github-action/ Reusable composite Action and report runner
.github/workflows/          PostgreSQL, evaluation, frontend, browser, Docker CI
docs/                       Architecture, security, compatibility, progress, requirements
```

## Safety model

All artifact bytes, filenames, manifest fields, logs, URLs, metadata and generated analysis are untrusted. Workers re-check size and SHA-256 before parsing. Unsafe XML/ZIP structures fail with explicit codes. Text observations are sanitized into immutable safe derivatives; the validator re-reads those bytes before publication. Screenshot and trace originals remain restricted and expose only bounded metadata/index records in this milestone.

The deterministic analyzer separates observations, inferences, hypotheses, missing evidence and investigation actions. A retry pass does not prove harmlessness. A timeout alone does not prove a flake. `known_flake` requires reviewed history with independent runs. Product-risk signals remain visible even when infrastructure symptoms also exist.

The system never approves releases, merges pull requests, deletes tests, suppresses product-risk flags or rewrites code.

Historical definitions and safety rules are documented in [`docs/history.md`](docs/history.md). Change-impact trust, mapping, fallback and override semantics are documented in [`docs/impact.md`](docs/impact.md). Compatible baseline, unit, percentile and uncertainty semantics are documented in [`docs/performance.md`](docs/performance.md).

## Evaluation truthfulness

The classification corpus manifest currently records 200 synthetic cases, 100 scenario families and **0 actual LedgerGuard executions**. The clustering fixture records 24 synthetic observations across 13 independently stored incident labels; its controlled result is 1.000 pairwise precision, 1.000 pairwise recall, 0 false merges, 0 false splits and 1.000 adjusted Rand index. The impact fixture records 12 synthetic cases across 11 scenario families and reports 1.000 defect-revealing-test recall, 1.000 mandatory-critical-test recall and correct focused/fallback status for every controlled case. The performance fixture records 20 synthetic compatibility/regression cases and reports 1.000 status accuracy, regression recall, compatibility-selection accuracy, evidence-citation validity and deterministic repeat agreement, with zero dangerous false negatives across five regression cases. All four datasets are agent-authored regression fixtures, not deployment guarantees, observed runtime-savings evidence or independently blinded studies. See [`evaluation/corpus/manifest.json`](evaluation/corpus/manifest.json), [`evaluation/corpus/clustering-manifest.json`](evaluation/corpus/clustering-manifest.json), [`evaluation/corpus/impact-manifest.json`](evaluation/corpus/impact-manifest.json), [`evaluation/corpus/performance-manifest.json`](evaluation/corpus/performance-manifest.json), and [`evaluation/reports/latest/performance-report.md`](evaluation/reports/latest/performance-report.md).

## Remaining M2 closure work

1. Generate and fixture-test every adapter from pinned real producers, including Java REST Assured, Playwright traces and screenshots.
2. Create immutable reviewed/masked screenshot derivatives and richer safe trace derivatives with image/trace-specific source maps and retention controls.
3. Add project-scoped authorization/isolation and authorized bounded artifact preview/download endpoints.
4. Expand claim predicates and validation metrics beyond the deterministic classification rules implemented here.
5. Complete M4 with separately modeled infrastructure-event correlation, then complete review roles/views, actual LedgerGuard corpus and live idempotent GitHub publication.

Factual progress is tracked in [`docs/PROGRESS.md`](docs/PROGRESS.md), with requirement status in [`docs/requirements-matrix.md`](docs/requirements-matrix.md).
