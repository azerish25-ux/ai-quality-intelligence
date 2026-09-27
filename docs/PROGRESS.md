# FailureLens delivery ledger

## Repository facts

- Canonical repository: `azerish25-ux/ai-quality-intelligence`
- Default and working branch: `main`
- Original starting commit: `bdb8171d7afaf6ff3626ecb46c9317328ea12bb0`
- Durable-ingestion starting revision: `671b06f6fb5844e9d4257fe650a8702455eac38a`
- M2 development parent: exact source export of `3ba6cc6a4f6f3f452244e8b010212a0eed14b8ae`
- Companion repositories remain read-only inputs:
  - `azerish25-ux/transaction-reliability-lab`
  - `azerish25-ux/playwright-quality-platform`

## Milestones

| Milestone | Status | Evidence in this revision |
|---|---|---|
| M0 — preflight and delivery proof | PASS | Canonical repository/branch/head and exact source parent were verified. Remote publication and CI must still be reread for each delivered SHA. |
| M1 — executable vertical slice | PASS | Raw upload -> stored ingestion/job -> leased worker -> run/evidence/failure -> automatic deterministic analysis -> dashboard. Recovery and browser path exist. |
| M2 — full ingestion and safe evidence | PARTIAL | Manifest `2.0`, adapter registry, per-input persistence, honest required-input completeness, pytest/k6/console/HAR/network/REST/GitHub/change adapters, and restricted screenshot/trace indexes now exist. Producer-pinned fixtures, safe binary derivatives, source maps, semantic claim validation and authorized artifact serving remain open. |
| M3 — analytical core | PARTIAL | Versioned fingerprint, five categories, conservative rules, contradiction handling, evidence IDs, abstention, policy flags and idempotent analysis inputs exist. Explainable cluster persistence/scoring/revision history remains open. |
| M4 — history and impact | PARTIAL | Prior-only fingerprint count and reviewed-flake gate exist. Changed-file inputs are now retained, but rates/denominators, impact recommendations and performance baselines remain open. |
| M5 — review workflow and UI | PARTIAL | Append-only reviews, conflict version, upload/status workflow, per-input completeness panel, overview/runs/failure/evaluation views and Chromium journey source exist. Roles, complete views and broader accessibility/browser coverage remain open. |
| M6 — corpus and evaluation | PARTIAL | 200 synthetic cases, grouped splits, executable harness, safety metrics and report exist. Actual LedgerGuard executions remain 0. |
| M7 — optional model boundary | NOT RUN | Deterministic mode is functional; provider adapter is not implemented. |
| M8 — GitHub integration | PARTIAL | Composite Action uses durable ingestion and emits ingestion/run/report outputs. Live idempotent PR publication and stale-head reconciliation remain open. |
| M9 — hardening and packaging | PARTIAL | Docker/Compose, nonroot backend, CI, storage/archive/image bounds, recovery tests, browser E2E source and migration chain exist. Retention, backup/restore, telemetry export, load benchmarks and broader isolation evidence remain open. |
| M10 — final audit and source delivery | PARTIAL | M1 plus the M2 foundation are implemented; complete master-spec acceptance remains open. |

## Checks executed for the M2 foundation

- `PYTHONPATH=src pytest -q`: **89 passed**.
- `PYTHONPATH=src pytest --cov=failurelens --cov-branch --cov-fail-under=75 -q`: **89 passed, 86.61% total coverage**.
- `python -m compileall -q src tests`: **passed**.
- Manifest/adversarial coverage includes malformed schemas, duplicate IDs, missing paths, digest mismatch, unsupported/rejected inputs, unsafe archives, redaction canaries, terminal controls, HAR/network sanitization, image bounds and restricted traces.
- `npm ci --offline`: **not run successfully in the isolated implementation container** because the lockfile dependency tarballs (including Vite) were absent. Locked npm test/build, PostgreSQL migration, Chromium E2E, evaluation and Docker outcomes must be taken only from the exact delivered GitHub workflow run.

## M2 failure perspectives reviewed

- **Functional correctness:** observations are no longer counted as artifacts; one report remains one input regardless of test count.
- **Missing evidence:** declared required paths persist as `missing`; present but unsafe/invalid inputs persist as `restricted`, `rejected` or `unsupported`; run status becomes partial.
- **Dangerous reassurance:** incomplete required scope is passed to deterministic analysis and blocks unsupported reassurance.
- **Data leakage:** text/query evidence is redacted; terminal controls are removed; screenshot/trace originals stay restricted.
- **Authorization:** uploaded GitHub metadata carries trust provenance but never authorizes publication; full project-scoped users/roles remain open.
- **Reproducibility:** source/input digests, manifest version, adapter-registry version, parser versions, policy version and analysis input digest are persisted.
- **Usability:** dashboard shows expected/received counts and every input’s state, parser, size, path and warning.
- **Recovery:** valid sibling artifacts survive a missing/rejected input; durable replay/idempotency remains tested.
- **Delivery truthfulness:** local backend verification is recorded separately from npm/CI lanes; no workflow is counted as passing until the candidate SHA is inspected remotely.
