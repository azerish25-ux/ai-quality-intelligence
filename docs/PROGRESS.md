# FailureLens delivery ledger

## Repository facts

- Canonical repository: `azerish25-ux/ai-quality-intelligence`
- Default and working branch: `main`
- Original starting commit: `bdb8171d7afaf6ff3626ecb46c9317328ea12bb0`
- Durable-ingestion starting revision: `671b06f6fb5844e9d4257fe650a8702455eac38a`
- Authorized write route: connected GitHub Git Data API, non-force update of `main`
- Companion repositories remain read-only inputs:
  - `azerish25-ux/transaction-reliability-lab`
  - `azerish25-ux/playwright-quality-platform`

## Milestones

| Milestone | Status | Evidence in this revision |
|---|---|---|
| M0 — preflight and delivery proof | PASS | Canonical remote/branch/head verified; publication uses a fast-forward Git Data API commit and exact-revision CI inspection. |
| M1 — executable vertical slice | PASS | Raw JUnit/Playwright/ZIP upload -> persisted ingestion/job -> leased worker -> restricted artifact + relational run/evidence/failure -> automatic deterministic analysis -> dashboard status/result. Backend integration and Chromium journey are in CI. |
| M2 — full ingestion and safe evidence | PARTIAL | Safe streamed storage, digest revalidation, ZIP controls, JUnit, Playwright JSON, normalized API, redaction, and precise locators exist. Remaining mandatory adapters and binary safe derivatives are open. |
| M3 — analytical core | PARTIAL | Versioned fingerprint, five categories, conservative rules, contradiction handling, evidence IDs, abstention, policy flags, and idempotent analysis inputs exist. Explainable cluster persistence/scoring/revision history remains open. |
| M4 — history and impact | PARTIAL | Prior-only fingerprint count and reviewed-flake gate exist. Complete rates/denominators, impact selection, and performance baselines remain open. |
| M5 — review workflow and UI | PARTIAL | Append-only reviews, conflict version, upload/status workflow, overview/runs/failure/evaluation views, and Chromium journey exist. Roles, complete views, and broader accessibility/browser coverage remain open. |
| M6 — corpus and evaluation | PARTIAL | 200 synthetic cases, grouped splits, executable harness, safety metrics, and report exist. Actual LedgerGuard executions remain 0. |
| M7 — optional model boundary | NOT RUN | Deterministic mode is complete for M1; provider adapter is not implemented. |
| M8 — GitHub integration | PARTIAL | Composite Action now uses durable ingestion and emits ingestion/run/report outputs. Live idempotent PR publication and stale-head reconciliation remain open. |
| M9 — hardening and packaging | PARTIAL | Docker/Compose, nonroot backend, CI, storage bounds, recovery tests, browser E2E source, and migration chain exist. Retention, backup/restore, telemetry export, load benchmarks, and broader adversarial coverage remain open. |
| M10 — final audit and source delivery | PARTIAL | This milestone delivers M1 to `main`; complete master-spec acceptance remains open. |

## Checks executed before publication

- `PYTHONPATH=src pytest -q`: 29 passed.
- `pytest --cov=failurelens --cov-branch --cov-fail-under=75`: 29 passed, 78.72% measured coverage.
- `python -m compileall`: passed.
- `npm test` and `npm run build`: passed with the committed lockfile on Node 22.
- PostgreSQL migration/integration, locked npm test/build, Chromium E2E, evaluation, and Docker checks are evaluated by the committed GitHub workflow against each delivered SHA.

## M1 failure perspectives reviewed

- **Functional correctness:** actual report bytes are parsed by the worker; analyses appear automatically.
- **Missing evidence:** expected/received counts produce explicit partial state rather than a clean-run implication.
- **Dangerous reassurance:** existing contradiction/abstention policy remains active in automatic analysis.
- **Data leakage:** source artifacts are restricted; displayed excerpts pass through redaction.
- **Authorization:** ingestion write token behavior remains; complete project-scoped users/roles are M5/M9 work.
- **Reproducibility:** source digest, parser version, policy version, manifest digest, and analysis input digest are persisted.
- **Usability:** dashboard exposes queue state, safe error diagnostics, retry/cancel, and completed-run navigation.
- **Recovery:** expired leases, crash-after-publication replay, malformed permanent failures, duplicate upload, and cancellation resurrection are tested.
- **Delivery truthfulness:** workflow source is not counted as a pass until its exact revision run is inspected.
