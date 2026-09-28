# FailureLens delivery ledger

## Accepted source checkpoint — M6.1 execution pipeline and reviewer view

**M6.1 scoped execution/evidence/UI acceptance: PASS. Product-recall target: FAIL. Full M6 and the full project: PARTIAL.**

Repository: `azerish25-ux/ai-quality-intelligence`. Default and working branch: `main`. Work started at `d05fc5297498004a8488c7d379248912479bafe8`. The accepted source is `0e98962d4ad46099298b42542b3e79708397536a`, tree `b9dd45d66d46f2262151f0a22978231a27063023`. [CI run 36492358143](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36492358143) passed all ten jobs on September 28, 2026. Source export run `36492358189` also passed. A subsequent documentation commit has its own CI; this source result does not substitute for that later run.

### Delivered behavior

The pinned, unmodified LedgerGuard source supplies fourteen production Java core files. The isolated JDK 21 runner executes sixty healthy controls and sixty detected interventions across fifteen distinct component mechanisms. Independent arithmetic, calendar and rejection-contract oracles verify each pair. Source digests are checked before and after execution. No companion code or branches were published.

All 120 resulting reports pass through the actual FailureLens ingestion API, durable worker and PostgreSQL. Label-free replay checks duplicate-import idempotency, persisted published analyses, authorized digest-checked evidence, exact excerpts and five repeated substantive analyses. Ground truth and intervention settings remain outside inference input. The file-open audit tripwire is not an operating-system sandbox.

The dashboard consumes real API metrics, labels the component scope, shows failed targets and abstentions, leaves five-class macro F1 undefined, and exposes mechanism breakdowns and limitations. Keyboard-operated details, table captions/header scopes and narrow-screen scrolling are browser-tested. Desktop and narrow execution screenshots from this exact source were inspected.

### Actual measured results

| Measurement | Result |
|---|---|
| Executed challenge | 60 product-defect cases, 15 mechanisms, 60 paired healthy controls |
| Correct product classifications | 48/60, or 80% |
| Product abstentions | 12/60 |
| Dangerous dismissals | 0/60 |
| Broader product misrouting | 0/60 |
| Published typed claims | 48/48 passed the application's typed support predicates |
| Repeat analysis | Five substantive results agree for each case |
| Unchanged 90% recall target | FAIL |
| Five-category macro F1 | Not established: this challenge has only product-defect labels |

The abstentions concern operation-scoped idempotency, stale projection ordering and weekly recurrence, four cases each. They remain visible regression evidence, not cases to relabel or silently tune into a purported held-out success. Four variants per mechanism are dependent. Case-level Wilson bounds are only an independence illustration; neither those bounds nor family resampling establish deployment risk. No real model was invoked and external-model spend was zero; compute cost was not measured.

### Executed verification

| Verification | Accepted-source result |
|---|---|
| Backend on PostgreSQL | 307 passed, no skips; 84.96% branch-aware coverage; unchanged 75% gate |
| Migration | PostgreSQL upgraded through `c8f2e6a9d410`; M6.1 needs no new migration |
| Actual producer fixtures | Producer generation and 16 adapter/API contracts passed; contracts are also included in the backend count |
| LedgerGuard execution and evidence job | Passed on a clean source tree with actual PostgreSQL replay |
| Frontend | npm lockfile install, unit tests, strict type-check and production build passed |
| Browsers | Chromium, Firefox and WebKit desktop plus narrow Chromium all passed |
| Legacy evaluation | All five deterministic regression harnesses passed; not held-out generalization evidence |
| Docker | Compose validation and API/dashboard image builds passed; not offline/backup/restore acceptance |

Local verification is separate: 303 backend tests passed and four PostgreSQL-only cases were skipped, with 82.36% branch-aware coverage. The 54 new evaluation/snapshot regression cases passed. Offline snapshot verification and independent rescoring reproduced the retained metrics exactly. The strict scorer's `--enforce-quality` option was exercised and returned exit 2 for the failed recall target, rather than silently passing it.

The commands actually executed are the permanent `.github/workflows/ci.yml` steps and the reproduction commands in [ledgerguard-evaluation.md](ledgerguard-evaluation.md): component runner, label-free replay with five repeats, executed scorer, legacy-family audit, PostgreSQL migration, backend coverage, npm tests/build, four Playwright projects and Docker configuration/build. No existing test was disabled, meaningful assertion removed, coverage threshold lowered or retry policy increased.

### Evidence and delivery boundaries

Accepted-source execution artifact `11002416072` in run `36492358143` has SHA-256 `de91aa6b6eed68b05fe99037198eb90950ba713e1d33781638155fc6ef3c34d1`, size 192,038 bytes and expiry `2026-10-28T22:27:49Z`. Its downloaded predictions were independently rescored against its artifacts and produced identical metrics.

Inspected browser artifacts: Chromium desktop `11002601435` and narrow Chromium `11001871879`, retained for seven days. Their evaluation screenshots display the tested source and the failed 90% target. The original compact corpus and reports from `7405d923` remain committed under `evaluation/corpus/ledgerguard-component-v1/` and `evaluation/reports/ledgerguard-component-v1-7405d923/`; they were not rewritten as newer results. The default local dashboard names that retained report's actual tested source. CI mounts its own exact-revision report.

Earlier run `36489651488` exposed the nested browser locator defect; run `36491672531` exposed missing table header scopes. Both were fixed and tested, not treated as acceptance. Temporary source/publication helpers are absent from the accepted tree. No public deployment, release, package publication, paid-model invocation or companion-repository change was performed.

### Remaining M6 work

These are real LedgerGuard component executions, not LedgerGuard HTTP/database financial transactions, concurrency/rollback tests or reconciled committed-economic-effect scenarios. Full M6 still needs a genuinely diverse five-category corpus with at least 200 cases and 80 independent mechanisms, valid family-grouped development/calibration/test splits, the required held-out product families, temporal and unknown-family challenges, broader adversarial/claim metrics and passing quality targets. The legacy 200-case corpus has 100 nominal IDs but only five recurring templates crossing splits; its original bytes and scores remain historical regression evidence.

The next substantive extension is a development-only full-stack LedgerGuard control/intervention path with an independent database/reconciliation oracle, followed by new category/family coverage and a frozen evaluation split. Do not claim inspected challenge cases are fresh held-out evidence. M2/M5 residual scope, M7–M10 and final project acceptance remain separate.

### Preserved history

The preceding ledger is preserved byte-for-byte in [PROGRESS-through-M6.1.md](PROGRESS-through-M6.1.md), original Git blob `d6933079dafe82cb19bebcc97829840a064321ca`. Earlier pending states and counts apply to their named revisions, not this accepted source. See the consolidated [requirements matrix](requirements-matrix.md).
