# FailureLens
## Evidence-Grounded Test Failure Triage and AI Evaluation

FailureLens is a self-hosted quality-intelligence platform that turns automated-test artifacts into evidence-linked failure investigations. Its mandatory analysis path is deterministic and CPU-only: no paid model API, cloud account, GPU, or runtime model download is required.

> **Current delivery status: M1 complete; M2 multi-artifact ingestion foundation implemented; full master specification remains incomplete.**
>
> This revision adds manifest-level input accounting, a versioned adapter registry, persisted per-input diagnostics, broader evidence formats, and a dashboard completeness view. Safe binary derivatives, producer-pinned integration fixtures, semantic claim validation, clustering, history/impact analysis, authorization, actual LedgerGuard evaluation cases, and live idempotent PR publication remain open.

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
- Stable versioned failure fingerprints and idempotent analysis revisions keyed to effective evidence/history input.
- Exactly five categories: `product_defect`, `test_defect`, `infrastructure_failure`, `known_flake`, and `insufficient_evidence`.
- Conservative policy that blocks unsupported flake/infrastructure reassurance when product-risk evidence conflicts or required scope is incomplete.
- Append-only human review events with optimistic version checks.
- React/Vite dashboard with uploads, live ingestion status, cancellation/retry, run navigation, per-input completeness diagnostics, failure inspection and evaluation results.
- Composite GitHub Action using the same durable ingestion and deterministic report path.
- Versioned 200-case synthetic corpus with group-preserving splits and explicit limitations.

## Verification for this checkpoint

```text
89 backend tests passed
86.61% branch-aware backend coverage (75% gate)
Python source and tests compile successfully
```

The frontend source was updated and manually audited, but the isolated implementation container did not contain the lockfile’s npm package tarballs, so `npm ci --offline` could not restore Vite. The committed GitHub workflow remains the required evidence for locked dependency resolution, frontend unit/build checks, PostgreSQL migration integration, Chromium E2E, evaluation and Docker execution on the exact delivered SHA. Do not treat workflow source alone as a pass.

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
failurelens ingest path/to/junit.xml --project my-project --external-id run-123
failurelens ingestion-status --ingestion <ingestion-id>
failurelens ingest path/to/failurelens-bundle.zip --project my-project --external-id run-124 --expected-inputs 3 --process
failurelens report --run <run-id> --format markdown
```

Raw API upload example:

```bash
curl --request POST \
  --header 'Content-Type: application/zip' \
  --data-binary @failurelens-bundle.zip \
  'http://localhost:8000/api/v1/projects/<project-id>/ingestions?external_id=run-123&filename=failurelens-bundle.zip&expected_inputs=3'
```

The response is `202 Accepted` with stable ingestion/job IDs and eventually a `run_id`. Query `GET /api/v1/ingestions/{ingestion_id}` or let the dashboard poll it. Inspect persisted scope with `GET /api/v1/runs/{run_id}/inputs`.

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
backend/src/failurelens/    API, storage, adapters, evidence, rules, jobs, CLI
backend/migrations/         Versioned relational schema
backend/tests/              Unit, adversarial, API and durable integration tests
evaluation/                 Corpus generator, labeled corpus, harness, reports
frontend/                   React/Vite dashboard, unit tests, Chromium E2E
integrations/github-action/ Reusable composite Action and report runner
.github/workflows/          PostgreSQL, evaluation, frontend, browser, Docker CI
docs/                       Architecture, security, compatibility, progress, requirements
```

## Safety model

All artifact bytes, filenames, manifest fields, logs, URLs, metadata and generated analysis are untrusted. Workers re-check size and SHA-256 before parsing. Unsafe XML/ZIP structures fail with explicit codes. Text evidence is sanitized; screenshot and trace originals remain restricted and expose only bounded metadata/index records in this milestone.

The deterministic analyzer separates observations, inferences, hypotheses, missing evidence and investigation actions. A retry pass does not prove harmlessness. A timeout alone does not prove a flake. `known_flake` requires reviewed history with independent runs. Product-risk signals remain visible even when infrastructure symptoms also exist.

The system never approves releases, merges pull requests, deletes tests, suppresses product-risk flags or rewrites code.

## Evaluation truthfulness

The corpus manifest currently records 200 synthetic cases, 100 scenario families and **0 actual LedgerGuard executions**. Labels are agent-reviewed rather than independently expert-adjudicated. See [`evaluation/corpus/manifest.json`](evaluation/corpus/manifest.json) and [`evaluation/reports/latest/report.md`](evaluation/reports/latest/report.md).

## Remaining M2 closure work

1. Generate and fixture-test every adapter from pinned real producers, including Java REST Assured, Playwright traces and screenshots.
2. Create immutable reviewed/masked screenshot derivatives and richer safe trace derivatives with source maps and retention controls.
3. Add publication-grade evidence validation that separately checks reference validity, quotation accuracy and semantic support.
4. Add project-scoped authorization/isolation and authorized artifact preview/download endpoints.
5. Then continue M3+: explainable cluster persistence/revisions, honest history rates, impact selection, performance baselines, complete review roles/views, actual LedgerGuard corpus and live idempotent GitHub publication.

Factual progress is tracked in [`docs/PROGRESS.md`](docs/PROGRESS.md), with requirement status in [`docs/requirements-matrix.md`](docs/requirements-matrix.md).
