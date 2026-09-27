# FailureLens delivery ledger

## Repository facts

- Canonical repository: `azerish25-ux/ai-quality-intelligence`
- Default and working branch: `main`
- Original starting commit: `bdb8171d7afaf6ff3626ecb46c9317328ea12bb0`
- Durable-ingestion starting revision: `671b06f6fb5844e9d4257fe650a8702455eac38a`
- M2 foundation parent: exact source export of `3ba6cc6a4f6f3f452244e8b010212a0eed14b8ae`
- Evidence-integrity development parent: exact source export of `59539ba4e4252eb1a41789fa6fab26b4c7f05c6b`
- Explainable-clustering development parent: exact source export of `5ea816f94c22d61a269b19298da38617947d1d77`
- Historical-intelligence development parent: exact source export of `0329b7c0f5eaee4f657e7daa29a7b88aed3b0bdc`
- Change-impact development parent: exact source export of `48335b42c2da5b74bee0ce02aea471b987e5d416`
- Companion repositories remain read-only inputs:
  - `azerish25-ux/transaction-reliability-lab`
  - `azerish25-ux/playwright-quality-platform`

## Milestones

| Milestone | Status | Evidence in this revision |
|---|---|---|
| M0 — preflight and delivery proof | PASS | Canonical repository/branch/head and exact source parent were verified. Remote publication and CI must still be reread for each delivered SHA. |
| M1 — executable vertical slice | PASS | Raw upload -> stored ingestion/job -> leased worker -> run/evidence/failure -> automatic deterministic analysis -> dashboard. Recovery and browser path exist. |
| M2 — full ingestion and safe evidence | PARTIAL | Manifest `2.0`, adapter registry, honest completeness, execution/input-scoped evidence, immutable safe text derivatives, source maps, independent digest/locator/quotation/observation checks, semantic classification-claim validation, safe degradation, and restricted screenshot/trace indexes exist. Producer-pinned fixtures, safe binary derivatives, broader predicates, project-scoped authorization and controlled artifact serving remain open. |
| M3 — analytical core | PASS | Versioned strict fingerprints plus loose readable clustering features, bounded candidate generation, explainable multi-signal scoring, hard conflict preservation, complete-link bridge prevention, deterministic cluster identities, append-only membership revisions, reviewed confirm/split/merge corrections, conservative rules, contradiction handling, confidence semantics and safe abstention all have executable coverage. |
| M4 — history and impact | PARTIAL | Prior-only exact-test history and deterministic change-impact recommendations are implemented. Impact uses immutable mapping snapshots, validated base/head provenance, renamed/deleted path handling, bounded reverse dependencies, mandatory critical tests, conservative full-suite fallbacks, ranked explanations and append-only optimistic overrides through the API/CLI/dashboard. Separately modeled infrastructure-event correlation and compatible performance baselines remain open. |
| M5 — review workflow and UI | PARTIAL | Append-only analysis reviews, cluster decisions and impact include/exclude overrides exist with optimistic conflict versions. Upload/status, per-input completeness, clustering, history, impact, overview/runs/failure/evaluation views and Chromium journey source exist. Roles, complete audit/settings views and broader accessibility/browser coverage remain open. |
| M6 — corpus and evaluation | PARTIAL | 200 synthetic classification cases, a 24-case/13-label clustering fixture and a 12-case/11-family deterministic impact fixture have executable harnesses and committed reports. Actual LedgerGuard executions remain 0, and the impact runtime figures are estimates rather than measured savings. |
| M7 — optional model boundary | NOT RUN | Deterministic mode is functional; provider adapter is not implemented. |
| M8 — GitHub integration | PARTIAL | Composite Action uses durable ingestion, carries repository/base/head/run-scope/comparison-trust metadata through safe argument arrays and emits ingestion/run/report outputs. Authenticated comparison lookup, live idempotent PR publication and stale-head reconciliation remain open. |
| M9 — hardening and packaging | PARTIAL | Docker/Compose, nonroot backend, CI, storage/archive/image bounds, recovery tests, browser E2E source and migration chain exist. Retention, backup/restore, telemetry export, load benchmarks and broader isolation evidence remain open. |
| M10 — final audit and source delivery | PARTIAL | M1 and M3 plus the M2 safety foundation and the history/impact portions of M4 are implemented; complete master-spec acceptance remains open. |

## Checks executed for the explainable-impact checkpoint

- `PYTHONPATH=src pytest -q`: **148 passed**.
- `PYTHONPATH=src pytest --cov=failurelens --cov-branch --cov-fail-under=75 -q`: **148 passed, 88.00% total branch-aware coverage**.
- `python -m compileall -q src tests`: **passed**.
- Impact coverage includes focused direct mappings, renamed/deleted paths, bounded reverse-dependency traversal with cycles, immutable mapping versions, project isolation, mandatory critical-test preservation, untrusted/incomplete/truncated/unmapped full-suite fallbacks, base/head mismatch rejection, deterministic replay, append-only overrides, stale-revision rejection and artifact self-trust prevention.
- The controlled impact fixture contains **12 synthetic cases / 11 scenario families** and reports defect-revealing-test recall **1.000**, mandatory-critical-test recall **1.000**, expected safety-status accuracy **1.000**, deterministic-repeat agreement **1.000**, **7** focused-subset cases and **5** full-suite fallback cases. It remains synthetic and agent-authored; runtime values are estimates, not measured savings.
- The frozen clustering fixture remains **24 cases / 13 evaluation-only incident labels** with pairwise precision **1.000**, pairwise recall **1.000**, **0** false merges, **0** false splits and adjusted Rand index **1.000**.
- SQLite Alembic empty-database upgrade, downgrade to the previous head `e4b7c2d9a510`, and re-upgrade: **passed**.
- `bash -n integrations/github-action/run.sh`: **passed**.
- Locked npm restore/test/build could not be completed locally because package-registry access stalled in the isolated environment. PostgreSQL migration, frontend unit/build, Chromium, evaluation and Docker results must be taken from the exact delivered GitHub workflow run rather than inferred from workflow source.

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

## M3 clustering failure perspectives reviewed

- **Functional correctness:** exact fingerprinting is distinct from loose similarity; current cluster membership is revision-scoped and deterministic.
- **False merge safety:** authorization/server status conflicts, different selectors behind generic timeout text and assertion direction/negation are hard boundaries.
- **Transitivity:** complete-link checks prevent A–B–C bridge collapse when every member pair is not sufficiently coherent.
- **Missing evidence and uncertainty:** outliers remain singleton clusters; mixed/conflicting signals are retained rather than hidden.
- **Dangerous reassurance:** cluster membership is never treated as a root-cause proof or an input that can override contradictory current-run product-risk evidence.
- **Review/audit:** confirm, split and merge create append-only revisions with optimistic concurrency; old memberships remain inspectable.
- **Isolation:** candidates and persistent identities are project-scoped; cross-project clusters cannot form.
- **Reproducibility:** cluster rows record feature/algorithm versions, explicit components, candidate reasons and deterministic keys.
- **Evaluation truthfulness:** incident labels are held outside runtime features, but the fixture remains synthetic and is not presented as external generalization evidence.

## M4 history failure perspectives reviewed

- **Functional correctness:** one run/browser cohort contributes one independent observation; attempts are collapsed into first/final outcomes and retry recovery.
- **Denominator honesty:** skipped, cancelled and unknown outcomes stay visible; absent tests are reported separately and never treated as passes.
- **Leakage:** current/future runs, later reviews, cross-project, cross-repository and cross-framework records are excluded. The API cannot move its cutoff later than the selected execution.
- **Selection bias:** `full_suite`, `impact_selected` and `unknown` are persisted and reported separately. The analyzer accepts only same-browser/branch/environment/parallelism full-suite history.
- **Dangerous reassurance:** known-flake output requires at least five compatible independent runs and pass/fail observations, both passes and failures, a prior qualifying review decision and no safety reason or contradictory product-risk signal.
- **Auditability:** every rate includes its definition, numerator, denominator, interval/status and contributing run/execution references. Human reviews annotate but never rewrite outcomes.
- **Reproducibility:** history policy, filters, cutoff, review IDs and observations feed a canonical digest stored in the analysis input/provenance; changed history creates a new revision.
- **Usability:** the dashboard exposes rates, cohort filters, observation navigation, selection-bias warnings and explicit insufficient-data reasons rather than favorable default zeros.

## M4 impact failure perspectives reviewed

- **Functional correctness:** the selector uses explicit versioned mappings and changed paths rather than hidden keyword similarity; renamed/deleted paths and bounded reverse dependencies are first-class inputs.
- **Missing evidence:** missing, incomplete, truncated, untrusted or unmapped change evidence produces `FULL_SUITE_REQUIRED` instead of a narrow recommendation.
- **Dangerous reassurance:** recommendations are advisory only, never execute or skip tests, and always preserve mandatory smoke, security, transaction and explicitly critical tests.
- **Trust boundary:** a changed-file artifact may declare trust, but effective trust is bound only by validated transport metadata; uploaded bytes cannot self-promote to `trusted_workflow`.
- **Authorization/isolation:** snapshots, recommendations, tests, edges and overrides are project-scoped; cross-project IDs are rejected. Full project roles remain an M5 gap.
- **Reproducibility:** recommendations persist base/head, changed-input digest, mapping snapshot/policy/engine versions, stable reason components, exclusions and a canonical recommendation digest.
- **Review/audit:** include/exclude overrides are append-only, attributed, reasoned and timestamped; optimistic revision updates reject stale reviewers. Mandatory/critical exclusions are blocked.
- **Usability:** the dashboard displays changed files, selected and excluded tests, safety reasons, mapping provenance, confidence, revision and override history rather than only a selected count.
- **Evaluation truthfulness:** the committed impact benchmark reports recall and fallback behavior on synthetic fixtures; estimated durations are not presented as observed CI savings, and actual full-suite LedgerGuard backtesting remains open.
- **Delivery truthfulness:** local backend, migration, shell and deterministic evaluation checks are separated from npm/browser/PostgreSQL/Docker workflow evidence until the exact candidate SHA is inspected remotely.
