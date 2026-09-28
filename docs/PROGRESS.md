# FailureLens delivery ledger

## Current checkpoint — M5.3.1 operational workflow stabilization

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

## Full-project status and next work

M1, M3 and M4 retain their previously recorded delivered status. M2 remains partial: real producer-pinned fixtures, reviewed/masked screenshot derivatives, safe trace derivatives and controlled artifact access still need completion. M6 still has 200 synthetic classification cases and **zero actual LedgerGuard executions**; synthetic scores do not satisfy the mandatory real-execution provenance requirement. The optional provider boundary, complete idempotent GitHub publication, broader hardening/operations and final master acceptance also remain unfinished. Remaining review-workflow scope is not declared complete merely because M5.3.1 passes.

The next substantial implementation work is unfinished M2 safe-evidence functionality, followed by real LedgerGuard-backed M6 evaluation, without weakening the restored CI baseline.

## Preserved history

The entire preceding ledger is preserved byte-for-byte in [PROGRESS-through-M5.3.md](PROGRESS-through-M5.3.md), with original Git blob `a314c22fc4e53ff966d24d1263b1027f90a2d649`. Its local-only delivery warnings, pending browser checks and older milestone overlays describe historical checkpoints, not the current delivered stabilization. Earlier benchmark and failed/superseded CI evidence has not been recast as current acceptance.
