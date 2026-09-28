# Requirement-to-evidence matrix

Current accepted source: `0e98962d4ad46099298b42542b3e79708397536a`, [CI run 36492358143](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36492358143). All ten jobs passed. See [PROGRESS.md](PROGRESS.md) for executed counts and exact delivery boundaries. PASS is scoped to the named behavior, not a full-project declaration. Full M2, complete M5, full M6 and the master project remain PARTIAL.

## Core and previously delivered behavior

Implementation paths below are relative to `backend/src/failurelens/` unless a full path is shown. Named test files are in `backend/tests/`. Current CI reruns the previous regression suite alongside M6.1.

| ID | Requirement | Status | Implementation and evidence / remaining boundary |
|---|---|---|---|
| R-DELIVERY-01 | Canonical repository and preserved history | PASS | Existing `main`, owner-authorized non-force publication, exact-source CI and source export; no companion writes. |
| R-DATA-01 | Relational model | PASS | `models.py`, Alembic migrations through `c8f2e6a9d410`, `test_models.py`, PostgreSQL migration. |
| R-INGEST-00 | Report to job, evidence and analysis | PASS | `service.py`, `storage.py`, worker and `test_durable_ingestion.py`; browser upload journey and executed replay. |
| R-INGEST-01 | Idempotent ingestion | PASS | Normalized/raw ingestion, `test_ingestion_replay.py`, executed duplicate-import checks. |
| R-INGEST-02 | JUnit XML dialect support | PARTIAL | Real producer exports, nested suites and unsafe XML tests; broader dialect/edge coverage remains. |
| R-INGEST-03 | Playwright JSON | PARTIAL | Actual pinned producer fixture and `test_producer_contracts.py` pass; full dialect/depth coverage remains. |
| R-INGEST-04 | All eleven input families | PARTIAL | Registry and M2 adapters, real producer fixtures and documented support depths; not universal compatibility. |
| R-INGEST-05 | Manifest/shard completeness | PASS | Persisted input states and required/optional semantics; observations are not input counts. |
| R-STORAGE-01 | Restricted bounded immutable storage | PASS | `storage.py`, digest/size checks, archive/resource regressions and deletion outbox. |
| R-AUTH-01 | Project-scoped roles | PASS | `auth.py`, `test_auth.py`, per-resource checks and cross-project not-found behavior. |
| R-AUTH-02 | Restricted credentials and sessions | PASS | Hashed scoped tokens, salted passwords, session expiry/revocation and account tests. |
| R-AUDIT-01 | Attributable append-only audit | PARTIAL | SQL filtering, export policy, review/account/retention events delivered; broader security-audit coverage and retention remain. |
| R-SEC-01 | Declared text redaction | PASS | `redaction.py`, `test_redaction.py`, `test_trace_safety.py`; no universal PII claim. |
| R-SEC-02 | Safe binary derivatives | PARTIAL | Reviewed opaque masks, safe trace text, digest-checked serving and expiry pass; richer sensitive-field policy and optional retained-original encryption remain. |
| R-EVIDENCE-01 | Precise verified citations | PARTIAL | `evidence_validation.py`, binary source locators and authorized content endpoints pass; broader claim predicates remain. |
| R-ANALYSIS-01 | Five permitted categories | PASS | Enums, schema and `test_analysis.py`. |
| R-ANALYSIS-02 | Abstention and contradiction safety | PASS | Publication degradation, product-risk checks and adversarial tests; benchmark quality is reported separately. |
| R-ANALYSIS-03 | Explainable clustering | PASS | `clustering.py`, bridge/collision tests, attributable corrections and revision history. |
| R-HISTORY-01 | Honest historical statistics | PASS | `history.py`, retry collapse, explicit denominators, cohort/cutoff tests and traceable observations. |
| R-INFRASTRUCTURE-01 | Recorded infrastructure associations | PASS | `infrastructure.py`, compatibility/trust/cutoff tests and synthetic regression harness; not causal proof. |
| R-HISTORY-02 | Known-flake history gate | PASS | Prior-only matching reviewed history, minimum independent-run support and contradictory-evidence checks. |
| R-IMPACT-01 | Explainable focused selection | PASS | `impact.py`, trusted mappings, mandatory tests, overrides and full-suite fallback tests. |
| R-PERFORMANCE-01 | Compatible baseline comparison | PASS | `performance.py`, exact current/baseline evidence, unit/percentile rules and uncertainty states. |
| R-REVIEW-01 | Human decision history | PARTIAL | Real authorized reviews, full-dataset SQL pagination, optimistic revisions and audit pass; wider workflow scope remains. |
| R-API-01 | Typed versioned operations | PARTIAL | Existing ingestion, investigations, roles, lifecycle and evidence endpoints pass; complete GitHub publication remains. |
| R-JOBS-01 | Durable leased processing | PASS | Queue claiming, recovery, bounded retries, cancellation and real worker tests. |
| R-GITHUB-01 | Reusable Action and publication | PARTIAL | One-shot ingestion/reporting exists; complete trusted lookup, idempotent live comments and stale-head reconciliation remain. |
| R-UI-01 | Complete reviewer dashboard | PARTIAL | Real API-backed operational, evidence and evaluation flows pass in four browser lanes; complete master UI scope is not declared finished. |
| R-OPS-01 | Runnable stack and recovery | PARTIAL | PostgreSQL/API/worker/browser startup, Compose validation and image builds pass; offline, restore, load and broader recovery acceptance remain. |
| R-CI-01 | Verification workflows | PASS | Ten accepted-source jobs; separate producer, PostgreSQL, evaluation, frontend, browser and Docker evidence. |
| R-M53-ACCOUNT | Account/session lifecycle | PASS | `accounts.py`, `test_operations.py`, `test_operations_postgres.py` and real browser account journey. |
| R-M53-RETENTION | Project expiry and tombstones | PASS | `retention.py`, deletion outbox/crash tests, PostgreSQL and actual worker/browser expiry; excludes global backup policy. |
| R-M53-QUEUE | Full review dataset pagination | PASS | SQL filtering before pagination, over-500-record regression and browser navigation. |
| R-M53-EXPORT | Governed filtered audit export | PASS | Administrator policy, bounded rows, formula escaping, attribution and API/browser tests. |
| R-M53-VERIFY | Scoped operational verification | PASS | Historical M5.3.1 acceptance preserved; current PostgreSQL/browser regression passes. |

## Corpus and evaluation

| ID | Requirement | Status | Evidence / boundary |
|---|---|---|---|
| R-CORPUS-01 | Full diverse 200-case corpus | PARTIAL | Old 200 synthetic records retained, but only five recurring templates; separate 60 executed product cases do not establish full five-category independent diversity. |
| R-CORPUS-02 | 60 actual LedgerGuard cases / 15 families | PASS | Sixty executed production-component interventions and paired controls across fifteen mechanisms; explicitly not full-stack DB/HTTP financial effects. |
| R-CORPUS-03 | 80 genuine independent families | FAIL | Legacy nominal IDs do not satisfy independence; fifteen new mechanisms do not close the overall target. |
| R-CORPUS-04 | Leakage-aware frozen splits | PARTIAL | Label-free input boundary and legacy cross-split audit pass; new challenge is public, product-only and not a frozen held-out split. |
| R-EVAL-01 | Dangerous-dismissal and five-class metrics | PARTIAL | Exact dangerous numerator/denominator and abstentions measured through API; five-class metric machinery exists, but meaningful five-category executed acceptance remains. |
| R-EVAL-02 | Independent/generalizable evaluation | NOT RUN | Agent-authored public challenge only; no independently blinded or deployment study. |
| R-EVAL-CLUSTER-01 | Labeled clustering evaluation | PASS | Existing 24-case/13-incident synthetic regression harness; not independent deployment evidence. |
| R-EVAL-IMPACT-01 | Selection recall/safety metrics | PASS | Existing 12-case synthetic harness; runtime savings remain estimated, not measured deployment savings. |
| R-EVAL-PERFORMANCE-01 | Performance compatibility evaluation | PASS | Existing 20-case synthetic harness; percentile and significance limits remain explicit. |
| R-EVAL-INFRASTRUCTURE-01 | Infrastructure safety evaluation | PASS | Existing 18-case synthetic harness; no future/project leakage or unsupported causality in that fixture. |
| R-M61-EXECUTION | Reproducible control/intervention runner | PASS | `integrations/ledgerguard/run.py`, pinned hashes, independent oracles, command provenance and accepted-source job `109163699055`. |
| R-M61-PIPELINE | Evaluate actual published decisions | PASS | `evaluation/replay.py`, separate labels, API/worker/PostgreSQL ingestion, idempotency, authorized evidence and five repeat analyses. |
| R-M61-INTEGRITY | Artifact and scoring integrity | PASS | Strict manifests, all 48 published typed claims verified; 54 tests in `test_executed_evaluation.py` and `test_executed_snapshot.py`. |
| R-M61-RETENTION | Durable inspectable corpus/results | PASS | Committed compact execution archive, immutable reports and bounded offline `evaluation/verify_snapshot.py`; old source provenance retained. |
| R-M61-RECALL | At least 90% product recall | FAIL | 48/60 = 80%, with 12 abstentions; strict quality mode returns exit 2. Target unchanged. |
| R-M61-SAFETY | No dangerous critical dismissal | PASS | 0/60 on the declared component challenge only; no population guarantee. |
| R-M61-UI | Truthful accessible executed-results view | PASS | `EvaluationPanel.tsx`, `evaluation-journey.ts`, desktop and narrow API-backed journeys, caption/scope/keyboard checks and inspected screenshots. |
| R-M61-FULL | Complete M6 acceptance | PARTIAL | Five-category diversity, valid held-out/temporal slices, full-stack scenarios, broader metrics and passing quality targets remain. |

## History and later milestones

The preceding matrix is preserved byte-for-byte in [requirements-through-M6.1.md](requirements-through-M6.1.md), original blob `b21332d811f5dbd92c65a402d17d9fb0ed171bad`. Its earlier pending descriptions are historical, not current missing-feature claims. M7 optional-provider contracts, M8 complete GitHub publication, M9 hardening/packaging and M10 final audit remain unfinished. No green scoped CI job overrides a failed quality target or implies full-project acceptance.
