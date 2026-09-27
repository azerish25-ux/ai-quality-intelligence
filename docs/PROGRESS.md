# FailureLens delivery ledger

## Repository facts

- Canonical repository: `azerish25-ux/ai-quality-intelligence`
- Default and working branch: `main`
- Original starting commit: `bdb8171d7afaf6ff3626ecb46c9317328ea12bb0`
- Durable-ingestion starting revision: `671b06f6fb5844e9d4257fe650a8702455eac38a`
- M2 foundation parent: exact source export of `3ba6cc6a4f6f3f452244e8b010212a0eed14b8ae`
- Evidence-integrity development parent: exact source export of `59539ba4e4252eb1a41789fa6fab26b4c7f05c6b`
- Companion repositories remain read-only inputs:
  - `azerish25-ux/transaction-reliability-lab`
  - `azerish25-ux/playwright-quality-platform`

## Milestones

| Milestone | Status | Evidence in this revision |
|---|---|---|
| M0 — preflight and delivery proof | PASS | Canonical repository/branch/head and exact source parent were verified. Remote publication and CI must still be reread for each delivered SHA. |
| M1 — executable vertical slice | PASS | Raw upload -> stored ingestion/job -> leased worker -> run/evidence/failure -> automatic deterministic analysis -> dashboard. Recovery and browser path exist. |
| M2 — full ingestion and safe evidence | PARTIAL | Manifest `2.0`, adapter registry, honest completeness, execution/input-scoped evidence, immutable safe text derivatives, source maps, independent digest/locator/quotation/observation checks, semantic classification-claim validation, safe degradation, and restricted screenshot/trace indexes exist. Producer-pinned fixtures, safe binary derivatives, broader predicates, project-scoped authorization and controlled artifact serving remain open. |
| M3 — analytical core | PARTIAL | Versioned fingerprint, five categories, conservative rules, contradiction handling, execution-scoped evidence IDs, independently validated claims, abstention, policy flags and idempotent analysis inputs exist. Explainable cluster persistence/scoring/revision history remains open. |
| M4 — history and impact | PARTIAL | Prior-only fingerprint count and reviewed-flake gate exist. Changed-file inputs are now retained, but rates/denominators, impact recommendations and performance baselines remain open. |
| M5 — review workflow and UI | PARTIAL | Append-only reviews, conflict version, upload/status workflow, per-input completeness panel, overview/runs/failure/evaluation views and Chromium journey source exist. Roles, complete views and broader accessibility/browser coverage remain open. |
| M6 — corpus and evaluation | PARTIAL | 200 synthetic cases, grouped splits, executable harness, safety metrics and report exist. Actual LedgerGuard executions remain 0. |
| M7 — optional model boundary | NOT RUN | Deterministic mode is functional; provider adapter is not implemented. |
| M8 — GitHub integration | PARTIAL | Composite Action uses durable ingestion and emits ingestion/run/report outputs. Live idempotent PR publication and stale-head reconciliation remain open. |
| M9 — hardening and packaging | PARTIAL | Docker/Compose, nonroot backend, CI, storage/archive/image bounds, recovery tests, browser E2E source and migration chain exist. Retention, backup/restore, telemetry export, load benchmarks and broader isolation evidence remain open. |
| M10 — final audit and source delivery | PARTIAL | M1 plus the M2 foundation are implemented; complete master-spec acceptance remains open. |

## Checks executed for the evidence-integrity checkpoint

- `PYTHONPATH=src pytest -q`: **100 passed**.
- `PYTHONPATH=src pytest --cov=failurelens --cov-branch --cov-fail-under=75 -q`: **100 passed, 87.38% total coverage**.
- `python -m compileall -q src tests`: **passed**.
- Manifest/adversarial coverage includes malformed schemas, duplicate IDs, missing paths, digest mismatch, unsupported/rejected inputs, unsafe archives, redaction canaries, terminal controls, HAR/network sanitization, image bounds, restricted traces, cross-failure evidence isolation, derivative tampering and semantically irrelevant citations.
- SQLite Alembic empty-database upgrade, downgrade to `a91f2c7d4e10`, and re-upgrade: **passed**.
- Locked npm test/build could not run locally because dependency tarballs were absent and package-network DNS was unavailable. PostgreSQL migration, frontend, Chromium, evaluation and Docker results must be taken from the exact delivered GitHub workflow run.

## M2 failure perspectives reviewed

- **Functional correctness:** observations are no longer counted as artifacts; one report remains one input regardless of test count. Evidence from one failed execution cannot enter another failure investigation.
- **Missing evidence:** declared required paths persist as `missing`; present but unsafe/invalid inputs persist as `restricted`, `rejected` or `unsupported`; rejected/tampered derivatives force explicit missing validated evidence and abstention.
- **Dangerous reassurance:** incomplete required scope blocks unsupported reassurance; invalid, modified or semantically irrelevant citations cannot retain a non-abstaining published category.
- **Data leakage:** text/query evidence is redacted into immutable safe derivatives; raw storage paths are not returned by the evidence API; screenshot/trace originals stay restricted.
- **Authorization:** uploaded GitHub metadata carries trust provenance but never authorizes publication; full project-scoped users/roles remain open.
- **Reproducibility:** source/input/derivative digests, manifest and adapter versions, parser/extractor/redaction/validation versions, evidence scope and analysis input digest are persisted.
- **Usability:** dashboard shows expected/received counts and every input’s state plus accepted/rejected evidence validation counts and publication status.
- **Recovery:** valid sibling artifacts survive a missing/rejected input; durable replay/idempotency remains tested.
- **Delivery truthfulness:** local backend verification is recorded separately from npm/CI lanes; no workflow is counted as passing until the candidate SHA is inspected remotely.
