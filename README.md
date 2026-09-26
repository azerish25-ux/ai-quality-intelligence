# FailureLens
## Evidence-Grounded Test Failure Triage and AI Evaluation

FailureLens is a self-hosted quality-intelligence platform for turning automated-test artifacts into evidence-linked failure investigations. The mandatory analysis path is deterministic and CPU-only: no paid model API, cloud account, GPU, or runtime model download is required.

> **Current delivery status: durable executable vertical slice, not the complete master specification.**
> This revision closes the operational M1 path: an actual JUnit XML, Playwright JSON, or bounded FailureLens ZIP upload is persisted as a durable ingestion, claimed by a leased database worker, normalized into runs/evidence/failures, automatically analyzed, and surfaced in the React dashboard. The larger ingestion, clustering, history, impact, corpus, authorization, and GitHub-publication milestones remain open and are recorded explicitly.

## What works in this revision

- FastAPI API with typed OpenAPI schemas and separate liveness/readiness endpoints.
- SQLAlchemy/Alembic relational model for projects, durable ingestions, runs, test executions, artifacts, evidence, failures, analyses, reviews, and leased jobs.
- Raw streamed uploads with content-addressed restricted storage, digest/size revalidation, bounded files, and safe filenames.
- Durable ingestion states: `queued`, `running`, `succeeded`, `partial`, `failed`, `cancelled`, and `dead_lettered`.
- PostgreSQL job claiming with leases, expired-lease recovery, bounded retry, permanent-input failure handling, cancellation safety, and idempotent replay.
- Automatic deterministic analysis after parsing; the normal path does not require a second API request or dashboard button.
- JUnit XML and Playwright JSON parsing through raw files or a schema-versioned/bounded ZIP bundle.
- DTD/entity rejection, archive traversal/symlink/encryption/collision/nesting/compression controls, terminal-control removal, and redaction of declared secret/PII classes.
- Stable versioned failure fingerprints and idempotent analysis revisions keyed to the effective evidence/history input.
- Exactly five primary categories: `product_defect`, `test_defect`, `infrastructure_failure`, `known_flake`, and `insufficient_evidence`.
- Conservative deterministic policy that blocks unsupported flake/infrastructure reassurance when product-risk evidence conflicts.
- Append-only human review events with optimistic version checks.
- React/Vite dashboard with upload, live ingestion status, diagnostics, cancellation/retry, run navigation, failure inspection, and evaluation results.
- Composite GitHub Action that runs the same durable ingestion and deterministic report path.
- CI jobs for PostgreSQL migrations/tests, deterministic evaluation, frontend tests/build, Chromium upload-to-analysis E2E, and Docker configuration/images.
- Versioned generator for a 200-case synthetic corpus with 100 scenario families and group-preserving splits.

## Verified in the implementation environment

```text
27 backend tests passed
79.63% branch-aware backend coverage (75% gate)
Python bytecode compilation passed
Dashboard TypeScript strict check passed against the current source
```

The committed GitHub workflow is the authoritative evidence for PostgreSQL migration, npm dependency resolution, frontend build, Chromium E2E, evaluation, and Docker execution for a delivered revision. Synthetic benchmark results apply only to the committed public synthetic corpus; they are not deployment guarantees and do not satisfy the requirement for actual executed LedgerGuard cases.

## Start the stack

```bash
docker compose up --build
```

Open:

- Dashboard: `http://localhost:8080`
- API documentation: `http://localhost:8000/docs`

Use **Load synthetic demo** to create a clearly labeled project, then upload a real JUnit XML, Playwright JSON, or FailureLens ZIP report from the **Durable pipeline** panel. The dashboard polls the persisted ingestion and opens its completed run automatically.

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
failurelens ingest path/to/playwright-report.json --project my-project --external-id run-124 --process
failurelens report --run <run-id> --format markdown
```

Raw API upload example:

```bash
curl --request POST \
  --header 'Content-Type: application/xml' \
  --data-binary @junit.xml \
  'http://localhost:8000/api/v1/projects/<project-id>/ingestions?external_id=run-123&filename=junit.xml&expected_inputs=42'
```

The response is `202 Accepted` with a stable `ingestion_id`, `job_id`, state, and eventually a `run_id`. Query `GET /api/v1/ingestions/{ingestion_id}` or let the dashboard poll it.

## Repository map

```text
backend/src/failurelens/    API, storage, ingestion, evidence, rules, jobs, CLI
backend/migrations/         Versioned relational schema
evaluation/                 Corpus generator, labeled corpus, harness, reports
frontend/                   React/Vite dashboard, unit tests, Chromium E2E
integrations/github-action/ Reusable composite Action and report runner
.github/workflows/          PostgreSQL, evaluation, frontend, browser, Docker CI
docs/                       Architecture, security, compatibility, progress, requirements
```

## Safety model

All artifact bytes, filenames, report fields, logs, metadata, and generated analysis are untrusted. Uploads are stored under content-addressed project paths with restrictive permissions. Workers re-check size and SHA-256 before parsing. Unsafe XML and ZIP structures fail permanently with inspectable error codes instead of entering retry loops.

The deterministic analyzer separates observations, inferences, hypotheses, missing evidence, and investigation actions. A retry pass does not prove harmlessness. A timeout alone does not prove a flake. `known_flake` requires reviewed history with independent runs. Product-risk signals remain visible even when infrastructure symptoms also exist.

The system never approves releases, merges pull requests, deletes tests, suppresses product-risk flags, or rewrites code.

## Evaluation truthfulness

The corpus manifest currently records 200 synthetic cases, 100 scenario families, and **0 actual LedgerGuard executions**. Labels are agent-reviewed rather than independently expert-adjudicated. See [`evaluation/corpus/manifest.json`](evaluation/corpus/manifest.json) and [`evaluation/reports/latest/report.md`](evaluation/reports/latest/report.md).

## Current limitations and next milestone

The immediate next milestone is **M2 — full ingestion and safe evidence**:

1. Add real producer-pinned adapters and fixtures for pytest JSON, REST Assured evidence, k6 summaries, console JSONL, HAR/network JSONL, screenshots, Playwright traces, authenticated GitHub metadata, and changed-file lists.
2. Add safe derivatives/review-and-mask for binary artifacts, retention and cleanup policy, and stronger project isolation/authorization.
3. Complete semantic citation validation and attachment correlation across bundle entries.
4. Continue M3+ work: explainable cluster persistence/revisions, history rates, impact selection, performance baselines, complete review roles/views, actual LedgerGuard corpus, and live idempotent GitHub publication.

Factual progress is tracked in [`docs/PROGRESS.md`](docs/PROGRESS.md), with requirement-level status in [`docs/requirements-matrix.md`](docs/requirements-matrix.md).
