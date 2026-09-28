# M6.1 implementation checkpoint — execution-backed component challenge

Work starts from `d05fc5297498004a8488c7d379248912479bafe8`; source pin was delivered as `1657eed1ca06e5aa5a0e6f8aeed85b3c590b3994` on `main`. The implementation adds 60 paired executed LedgerGuard component faults across 15 actual mechanisms, label-free API/worker replay, digest-checked exported evidence, independent outcome scoring, honest comparisons, family-level uncertainty and legacy-template leakage auditing. The evaluation dashboard reads real metrics and displays failed targets and undefined five-class metrics explicitly.

Local JDK 21 execution: 60 healthy controls pass and all 60 interventions fail the independent contracts. SQLite API/worker replay ingests all 120 reports, verifies idempotency and evidence, and retains substantive decisions across five analysis requests. Local measured product recall is **48/60 (80%)**, 12 abstentions and 0/60 dangerous dismissals. The unchanged 90% recall target **FAILS**. Thirty new evaluation regression tests pass locally. These local results use an uncommitted worktree; PostgreSQL, browser and exact-revision remote acceptance must be recorded separately after publication.

This is real production-component execution, not LedgerGuard HTTP/database/committed-economic-effects verification. Full M6 remains **PARTIAL**, including the 200-case/80-independent-family five-category held-out benchmark. The old manifest's 100 IDs represent only five generator templates crossing splits; it is retained as a legacy regression fixture, not credited as independent families. No companion repository modification, public deployment or paid model invocation occurs. See [the execution contract](ledgerguard-evaluation.md).

---

# FailureLens delivery ledger

## Current checkpoint — M2.1.1 trace-text safety

**M2.1.1: PASS for the scoped trace-text regressions and continued M2.1 acceptance. Full M2 and the full master project remain PARTIAL.**

Delivered source: `bb532f0623773f2837dd3137f7005a4c4787fa6e`, tree `d2537cfda3eb372b1d691c4469689692bcf13405`, on `main`. This follows and preserves the M2.1 acceptance documentation at `5ecde92dfe7ad45c5314def934dae46326ed8ef8`. [CI run 36478244423](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36478244423) verifies this exact code revision. A later documentation commit has separate CI; this result does not substitute for that later run.

The follow-up audit found three concrete trace publication failures: clipping before secret redaction could expose a long private-key prefix; arbitrary event types became unsanitized metadata keys; and malformed URL fallback could retain credentials. The fix sanitizes the complete bounded field before explicit clipping, withholds incomplete private keys, uses allowlisted event-count keys with visible unknown counts, and withholds malformed or unsupported network URLs. Summary and event locators record `trace-safe-text-v2.1`. The original schema, precise source positions, deterministic classifier, authorization, masks and retention contracts remain intact.

`backend/tests/test_trace_safety.py` adds 12 synthetic-canary cases, including the real ingestion API, durable worker, aggregate derivative and individually cited content endpoints. The old code failed 11 of these cases; all 12 pass with the fix. No real secret was used.

| Verification at the delivered source | Executed result |
|---|---|
| PostgreSQL/backend | 253 passed, no skips; 84.96% branch-aware coverage; existing 75% gate unchanged |
| Producer conformance | Fresh exact-revision actual Playwright/Pytest/REST Assured/JUnit/k6 fixtures; 16 contract cases passed and included in the backend count |
| Browsers | Chromium, Firefox and WebKit desktop: 11 cases each; narrow Chromium: 2 cases; all 35 passed |
| Frontend | Unit tests, strict type-check and production build passed |
| Evaluation | All five deterministic harnesses passed on the declared synthetic corpora |
| Docker | Compose validation and application image builds passed; not offline/restore acceptance |

All nine CI jobs passed without suppressing tests or increasing retry policy. Backend logs record migration through `c8f2e6a9d410`; no new schema change is required for this text-policy update. Local verification independently passed 249 tests with four PostgreSQL-only cases skipped, 82.36% branch-aware coverage, and a SQLite upgrade/downgrade/re-upgrade. Local tests replayed genuine producer artifacts from the preceding accepted source; CI regenerated them for this code revision instead of claiming the local replay was a fresh producer execution. Desktop and narrow approved/masked-evidence screenshots from the preceding M2.1 acceptance were inspected; the patch does not change UI code.

**Upgrade boundary:** existing immutable trace derivatives are not rewritten or automatically revoked by this patch. Before exposing pre-hardening evidence, follow the review/revocation, run-metadata expiry where needed, and new-run re-ingestion guidance in [the trace contract](safe-binary-evidence.md#trace-text-policy-and-upgrade-guidance). Existing exports and backups require operator review. No universal PII removal or automatic historical-data cleanup is claimed.

The M2.1 screenshot/trace workflow and real producer fixtures remain delivered, but they are not actual LedgerGuard cases. M6 still requires at least 60 real LedgerGuard controlled executions across 15 root-cause families. No companion repository, public deployment, release or paid model invocation was performed in this continuation.

The historical checkpoints below retain their original execution counts and limitations. Their acceptance did not include the newly added adversarial cases.

## Historical accepted checkpoint — M2.1 producer-verified safe binary evidence

Repository: `azerish25-ux/ai-quality-intelligence`. Default and working branch: `main`.

**M2.1: PASS for the scoped binary-evidence and producer acceptance below. Full M2, complete M5 and the full master project remain PARTIAL.**

Work started from `f84da131e4b5c2f498a2d7cf7a15fa1f324c41b2`. The accepted source checkpoint is `a2e4be3e30bfb49e60f949e9ef2f52b2cdee545f`, tree `de190a8e084c97c3814175dd7bbc6b29718d53af`. [FailureLens CI run 36475782858](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36475782858) completed successfully on September 28, 2026 at 20:01 UTC for that exact source. All nine jobs passed. A subsequent documentation commit has its own CI run; this accepted source result is not presented as that later commit's result.

### Delivered and verified

Screenshots are fully decoded under bounded codec-process limits. Reviewers submit the exact digest-checked local original, burn permanent opaque masks into an immutable metadata-stripped derivative, inspect/download approved pixels, and compare only compatible expected/actual images. Original access remains restricted. Review decisions are attributed and versioned; PostgreSQL contention allows one concurrent approval and rejects the stale reviewer.

Actual Playwright 1.63.0/schema-9 traces yield bounded, sanitized event derivatives with archive entry, line and digest citations. Unsupported versions fail explicitly. Trace excerpts remain supplemental evidence, not invented test outcomes or proof of root cause. The local inspection command verifies an original before printing pinned viewer instructions; it does not install or execute a viewer.

Authorized content endpoints recheck project ownership, approval, source/derivative digests and expiry, support bounded previews and single-range downloads, and prevent ingestion credentials from reading evidence. Revocation closes earlier derivative URLs. Real-worker expiry returns HTTP 410 and survives investigation reload without silently selecting another input.

| Verification | Executed result at the accepted source checkpoint |
|---|---|
| Backend with PostgreSQL | 241 tests passed, no skips; 84.93% branch-aware coverage; existing 75% gate retained |
| Migration | PostgreSQL upgraded through `c8f2e6a9d410` |
| Actual producer contracts | 16 tests passed against executed Playwright, Pytest, REST Assured/JUnit and k6 exports, including durable bundle ingestion and identical replay |
| Chromium desktop | 11/11 browser cases passed |
| Firefox desktop | 11/11 browser cases passed |
| WebKit desktop | 11/11 browser cases passed |
| Narrow Chromium | 2/2 browser cases passed |
| Frontend | Locked npm installation, unit tests, strict type-check and production build passed |
| Deterministic evaluation | All five classification, clustering, impact, performance and infrastructure harnesses passed on their synthetic corpora |
| Docker | Compose configuration and API/dashboard image builds passed; not full offline/backup/restore acceptance |

The 35 browser cases retain all 31 prior cases and add the binary-evidence journey in each of four lanes. No existing test was disabled, no meaningful assertion or coverage gate was lowered, and the existing browser retry policy was not increased. Actual desktop and narrow approved-evidence screenshots from the accepted source were inspected. Browser diagnostics retain screenshots for seven days; exact-revision producer artifacts retain commands, versions, independent outcome oracles and file digests for 30 days. The reproducible generator is committed; generated binary exports are CI artifacts rather than bulk Git history.

Real execution found and fixed HAR context configuration, idempotent replay after binary-source disposal, exact accessible selector names, and narrow-layout overflow from retained opaque test identities after expiry. Earlier failed/superseded runs remain historical evidence, not acceptance for the final source.

Local checks are separate: 237 backend tests passed and four PostgreSQL-only tests were skipped, with 82.32% branch-aware coverage. SQLite migration upgrade, downgrade to `b7d3a9e5c620`, and re-upgrade passed. Local results are not substituted for PostgreSQL or actual browser CI.

See [safe-binary-evidence.md](safe-binary-evidence.md) for the requirement-to-evidence map, exact APIs, producer contract, limits and rollout boundaries. Both temporary checksum-bound publication helpers are absent from the delivered tree. No companion repository, deployment, release, package publication or paid model invocation was part of this milestone.

### Remaining scope and next work

Successfully processed binary sources are disposed through the existing deletion outbox. This is not an encrypted retained-original service: failed/interrupted raw staging still follows the existing restricted-source recovery/retention policy. No universal pixel/PII sanitization, decoder OS sandbox or instant crash cleanup is claimed.

Full M2 still needs broader producer/dialect edge coverage, richer application-specific sensitive-field policy and any separately authorized encrypted retained-original profile. The new producer fixtures are honestly labeled `other_executed`. The classification corpus still has 200 synthetic cases and **zero actual LedgerGuard executions**. The next substantial milestone is M6: reproducible LedgerGuard controlled scenarios, at least 60 executed cases across 15 root-cause families, independent oracles and leakage-aware evaluation. Remaining M5 scope, optional model boundaries, complete idempotent GitHub publication, broader hardening and final master acceptance remain independently unfinished.

The sections below are historical checkpoints. Their pending checks and next-work statements describe those earlier revisions, not the accepted M2.1 source above.

## Historical M2.1 pre-publication checkpoint

The scoped implementation adds fully decoded and reviewed/masked screenshots,
version-pinned safe trace event derivatives, authorized digest-verified previews,
revocation, retention integration, conservative visual comparison, real producer
fixture generation, and API-backed dashboard acceptance cases. See
[safe-binary-evidence.md](safe-binary-evidence.md) for contracts, policy limits and
requirement-to-test mapping.

Local pre-publication checks: all 220 non-PostgreSQL backend cases then present
passed, with three existing PostgreSQL-only cases not run locally. The 20 new
binary regression cases passed. Strict frontend/browser and newly added actual
producer/PG-concurrency verification are pending remote execution at this checkpoint.
No fixture has been relabeled as a LedgerGuard execution. Full M2/master remain
PARTIAL. The historical M5.3.1 evidence below is preserved and is not substituted
for verification of this new source.

## Historical accepted checkpoint — M5.3.1 operational workflow stabilization

Repository: `azerish25-ux/ai-quality-intelligence`. Default and working branch: `main`.

**M5.3.1: PASS for the scoped stabilization acceptance below. The full master project and complete M5 remain PARTIAL.**

Development started from `eb577742114b403f055dd0f4e961215644786989`. The first fully accepted source checkpoint is `f4c3cf217f91a9c67b3b3b124ceae7d12151ca0b`, tree `09ca91a227e65d0d9fae2e9080ec72616fffaa01`. [FailureLens CI run 36451042191](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36451042191) completed successfully for that exact commit on September 28, 2026. All eight jobs passed: PostgreSQL/backend, frontend, deterministic evaluation, Docker configuration/build, and four browser lanes.

This documentation records an already executed source checkpoint. A subsequent documentation commit has its own CI execution; the source checkpoint's result is not represented as that later commit's result.

### Delivered and verified

The run-detail API/client envelope is contract-tested, including nullable exception types and lifecycle metadata. Old investigation links survive the bounded recent-run list, reloads, and Back/Forward. Explicit unavailable or mismatched-project links report an error instead of selecting another investigation. Demo loading preserves the exact returned project/run, delayed requests cannot overwrite a newer selection, and reopening an already selected run reloads its panels. Compact navigation preserves focus and the target viewport. Real-worker evidence expiry, HTTP 410, expired investigation reload, password rotation, and session revocation pass through the real API and PostgreSQL.

| Verification | Executed result at the accepted source checkpoint |
|---|---|
| Backend with PostgreSQL | 203 tests passed; 85.69% branch-aware coverage; migration through `b7d3a9e5c620` |
| Chromium desktop | 10/10 browser cases passed |
| Firefox desktop | 10/10 browser cases passed |
| WebKit desktop | 10/10 browser cases passed |
| Narrow Chromium | 1/1 browser case passed |
| Frontend | Locked npm installation, unit tests, strict type-check and production build passed |
| Deterministic evaluation | Classification, clustering, impact, performance and infrastructure harnesses passed |
| Docker | Compose configuration validation and API/dashboard image builds passed; not a claim of full offline/restore acceptance |

The 31 browser cases retain all original 19 cases and add four regression scenarios in each desktop browser. No tests were skipped or disabled to obtain acceptance, no meaningful assertion or threshold was reduced, and no additional retry policy was introduced. Browser databases and processes are isolated per lane. Successful desktop and narrow-layout screenshots were inspected and are retained in the run's browser-diagnostics artifacts under the existing seven-day policy.

Local verification is separate: 200 backend tests passed, three PostgreSQL-only tests skipped, with 85.59% branch-aware coverage. The focused API/authentication/operations subset passed 43 tests. All five deterministic harnesses passed locally on their committed synthetic fixtures.

See [the scoped requirement matrix and source evidence](operations-stabilization.md) for implementation paths and test coverage. Temporary checksum-bound publication helpers were removed from the delivered tree. No companion repository, public deployment, release, package publication or paid model invocation was part of this change.

## Historical M5.3.1 full-project status and next work

M1, M3 and M4 retain their previously recorded delivered status. M2 remains partial: real producer-pinned fixtures, reviewed/masked screenshot derivatives, safe trace derivatives and controlled artifact access still need completion. M6 still has 200 synthetic classification cases and **zero actual LedgerGuard executions**; synthetic scores do not satisfy the mandatory real-execution provenance requirement. The optional provider boundary, complete idempotent GitHub publication, broader hardening/operations and final master acceptance also remain unfinished. Remaining review-workflow scope is not declared complete merely because M5.3.1 passes.

The next substantial implementation work is unfinished M2 safe-evidence functionality, followed by real LedgerGuard-backed M6 evaluation, without weakening the restored CI baseline.

## Earlier preserved history

The entire preceding ledger is preserved byte-for-byte in [PROGRESS-through-M5.3.md](PROGRESS-through-M5.3.md), with original Git blob `a314c22fc4e53ff966d24d1263b1027f90a2d649`. Its local-only delivery warnings, pending browser checks and older milestone overlays describe historical checkpoints, not the current delivered stabilization. Earlier benchmark and failed/superseded CI evidence has not been recast as current acceptance.
