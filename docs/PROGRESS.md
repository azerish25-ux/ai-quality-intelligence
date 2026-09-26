# FailureLens delivery ledger

## Repository facts

- Canonical repository: `azerish25-ux/ai-quality-intelligence`
- Default and working branch: `main`
- Original starting commit: `bdb8171d7afaf6ff3626ecb46c9317328ea12bb0`
- Pre-implementation checkpoint: `b548f3e3819131e743dc8744d80937fa9a3bdd51`
- Authorized write route: connected GitHub Git Data API, non-force update of `main`
- Companion repositories inspected read-only:
  - `azerish25-ux/transaction-reliability-lab`
  - `azerish25-ux/playwright-quality-platform`

## Milestones

| Milestone | Status | Evidence in this revision |
|---|---|---|
| M0 — preflight and delivery proof | PASS | Canonical remote/branch/head verified; previous remote checkpoint exists; this revision uses the same authorized write path. |
| M1 — executable vertical slice | PASS | API/CLI ingestion -> relational persistence -> evidence -> deterministic analysis -> React dashboard source; API vertical-slice test passes. |
| M2 — full ingestion and safe evidence | PARTIAL | JUnit, Playwright JSON, normalized API, path safety, XML entity rejection, and text redaction exist. Remaining required adapters and binary controls are open. |
| M3 — analytical core | PARTIAL | Versioned fingerprint, five categories, conservative rules, contradiction handling, evidence IDs, abstention, and policy flags exist. Full clustering system is open. |
| M4 — history and impact | PARTIAL | Prior-only fingerprint count and reviewed-flake gate exist. Complete history analytics, impact selection, and performance baselines are open. |
| M5 — review workflow and UI | PARTIAL | Append-only review events, conflict version, overview/runs/failure workspace/evaluation UI exist. Roles, all views, and browser E2E are open. |
| M6 — corpus and evaluation | PARTIAL | 200 synthetic cases, 100 families, grouped splits, executable harness, predictions, confusion matrix, safety metrics, and report. Actual LedgerGuard executions: 0, therefore mandatory provenance remains BLOCKED. |
| M7 — optional model boundary | NOT RUN | Deterministic mode works; provider adapter is not implemented. |
| M8 — GitHub integration | PARTIAL | Composite Action and sanitized report runner exist. Live PR comment publication and stale-SHA reconciliation are not implemented or verified. |
| M9 — hardening and packaging | PARTIAL | Docker/Compose, nonroot backend, CSP, CI source, security tests, and migration test exist. Recovery, retention, telemetry export, browser E2E, and benchmark suite are open. |
| M10 — final audit and source delivery | PARTIAL | Local gates passed and this revision is delivered to the canonical `main` branch; complete master-spec acceptance remains open. |

## Checks executed in the delivery environment

- `PYTHONPATH=src pytest -q`: 19 passed.
- `pytest --cov=failurelens --cov-branch`: 85.55% total measured coverage; 75% gate passed.
- Synthetic test evaluation: 100 cases, 50 families, five categories represented, 0/40 dangerous dismissals, macro F1 1.000.
- Frontend build: NOT RUN locally because the execution container cannot resolve external npm registry DNS; CI contains the build job.
- PostgreSQL integration: source and Compose/CI service exist; local Docker is unavailable in the delivery environment.

## Truthfulness rule

A source file or workflow definition is not counted as executed evidence. Real companion-project provenance, live GitHub publication, browser execution, and CI status remain distinct gates and are not inferred from implementation presence.
