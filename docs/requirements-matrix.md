# Requirement-to-evidence matrix

## M6.4.1 transaction-finality closeout

The initial NOT RUN checkpoints are superseded by actual execution at
`b7327b437d8fc4cb009918d1d4d31b6bf36f508a`, run
[36567980376](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36567980376).
The later clean-source repair and retention verification are recorded in
[PROGRESS.md](PROGRESS.md). Older rows below remain scoped historical records;
no failed held-out target is waived by this closeout.

| ID | Requirement | Status | Implementation and verification boundary |
|---|---|---|---|
| R-M641-CONTRACT | Evidence-grounded terminal-rejection/committed-effects relation | PASS | Additive `TransactionFinality`, independent publication recomputation, 97 boundary/API regressions and actual PostgreSQL/API/worker replay at `b7327b4`; four published claims independently supported. |
| R-M641-PRODUCER | Actual paired rollback/early-commit execution | PASS | Run `36567980376`, job `109404555847`: four real HTTP/PostgreSQL control/intervention pairs, pinned companion, isolated resources and independently checked SQL/receipts. One mechanism, not broad fault coverage. |
| R-M641-AUDIT | Case/family diagnostic gap audit | PASS | `evaluation/diagnostic_gap_audit.py`, independent scoring first, 13 local regressions and actual retained benchmark audit; legacy records remain uninstrumented rather than assigned invented causes. |
| R-M641-VERIFY | Exact-source PostgreSQL and browser evidence | PASS | Actual `rollback-evaluation.yml` execution at `b7327b4`, strict source/provenance/scoring assertions and desktop/narrow API-backed journeys; subsequent repair-source runs are identified separately in `PROGRESS.md`. |
| R-M641-CI | Clean committed-source backend installation | PASS | `scripts/install_committed_backend.sh`, ordinary PostgreSQL CI backend installation, 25 real-build/provenance regressions and explicit offline build-backend test dependency. Backend job at `9b68283` passed; no provenance assertion, coverage gate or test was removed. Final package CI is recorded separately in `PROGRESS.md`. |
| R-M641-RETAIN | Durable independently verifiable actual execution | PASS | `evaluation/reports/transaction-finality-postgresql-v1/`, verified original artifact digest, all 48 member bodies retained, bounded `verify_finality_snapshot.py`, independent rescoring/oracle recomputation and 17 corruption/scope regressions. Offline verification is not fresh PostgreSQL or browser execution. |
| R-M641-HELDOUT | Renewed five-category held-out acceptance | NOT RUN | Eight-case one-mechanism development slice only; original quality targets and failed benchmark bytes unchanged. |

## M6.4 diagnostic-quality development

The two historical M6.3 tracks below now have distinct CAMPAIGN/BENCHMARK IDs;
neither dataset nor its results have been merged. Immutable historical matrix
archives are unchanged. This is a scoped implementation, not full M6 acceptance.

| ID | Requirement | Status | Implementation and verification boundary |
|---|---|---|---|
| R-M64-BASE | Verify reconciled source before extension | PASS | Source-only export commit `17cd55af5e231d58796bc44e1b4911438b12a088`: all ten jobs in CI run `36515163885` passed. This does not certify later commits. |
| R-M64-DIAG | Four typed observable diagnostic relations | PASS | `contract_evidence.py`, `analysis.py`, additive JSON Schema; positive, missing, contradictory and malformed-input regressions. |
| R-M64-PUBLISH | Recomputed categories, wording and safe product-risk handling | PASS | `evidence_validation.py`, forged text/category/reference tests; competing product-risk signals cannot be outscored into non-product reassurance. |
| R-M64-SCORE | Independent scoring with explicit development scope | PASS | `campaign_harness.py`, independent numeric/category rubrics; development-only rejects held-out data and default scoring preserves corpus minimums. |
| R-M64-OBSERVE | Fresh richer companion observations | PASS | Run `36519135228` at `dc0aaf1`: twelve fresh interventions and twelve controls across three known mechanisms; independent scalar oracles. Not new held-out families or HTTP/database transactions. |
| R-M64-UI | Display diagnostic findings and unresolved gaps | PASS | Same exact-source run passed all sixteen desktop/narrow API-backed diagnostic journeys. Captured views inspected; no retries or assertions weakened. |
| R-M64-REGRESSION | New and existing regression verification | PARTIAL | 112 new diagnostic/evaluator tests plus 59 retained contract regressions; full local suite 670 passed, four PostgreSQL-only skips. Exact-source GitHub results belong in `PROGRESS.md`. |
| R-M64-HELDOUT | Renewed held-out quality evaluation | NOT RUN | No new 100-case/20-product-family test set or deployment-quality claim. Historical failed test results are unchanged. |
| R-M64-FULL | Full M6.4 quality recovery and M6 completion | PARTIAL | Fresh held-out acceptance, full temporal/adversarial scope and wider actual producer evidence remain required. |

## M6.3 source checkpoint

| ID | Requirement | Status | Implementation and current boundary |
|---|---|---|---|
| R-M63-CAMPAIGN-CONTRACT | Three structured diagnostic contracts | PASS | `contract_evidence.py`, ingestion/execution binding, `analysis.py`, independent publication recomputation; 59 local contract regressions. Producer measurements are not trusted causal verdicts. |
| R-M63-CAMPAIGN-CORPUS | Versioned five-category family-grouped corpus | PARTIAL | 264 cases / 87 agent-reviewed catalogue groups, 160 synthetic test cases / 60 test-only groups. Minimum counts and structural split checks pass; conceptual independence is not independently expert-adjudicated. |
| R-M63-CAMPAIGN-PROVENANCE | Preserve real execution and synthetic distinctions | PASS | Original sixty executed component cases stay in development. 204 synthetic cases include twelve structured supplements, not new real executions. Existing reports remain unchanged. |
| R-M63-CAMPAIGN-REPLAY | General API/worker and prior-only history replay | PARTIAL | Separate public input runner, actual ingestion and five repeated decisions; synthetic clock and future-review exclusion tested locally. Exact-source PostgreSQL campaign execution pending at this checkpoint. |
| R-M63-CAMPAIGN-SCORER | Independent bounded claim and safety evaluation | PARTIAL | Separate scorer, unchanged targets, actual publication/evidence checks, per-class metrics, baselines, family aggregation and error retention. Full frozen test metrics pending; broader semantic rubric remains open. |
| R-M63-CAMPAIGN-UI | Campaign dashboard and verification | PARTIAL | Authenticated bounded report API, separate campaign view, confusion matrix, comparisons and all errors. Actual desktop/narrow browser verification pending at this checkpoint. |
| R-M63-CAMPAIGN-FULL | Complete M6 quality acceptance | PARTIAL | Code or count gates do not substitute for passing quality targets, wider adversarial/temporal coverage and complete master-prompt acceptance. |

The preceding M6.2 matrix is historical below; its exact-revision acceptance does
not substitute for verification of this new source.


Current executed M6.2 source: `b31be357fc35aa4b9c225f28147ab32367d95a18`, [CI run 36499736103](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36499736103) and [full-stack run 36499736145](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36499736145). All ten existing jobs and the new full-stack job passed. Retained reports continue to name the revision actually executed; subsequent commits need separate CI. See [PROGRESS.md](PROGRESS.md) for executed counts and exact delivery boundaries. PASS is scoped to the named behavior, not a full-project declaration. Full M2, complete M5, full M6 and the master project remain PARTIAL.

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

## M6.2 scoped execution and retention

| ID | Requirement | Status | Implementation / verification boundary |
|---|---|---|---|
| R-M62-EXEC | Real HTTP/PostgreSQL control and faulty retry boundary | PASS | `integrations/ledgerguard/fullstack.py`, clean pinned source, disposable stack, actual lost response and independent SQL/receipt oracle; executed job `109187473637`. One mechanism, not concurrency/rollback coverage. |
| R-M62-BUNDLE | Preserve related artifacts in one run and isolate paired roles | PASS | Replay v2, three-input bundles, numeric adapter, actual API/worker/PostgreSQL replay, two distinct runs per pair and idempotent re-import. |
| R-M62-CLAIM | Recomputed numeric diagnosis with verified evidence | PASS | `transaction_evidence.py`, publication predicates, independent scorer; four bounded claims and eight producer-bound numeric derivatives; confusing/missing/conflicting/forged-evidence regressions. |
| R-M62-REVIEW | Scoped, inspectable results and advisory reports | PASS | Separate evaluation API/panel, executed desktop/narrow Chromium journey and inspected screenshots; advisory HOLD reports. Source/scope/limits visible; UUID links require originating DB. |
| R-M62-RETENTION | Bounded durable snapshot and independent offline rescore | PASS | Exact `b31be357` report and lossless snapshot; `verify_fullstack_snapshot.py`, `test_fullstack_snapshot.py`; archive/report digests and original CI expiry retained. Offline verification is not fresh execution. |
| R-M62-ACCEPT | Exact-source delivery and unchanged historical failures | PASS | Accepted `b31be357` source has ten green regression jobs and one green full-stack job. Existing component 48/60 recall and failed 90% target remain unchanged. Later evidence commits require their own CI. |
| R-M62-FULL | Diverse held-out evaluation and complete M6 | PARTIAL | One development mechanism with four dependent amount variants does not satisfy 80 independent families, frozen five-category splits, temporal/unknown-family slices or broader quality acceptance. |

## M6.3 local implementation checkpoint

The entries below supplement, not overwrite, the immutable historical measurements
above. Delivery and exact tested revisions are recorded in `PROGRESS.md`.

| ID | Requirement | Status | Implementation / boundary |
|---|---|---|---|
| R-M63-BENCHMARK-DOMAIN | Structured operation, projection and calendar observations | PASS | `domain_evidence.py`, adapter/binder, recomputed publication predicates, API/worker and false-blame regressions. Producer assertions are not causal certification. |
| R-M63-BENCHMARK-CORPUS | General five-category frozen corpus | PASS | 260 cases, 83 authored mechanism groups, 108 test cases, preserved 60 actual historical executions; explicit author/adjudication limitations. |
| R-M63-BENCHMARK-SPLIT | Family/incident/artifact isolation | PASS | `benchmark_audit.py`, exact digests, all previously inspected mechanisms in development, altered-policy and cross-split regressions. |
| R-M63-BENCHMARK-PIPELINE | General API/worker replay and independent scoring | PASS | 260-case actual local API/worker/SQLite replay, 718 ingestions, five identical analyses per case, 260 resolved references and 126 supported claims under the declared rubric. PostgreSQL/browser acceptance is not inferred. |
| R-M63-BENCHMARK-UI | Five-class results, comparisons and all errors | PARTIAL | Authenticated bounded endpoint and UI/browser test source implemented. Full frontend install/build/browser verification is environment-dependent. |
| R-M63-BENCHMARK-QUALITY | Original recall/F1/coverage/safety targets | FAIL | Test product recall 0/44, macro F1 0.3048 and coverage 18/92 miss 90%/0.80/75%. All 44 product cases abstain; dangerous dismissals are 0/44. Strict scorer exits 2; no thresholds or labels changed. |
| R-M63-BENCHMARK-ADVERSARIAL | Forty tagged cross-category inputs | PARTIAL | Five text/canary classes; not every master attack class or OS sandbox verification. |
| R-M63-BENCHMARK-TEMPORAL | Prior-only chronology and unknown families | PARTIAL | Actual ingestion/review order and later-run exclusion; unknown-family slice equals the test split, not an independent second benchmark or dated production backtest. |
| R-M63-BENCHMARK-FULL | Full M6 acceptance | PARTIAL | No blinded expert study, no new LedgerGuard executions in this campaign; broad adversarial, temporal, quality and final packaging scope remains. |

Retained M6.3 measurement source: `f1269c3ce52d4bf64f8614aacd34d99903a99b5f`. The compact snapshot and metrics rescore identically with `python evaluation/verify_benchmark_snapshot.py`. This verifies historical local bytes, not fresh PostgreSQL/browser execution.

## 2026-09-30 continued full-project implementation

| ID | Requirement | Status | Evidence and remaining boundary |
|---|---|---|---|
| R-M7-TRANSPORT | Concrete optional HTTP adapter and safe evidence bridge | PARTIAL | `providers.py`, `provider_service.py`, explicit deadlines, transport privacy, retained rejection usage and deterministic safety. Disabled-default operator/API/UI wiring is implemented with production-auth gates and explicit approval; fresh hosted acceptance and real-model evaluation remain. |
| R-M7-LEDGER | Durable budgets, invocation attempts and recovery | PARTIAL | Migrations `d3a5f7c9b120` and `e6c8a2f4b130`, linked dedicated jobs, atomic reservations/idempotency, shared admission/circuit state, current-session/evidence revalidation and late numeric settlement. Earlier internal PostgreSQL passed at `9414d91`; new integration has 286 focused local passes and seven new PostgreSQL-only cases awaiting real execution. |
| R-M7-APPLICATION | Safe preview, explicit approval and status/cancellation UI | PARTIAL | Scoped APIs and administrator UI, exact transmitted-evidence preview, immutable approval digests, ambiguous-response reconciliation, cancellation and stale-navigation guards; 115 frontend tests and production-auth HTTP fixtures pass. Separate desktop/narrow provider journeys await hosted browser execution. |
| R-M7-EGRESS | Isolated optional provider worker and destination restriction | PARTIAL | Separate Compose profile, worker-only token, operator-owned DB credentials, production-auth requirement, exact-host CONNECT proxy and bounded public-address DNS resolution; 85 local proxy/deployment cases pass. Docker topology, ordinary-worker isolation and PostgreSQL execution remain NOT RUN for this new tree. |
| R-M8-PUBLISH | Bot-owned idempotent comments and stale SHA reconciliation | PARTIAL | `github_publication.py`, durable service/receipt models and migration `f8d0c2e4a610`; authenticated Bot identity before mutation, committed write intents, sticky uncertainty, current-evidence revalidation and explicit neutral repair. The reviewed 134-case local suite passes; three PostgreSQL cases, exact-source hosted acceptance and authorized live target remain unverified. Conditional trusted follow-up stays disabled. |
| R-M8-PREVIEW | Authorized shared JSON/Markdown report preview | PASS | `github_snapshot.py`, API/CLI integration and scope/retry/expiry tests; exact-source ordinary CI `36653389182` at `9d8a5b9` passed. Newer restriction-revalidation regression needs its own CI. |
| R-M8-UI | Inert preview/download and current product branding | PARTIAL | Markdown plus exact canonical report/evidence JSON downloads, scope/digest/byte checks, stale-response handling and cancellation. Frontend build and 200 unit tests pass, including a real synthetic backend-to-client byte round trip. All 43 existing browser journeys collect with extended desktop/narrow checks; actual new browser execution remains pending. |
| R-M8-RICH | Persisted rich report contents and conservative baselines | PARTIAL | Shared report adds skipped reasons, effective impact overrides, current clusters and evidence-checked performance/baseline findings. Suite/source-path identity and Unicode trimming regressions pass within 112 focused report/Action/publication tests. No preview-created recommendations or relaxed risk flags; fresh full/hosted verification pending. |
| R-M8-EVIDENCE | Retain approved inspectable evidence after ephemeral CI | PARTIAL | `github_evidence.py`, shared immutable scoped validation, digest-bound CLI/API export and declared Action artifact. Thirty-two focused evidence/snapshot/validator tests pass; only an approved bounded reference subset is retained. Hosted artifact transfer and new browser downloads remain unverified. |
| R-M8-CONFIG | Strict Action modes and operator-selected configuration | PARTIAL | Explicit deterministic and summary/artifact-only modes, bounded non-executable config path/digest, no PR auto-discovery, no provider/comment activation, fixed output caps and independent file/scope/digest checks. All 86 Action cases and offline workflow audit pass; hosted execution remains pending. |
| R-M9-CAPABILITY | Network/process/GitHub mutation boundary regressions | PARTIAL | Forty local passing normalized-input attack combinations with capability spies; not complete OS/binary/adversarial acceptance. |
| R-M9-MUTATION | Executed safeguard sensitivity and false-kill rejection | PARTIAL | Seven isolated baseline/mutant pairs and 38 local runner regressions; provenance changes invalidate results rather than count as kills. Strict local and dedicated CI at `1f7fe67` passed seven baselines/seven kills with zero errors; fresh `9414d91` CI also passes. Not a held-out or security-immunity claim. |
| R-M9-TRACE | Bounded manual spans and durable trace context | PASS | `telemetry.py`, fixed enums/counters, explicit disabled-by-default OTLP, actual loopback canaries and durable-worker tests; all ten ordinary CI jobs at `8dbce9b` pass. Process-local metrics remain explicitly scoped; no external collector invoked. |
| R-M9-COLLECTOR | Optional isolated local collector/viewer | PASS | Actual Docker run `36687923599` at `8daa5c7` verifies PostgreSQL-backed API/worker trace, canaries, internal-only OTLP, loopback viewer ingress, Internet denial and collector-outage readiness. Not an interactive visual UI audit. |
| R-M9-LOAD | Actual 50,000-execution read target | PARTIAL | Original failures and 312.37 ms passing measurement preserved; identical-runtime docs-only follow-up failed at 572.62 ms, and `efa9a13` measured 710.69 ms on AMD EPYC with zero request failures. Stable acceptance and failure-heavy/reference-resource workloads remain open. |
| R-M2-KEYED | Project-scoped keyed sensitive-value correlation | PARTIAL | v3 HMAC/project keys, private persistence, queue pins, rotation and immutable legacy validation implemented; 441 affected passes followed by clean local source `f7d847f` (1,302 passed, nine PostgreSQL-only skips). Exact-source PostgreSQL/backup/browser verification pending. Strict typed identifiers and unknown fields remain explicit gaps; old derivatives unchanged. |
| R-M9-QUALITY-TOOLS | Formatting, lint, backend type and dependency/workflow security gates | PARTIAL | All six independent offline gates pass on clean local `d7dd7eb`: lint, format, gradual types, lock/export parity, workflows and source-bound secret review (3,052 candidates, zero unresolved). Initial hosted workflow at `efa9a13` failed before jobs; runner-context correction passes 80 focused tests. New hosted acceptance remains pending. Required npm metadata audit remains authorization-gated and NOT RUN; security acceptance is blocked. |

The original benchmark quality failure is still FAIL. These additions neither
change acceptance thresholds nor complete M6, M7, M8, M9 or the full master project.

The read-only two-shard GitHub consumer is implemented with explicit completeness and
sanitized outputs; hosted Action execution is pending. Trusted write publication
still requires separate threat-boundary and live-target verification.
