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
- Performance-intelligence development parent: exact source export of `2324ea06aa0d4910e671d23dda36d817a108e05d`
- Infrastructure-correlation development parent: exact source export of `76138480b81b4a6611d12043f36297d8bd5c0c8b`
- Project-authorization/review development parent: exact source export of `e8d0d750f2a3f5306722f0eec58da14e6a1c2525`
- Companion repositories remain read-only inputs:
  - `azerish25-ux/transaction-reliability-lab`
  - `azerish25-ux/playwright-quality-platform`

## Milestones

| Milestone | Status | Evidence in this revision |
|---|---|---|
| M0 — preflight and delivery proof | PASS | Canonical repository/branch/head and exact source parent were verified. Remote publication and CI must still be reread for each delivered SHA. |
| M1 — executable vertical slice | PASS | Raw upload -> stored ingestion/job -> leased worker -> run/evidence/failure -> automatic deterministic analysis -> dashboard. Recovery and browser path exist. |
| M2 — full ingestion and safe evidence | PARTIAL | Manifest `2.0`, adapter registry, honest completeness, execution/input-scoped evidence, immutable safe text derivatives, source maps, independent digest/locator/quotation/observation checks, semantic classification-claim validation, safe degradation, restricted screenshot/trace indexes, and project-scoped authorization exist. Producer-pinned fixtures, safe binary derivatives, broader predicates and bounded controlled artifact serving remain open. |
| M3 — analytical core | PASS | Versioned strict fingerprints plus loose readable clustering features, bounded candidate generation, explainable multi-signal scoring, hard conflict preservation, complete-link bridge prevention, deterministic cluster identities, append-only membership revisions, reviewed confirm/split/merge corrections, conservative rules, contradiction handling, confidence semantics and safe abstention all have executable coverage. |
| M4 — history, impact and performance | PASS | Prior-only exact-test history, independently recorded infrastructure-event correlation, deterministic change-impact recommendations and compatibility-gated performance regression analysis are implemented. Infrastructure analysis reuses the independent-run history cohort, applies strict trust/context/time compatibility, exposes exact exposed/unexposed denominators and immutable snapshots, and cannot independently authorize a diagnosis. History, infrastructure, impact and performance are available through the API/CLI/dashboard with executable safety coverage. |
| M5 — review workflow and UI | PARTIAL | M5.1 adds salted human credentials, revocable hashed sessions, project-bound one-time ingestion tokens, project-scoped viewer/reviewer/administrator enforcement, server-derived reviewer identity, append-only review decisions, audit events, a review queue and role-aware settings. M5.2 adds URL-restored project/run/failure/cluster/impact and filter state, searchable/sortable/paginated review and audit views, filtered audit CSV export, live health/policy status, skip-link/focus/live-region semantics, compact narrow-layout navigation, reduced-motion handling, and Chromium/Firefox/WebKit/narrow Playwright projects. Account/session recovery and administration, reviewer assignment/notifications, retention/tombstones, and exact delivered cross-browser CI evidence remain open. |
| M6 — corpus and evaluation | PARTIAL | 200 synthetic classification cases, a 24-case/13-label clustering fixture, a 12-case/11-family deterministic impact fixture, a 20-case performance compatibility/regression fixture and an 18-case infrastructure-correlation fixture have executable harnesses and committed reports. Actual LedgerGuard executions remain 0; all specialized fixtures are controlled synthetic safety evidence rather than production measurements or causal validation. |
| M7 — optional model boundary | NOT RUN | Deterministic mode is functional; provider adapter is not implemented. |
| M8 — GitHub integration | PARTIAL | Composite Action uses durable ingestion, carries repository/base/head/run-scope/comparison-trust metadata through safe argument arrays and emits ingestion/run/report outputs. Authenticated comparison lookup, live idempotent PR publication and stale-head reconciliation remain open. |
| M9 — hardening and packaging | PARTIAL | Docker/Compose, nonroot backend, CI, storage/archive/image bounds, recovery tests, browser E2E source and migration chain exist. Retention, backup/restore, telemetry export, load benchmarks and broader isolation evidence remain open. |
| M10 — final audit and source delivery | PARTIAL | M1, M3 and M4 plus the M2 safety foundation and M5.1/M5.2 identity, review, URL-state, accessibility and browser-source foundations are implemented. M2 closure, remaining M5 account/session and retention operations, actual companion-project M6 evidence, M7 provider boundary, M8 live publication, broader M9 operations and remaining final acceptance remain open. |

## Checks executed for the M5.2 accessibility/browser source checkpoint

- The working tree is based on exact remote commit `82f2bd3e567216c28c2dbbbe029031c201e035dc`; the reconstructed source tree matches Git tree `8dc805e59886863a17d82c3a8dff5605a3384112`.
- `PYTHONPATH=src pytest -q`: **171 passed**.
- `PYTHONPATH=src pytest --cov=failurelens --cov-branch --cov-report=term-missing --cov-fail-under=75`: **171 passed, 84.18% total branch-aware coverage**.
- SQLite Alembic empty-database upgrade, downgrade to `c7a9e2f4b610`, and re-upgrade through `a4f6e8c2d901`: **passed**.
- The classification, clustering, impact, performance and infrastructure deterministic harnesses regenerated and passed. The frozen test split retained macro F1 **1.000**, product-defect recall **1.000**, clustering pairwise precision/recall **1.000**, impact safety/recall metrics **1.000**, performance regression/compatibility metrics **1.000**, and infrastructure status/compatibility/provenance metrics **1.000** with the documented synthetic limitations.
- `tsc -p frontend/tsconfig.app.json --pretty false` against temporary source-compatible local React/Vitest declarations: **passed**. The declarations were removed after the check and are not repository content.
- `tsc --noEmit --strict --target ES2022 --module ESNext --moduleResolution Bundler --lib ES2022,DOM --types node frontend/playwright.config.ts frontend/e2e/*.ts` against temporary source-compatible Playwright/Node declarations: **passed**.
- `python -m compileall -q backend/src backend/tests evaluation`, `bash -n integrations/github-action/run.sh`, and the tracked-source credential-canary scan: **passed**.
- `git diff --check`: **passed**.
- Locked `npm ci`, Vitest, Vite production build, real browser execution, and exact delivered GitHub CI remain **NOT RUN** in this isolated source environment because the npm registry was unreachable. They must not be inferred from the static compile checks.

## Checks executed for the project-authorization/review checkpoint

- `PYTHONPATH=src pytest -q`: **171 passed**.
- `PYTHONPATH=src pytest --cov=failurelens --cov-branch --cov-fail-under=75 -q`: **171 passed, 84.18% total branch-aware coverage**.
- `python -m compileall -q backend/src backend/tests evaluation`: **passed**.
- Performance coverage includes final-attempt test durations and bounded k6 statistics, original/canonical units, exact evidence locators, immutable versioned policies, prior-only baselines, project/repository/workload/environment/producer/statistic/unit/trust/completeness gates, stale and future exclusion, deterministic replay, missing/incompatible statuses, lower- and higher-is-better metrics, zero baselines and run-level percentile anti-aggregation.
- Impact coverage includes focused direct mappings, renamed/deleted paths, bounded reverse-dependency traversal with cycles, immutable mapping versions, project isolation, mandatory critical-test preservation, untrusted/incomplete/truncated/unmapped full-suite fallbacks, base/head mismatch rejection, deterministic replay, append-only overrides, stale-revision rejection and artifact self-trust prevention.
- The controlled impact fixture contains **12 synthetic cases / 11 scenario families** and reports defect-revealing-test recall **1.000**, mandatory-critical-test recall **1.000**, expected safety-status accuracy **1.000**, deterministic-repeat agreement **1.000**, **7** focused-subset cases and **5** full-suite fallback cases. It remains synthetic and agent-authored; runtime values are estimates, not measured savings.
- The controlled performance fixture contains **20 synthetic cases** and reports status accuracy **1.000**, regression recall **1.000**, compatibility-selection accuracy **1.000**, evidence-citation validity **1.000**, deterministic-repeat agreement **1.000**, **0/5** dangerous false negatives, **0** significance claims and **0** non-median baseline aggregations. It remains synthetic and agent-authored, not production workload evidence.
- The controlled infrastructure fixture contains **18 synthetic cases** and reports status accuracy **1.000**, compatibility-selection accuracy **1.000**, event-provenance validity **1.000**, deterministic-repeat agreement **1.000**, **0** future-event leaks, **0** cross-project leaks, **0** unsupported causality claims and **0/1** dangerous product-defect downgrades. Every replay persisted/reused its immutable digest. It remains synthetic and does not establish causal validity or production prevalence.
- The frozen clustering fixture remains **24 cases / 13 evaluation-only incident labels** with pairwise precision **1.000**, pairwise recall **1.000**, **0** false merges, **0** false splits and adjusted Rand index **1.000**.
- SQLite Alembic empty-database upgrade, downgrade to the previous head `c7a9e2f4b610`, and re-upgrade through `a4f6e8c2d901`: **passed**.
- `bash -n integrations/github-action/run.sh`: **passed**.
- Application and frontend test sources passed a local TypeScript static compile check. The locked npm unit/build suite could not be restored in this isolated container because the registry was unreachable.
- Frontend unit/build, PostgreSQL migration, Chromium and Docker results must be taken from the exact delivered GitHub workflow run rather than inferred from source.

## M2 failure perspectives reviewed

- **Functional correctness:** observations are no longer counted as artifacts; one report remains one input regardless of test count. Evidence from one failed execution cannot enter another failure investigation.
- **Missing evidence:** declared required paths persist as `missing`; present but unsafe/invalid inputs persist as `restricted`, `rejected` or `unsupported`; rejected/tampered derivatives force explicit missing validated evidence and abstention.
- **Dangerous reassurance:** incomplete required scope blocks unsupported reassurance; invalid, modified or semantically irrelevant citations cannot retain a non-abstaining published category.
- **Data leakage:** text/query evidence is redacted into immutable safe derivatives; raw storage paths are not returned by the evidence API; screenshot/trace originals stay restricted.
- **Authorization:** uploaded GitHub metadata carries trust provenance but never authorizes publication; every evidence/resource lookup now passes through project-scoped identity and role enforcement. Bounded artifact delivery remains open.
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

## M4 infrastructure-correlation failure perspectives reviewed

- **Functional correctness:** events are first-class project records with stable producer identity and canonical content digests; retries/browser observations collapse to one conservative run outcome before exposure analysis.
- **Trust boundary:** only `authenticated_lookup`, `trusted_workflow` and `verified_monitor` records can enter an exposed cohort; self-reported/artifact-derived claims remain visible but cannot corroborate themselves.
- **Leakage and isolation:** events starting or independently recorded at/after the cutoff are excluded; cross-project events are unreachable and repository/environment/worker/workflow/runner/region incompatibilities are rejected explicitly.
- **Denominator honesty:** exposed and unexposed rates preserve skipped, cancelled and unknown outcomes outside exact pass/fail denominators and include Wilson intervals/minimum-support states.
- **Dangerous reassurance:** temporal overlap never proves causation, never removes current product-risk evidence and never independently changes a category to `infrastructure_failure`.
- **Confounding:** multiple event kinds overlapping one run produce an explicit confounded state unless the caller selects one kind; rejected events and reasons remain inspectable.
- **Reproducibility:** immutable snapshots persist policy/engine versions, the underlying history digest, accepted/rejected events, exact run/execution members, filters, rates, safety flags and a canonical input digest.
- **Usability:** the history API and dashboard expose trusted event provenance, exposed/unexposed counts/rates, event-kind associations, rejected context, confounders and snapshot persistence rather than a binary infrastructure badge.
- **Evaluation truthfulness:** the 18-case fixture verifies deterministic compatibility, leakage and dangerous-downgrade boundaries; it is synthetic and is not presented as causal or production evidence.
- **Delivery truthfulness:** local backend, migration, shell and deterministic evaluation checks remain distinct from exact delivered frontend/PostgreSQL/browser/Docker CI evidence.

## M4 impact failure perspectives reviewed

- **Functional correctness:** the selector uses explicit versioned mappings and changed paths rather than hidden keyword similarity; renamed/deleted paths and bounded reverse dependencies are first-class inputs.
- **Missing evidence:** missing, incomplete, truncated, untrusted or unmapped change evidence produces `FULL_SUITE_REQUIRED` instead of a narrow recommendation.
- **Dangerous reassurance:** recommendations are advisory only, never execute or skip tests, and always preserve mandatory smoke, security, transaction and explicitly critical tests.
- **Trust boundary:** a changed-file artifact may declare trust, but effective trust is bound only by validated transport metadata; uploaded bytes cannot self-promote to `trusted_workflow`.
- **Authorization/isolation:** snapshots, recommendations, tests, edges and overrides are project-scoped; cross-project IDs are hidden and viewer/reviewer/administrator roles are enforced.
- **Reproducibility:** recommendations persist base/head, changed-input digest, mapping snapshot/policy/engine versions, stable reason components, exclusions and a canonical recommendation digest.
- **Review/audit:** include/exclude overrides are append-only, attributed, reasoned and timestamped; optimistic revision updates reject stale reviewers. Mandatory/critical exclusions are blocked.
- **Usability:** the dashboard displays changed files, selected and excluded tests, safety reasons, mapping provenance, confidence, revision and override history rather than only a selected count.
- **Evaluation truthfulness:** the committed impact benchmark reports recall and fallback behavior on synthetic fixtures; estimated durations are not presented as observed CI savings, and actual full-suite LedgerGuard backtesting remains open.
- **Delivery truthfulness:** local backend, migration, shell and deterministic evaluation checks are separated from npm/browser/PostgreSQL/Docker workflow evidence until the exact candidate SHA is inspected remotely.

## M4 performance failure perspectives reviewed

- **Functional correctness:** final-attempt test durations and bounded k6 summary statistics become normalized observations; original and canonical values, units, statistic type, threshold state, workload and dimensions remain explicit.
- **Baseline compatibility:** baselines are prior-only and require matching project, repository, workload, metric scope/name/statistic, canonical unit, direction, trusted producer/run context, completeness and configured dimensions. Rejected candidates retain reason counts.
- **Missing evidence:** no acceptable prior cohort yields `BASELINE_UNAVAILABLE` or `INCOMPATIBLE_BASELINE`; neither state is rendered as no regression. Every accepted observation requires approved safe evidence.
- **Dangerous reassurance:** single current/baseline percentile pairs never produce significance claims; exported p95 values are compared as run-level observations and never averaged into an aggregate p95.
- **Data leakage and isolation:** current/future runs and cross-project records are excluded; immutable snapshots persist cutoff, policy, accepted members, rejected candidates and a canonical digest.
- **Uncertainty and confounders:** repeated observations expose median absolute deviation where available; small cohorts, producer threshold conflicts and limited samples remain visible with an explicit next-measurement recommendation.
- **Authorization:** project isolation and viewer/reviewer/administrator permissions are enforced at every policy, observation, baseline and comparison lookup.
- **Reproducibility:** policy, engine, normalized dimensions, observation/baseline digests, exact evidence IDs and deterministic comparison inputs are persisted.
- **Usability:** API, CLI and dashboard expose deltas, counts, tolerances, baseline age/provenance, blockers, rejected compatibility reasons, confounders, evidence links and next measurements.
- **Evaluation truthfulness:** the 20-case fixture is controlled synthetic safety evidence; it does not claim production prevalence, statistical power or independently blinded generalization.
- **Delivery truthfulness:** local backend, migration, TypeScript, shell and deterministic evaluation results remain distinct from the exact delivered GitHub Actions evidence.

## M5.1 identity, authorization, review and audit failure perspectives reviewed

- **Functional correctness:** human sessions, project memberships, project ingestion credentials and actor attribution are relational records with explicit expiry/revocation and optimistic review versions; the dashboard consumes the same typed API.
- **Missing evidence:** reviewer-supplied evidence IDs must exist in the analysis project, and category corrections require an explicit replacement category and engineering reason.
- **Dangerous reassurance:** `NO_BLOCKER_IDENTIFIED_IN_OBSERVED_SCOPE` is rejected when evidence is incomplete, product risk remains unresolved, or safety policy flags are active; a human record never executes release approval.
- **Data leakage:** every project-owned lookup resolves the owning project before serialization; a non-member receives not-found behavior for a guessed cross-project UUID, and ingestion credentials cannot read project data.
- **Authorization:** viewers are read-only, reviewers can record bounded human decisions, administrators manage memberships/credentials/policies, system administration is explicit, and client-supplied actor fields are rejected.
- **Credential safety:** passwords use salted `scrypt`; session and ingestion secrets are stored only as digests; project token plaintext is returned once; expired, revoked, malformed and cross-project credentials are rejected.
- **Auditability:** login outcomes, user/project membership changes, credential lifecycle operations, reviews, cluster corrections and impact overrides retain verified actor, reason, resource, project, timestamp and safe metadata. Application append-only records are not misrepresented as database-admin-proof immutability.
- **Reproducibility:** review decisions retain expected/current versions, prior decisions and cited evidence IDs; automated reanalysis does not overwrite human history.
- **Usability and accessibility:** the dashboard labels demo identity, exposes current role, removes actor text fields, disables unavailable controls, provides review/settings/audit workflows, labeled inputs and status messages. Broader automated accessibility and narrow-layout coverage remains open.
- **Recovery:** administrators can revoke ingestion credentials immediately; logout revokes the current session; production refuses unsafe bootstrap or cookie settings.
- **Delivery truthfulness:** local SQLite, backend, frontend and deterministic checks remain distinct from PostgreSQL, Chromium and Docker evidence on the exact delivered remote SHA.
