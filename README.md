# FailureLens
## Evidence-Grounded Test Failure Triage and AI Evaluation

FailureLens is a self-hosted quality-intelligence platform for turning automated-test artifacts into evidence-linked failure investigations. The mandatory analysis path is deterministic and CPU-only: no paid model API, cloud account, GPU, or runtime model download is required.

> **Current delivery status: executable vertical slice, not the complete master specification.**
> This revision implements the core run/evidence/failure/analysis workflow, PostgreSQL schema and migrations, JUnit and Playwright JSON ingestion, safe text redaction, durable job primitives, human review events, an API-backed React dashboard, a reusable GitHub Action, and a 200-case synthetic evaluation corpus. Real LedgerGuard execution provenance, every required artifact adapter, browser E2E, live GitHub comment publication, full authorization/isolation, and several hardening milestones remain open. The repository records these gaps explicitly rather than presenting scaffolding as completion.

## What works in this revision

- FastAPI API with typed OpenAPI schemas and health/readiness endpoints.
- SQLAlchemy relational model for projects, runs, test executions, artifacts, evidence, failures, analyses, reviews, and leased jobs.
- Alembic migration from an empty database.
- Idempotent normalized-run ingestion with pass/fail/skip/cancel distinctions.
- Real JUnit XML and Playwright JSON parser paths used by the CLI.
- DTD/entity rejection, archive-path validation, terminal-control removal, and redaction of declared secret/PII classes.
- Stable, versioned failure fingerprints that preserve important distinctions such as HTTP status.
- Exactly five primary categories: `product_defect`, `test_defect`, `infrastructure_failure`, `known_flake`, and `insufficient_evidence`.
- Conservative deterministic policy that blocks unsupported flake/infrastructure reassurance when product-risk evidence conflicts.
- Explicit heuristic-score semantics; heuristic values are never described as calibrated probabilities.
- Append-only review events with optimistic version checks.
- Markdown report rendering with scope completeness and advisory—not approval—language.
- React/Vite dashboard for overview, run selection, failure inspection, persisted analysis, evidence completeness, and evaluation results.
- Versioned generator for a 200-case synthetic corpus with 100 scenario families and group-preserving 50/25/25 test/calibration/development family splits.
- Executed frozen-test report containing 100 cases and all five categories.

## Verified local results

The implementation was verified in the delivery environment with Python 3.13:

```text
19 backend/evaluation tests passed
85.55% measured backend branch-aware coverage
Alembic upgrade from an empty SQLite verification database passed
Synthetic frozen test split: 100 cases / 50 families
Dangerous dismissal: 0/40 product-defect cases
Product-defect recall: 1.000
Macro F1: 1.000
Forbidden published claims: 0
Sensitive-canary leaks: 0
```

These benchmark results apply only to the committed public synthetic corpus. They are not deployment guarantees and do not satisfy the requirement for actual executed LedgerGuard cases.

## Start the stack

Docker is the primary application path:

```bash
docker compose up --build
```

Then open:

- Dashboard: `http://localhost:8080`
- API documentation: `http://localhost:8080/api/docs` is not proxied in this revision; use `http://localhost:8000/docs` when running the API directly, or add a local port mapping for the API.

The dashboard includes **Load synthetic demo**, which persists clearly labeled demonstration data and exercises ingestion, classification, and evidence views.

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
failurelens analyze --run <run-id>
failurelens report --run <run-id> --format markdown
```

## Repository map

```text
backend/src/failurelens/    API, domain model, ingestion, evidence, rules, jobs, CLI
backend/migrations/         Versioned relational schema
evaluation/                 Corpus generator, labeled corpus, harness, reports
frontend/                   React/Vite engineering dashboard
integrations/github-action/ Reusable composite Action and report runner
.github/workflows/          CI for backend, evaluation, frontend, and Docker model
docs/                       Architecture, security, compatibility, progress, specification
```

## Safety model

FailureLens treats artifact text, filenames, metadata, logs, and generated analysis as untrusted. Its deterministic analyzer separates observations, inferences, hypotheses, missing evidence, and investigation actions. A retry pass does not prove harmlessness. A timeout alone does not prove a flake. `known_flake` requires reviewed history with independent runs. Product-risk signals are preserved even when infrastructure symptoms also exist.

The system never approves releases, merges pull requests, deletes tests, quarantines failures, suppresses product-risk flags, or rewrites code.

## Evaluation truthfulness

The corpus manifest records:

- 200 synthetic cases.
- 80 product defects.
- 30 test defects.
- 30 infrastructure/environment failures.
- 30 reviewed-history known flakes.
- 30 insufficient-evidence cases.
- 100 scenario families.
- 0 actual LedgerGuard executions.
- Agent-reviewed labels, not independent expert adjudication.

See [`evaluation/corpus/manifest.json`](evaluation/corpus/manifest.json), the reproducible generator, and [`evaluation/reports/latest/report.md`](evaluation/reports/latest/report.md). The generated case JSONL and per-case predictions are intentionally reproducible build outputs rather than permanent Git payloads.

## Current limitations

The master project contract remains larger than this revision. Highest-priority gaps are:

1. Execute and ingest at least 60 controlled LedgerGuard cases across 15 real root-cause families.
2. Complete HAR, k6, pytest-json-report, REST Assured evidence, screenshot, trace, console JSONL, commit metadata, and changed-file adapters with real producer fixtures.
3. Implement project-scoped user/session authorization, ingestion-token management, restricted-original artifact storage, retention, backup/restore, and cross-project isolation tests.
4. Complete clustering revision history, historical rate analysis, change-impact selection, performance baselines, and all required dashboard views.
5. Add Playwright browser E2E, real PostgreSQL concurrency/recovery suites, live GitHub publication verification, and hardened fork-PR publication.
6. Commit an npm lockfile after an environment with registry access resolves the dashboard dependencies; the current execution container could not resolve external package registries.

The supplied master contract is summarized by [`docs/requirements-matrix.md`](docs/requirements-matrix.md), and factual progress is tracked in [`docs/PROGRESS.md`](docs/PROGRESS.md).
