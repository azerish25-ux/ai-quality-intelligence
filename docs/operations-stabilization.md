# M5.3.1 — Operational workflow stabilization

## Scope and verified source

Development started on `main` from `eb577742114b403f055dd0f4e961215644786989`. Its CI run `36440635256` passed the non-browser jobs but recorded 10 passing and 9 failing browser cases: impact-run selection in three browsers, old-investigation retention navigation in three browsers, history navigation in Firefox/WebKit, and narrow-layout section navigation.

**Scoped stabilization acceptance: PASS.** The first fully accepted source is `f4c3cf217f91a9c67b3b3b124ceae7d12151ca0b`, Git tree `09ca91a227e65d0d9fae2e9080ec72616fffaa01`. [CI run 36451042191](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36451042191) passed all eight jobs for that exact SHA on September 28, 2026. This is source-checkpoint evidence, not an assertion about a later documentation commit's separate CI result.

Source delivery includes `652943c23d6f366c87edd60e4663c629dc386b1b` and the repeated-selection correction `064a46f976da6f6ea00c21831d83b167466496c7`. Exact checksum-bound publication helpers performed non-force pushes after checks and were subsequently removed. They are not application features or persistent automations.

## Corrections

The existing run-detail envelope (`run`, `failure_types`, `failure_count`) now has an explicit FastAPI response schema. The TypeScript client validates and unwraps it instead of treating the outer envelope as a flat run. Old-run lookup and expiry polling receive their actual lifecycle fields. Failures with no exception type remain counted in an explicit `unknown` bucket rather than failing response validation.

Project/run navigation captures selection intent before asynchronous work, loads an old run individually when it is outside the bounded recent list, and rejects stale responses. Invalid or mismatched-project links retain an explicit unavailable state rather than silently becoming a different investigation. Back/Forward restoration does not treat currently loaded arrays as the complete resource catalogue. Reopening the same selected run increments a navigation revision so cleared panels reload even when the run ID is unchanged.

Demo loading selects the exact project/run returned by the seed API, including when newer passing or change-only runs exist. The impact journey navigates explicitly to its own project/run. Compact section links are separate from investigation routing: they close the menu, move keyboard focus and scroll to the target without competing smooth-scroll/popstate transitions.

Retention verification reads the real API envelope and executes the complete policy preview/save/cleanup path, then checks real-worker expiry, an evidence HTTP 410, and the expired investigation after reload. Account verification continues to use real cookies for password rotation and individual session revocation.

## Requirement-to-evidence matrix

All rows below were exercised by the accepted CI source checkpoint, not merely inferred from source presence.

| ID | Required behavior | Implementation and regression evidence | Status |
|---|---|---|---|
| M531-CONTRACT | Preserve and correctly consume the actual run-detail envelope and lifecycle fields | `backend/src/failurelens/api.py`, `schemas.py`; `backend/tests/test_api.py` envelope/OpenAPI and nullable-exception tests; `frontend/src/api.ts`, `operations.test.ts` | PASS |
| M531-OLD-LINK | Resolve an investigation outside the recent-run page; preserve it on reload and Back/Forward | `frontend/src/App.tsx`; `e2e/navigation-regressions.spec.ts` old investigation journey; `e2e/operations.spec.ts` with 101 newer fixture runs | PASS |
| M531-UNAVAILABLE | Missing or mismatched-project run URLs must not silently select another investigation | `App.tsx`; `navigation-regressions.spec.ts` missing/cross-project URL test | PASS |
| M531-DEMO-IMPACT | Select the seed API's actual run and the impact journey's actual project/run | `App.tsx`; `backend/tests/test_api.py` repeated-seed test; `navigation-regressions.spec.ts`, `durable-ingestion.spec.ts` | PASS |
| M531-RACE-REOPEN | Late project responses cannot undo selection; repeated Open run reloads panels | `App.tsx`; delayed-real-response regression and repeated Open run assertion in `durable-ingestion.spec.ts` | PASS |
| M531-HISTORY | History filters and investigation state survive navigation across supported desktop browsers | `e2e/accessibility-navigation.spec.ts`, `navigation-regressions.spec.ts` | PASS |
| M531-RETENTION | Real-worker expiry, HTTP 410, explanatory UI and reload of the same investigation | `e2e/operations.spec.ts` retention journey with PostgreSQL/API/worker | PASS |
| M531-ACCOUNT | Password rotation revokes old credentials and individual session revocation works | `e2e/operations.spec.ts` real-cookie account journey; existing backend operations tests | PASS |
| M531-NARROW | Section target visible and focused, compact menu closed, no horizontal overflow | `App.tsx`; `e2e/narrow-layout.spec.ts`, actual 390 by 844 screenshot | PASS |
| M531-DELIVERY | Source pushed on main, helpers absent, all verification lanes executed | Accepted source SHA/tree and CI run above; `.github/workflows/ci.yml` | PASS |

## Executed verification

| CI job | Job ID | Result |
|---|---|---|
| backend | 109025819942 | 203 tests passed; 85.69% branch-aware coverage; PostgreSQL migration passed |
| frontend | 109025819911 | Locked install, unit tests, strict type-check and production build passed |
| evaluation | 109025819517 | All five deterministic harnesses passed |
| docker-config | 109025820024 | Compose model validation and API/dashboard image builds passed |
| browser-e2e (chromium-desktop) | 109025819693 | 10 passed |
| browser-e2e (firefox-desktop) | 109025820275 | 10 passed |
| browser-e2e (webkit-desktop) | 109025819946 | 10 passed |
| browser-e2e (chromium-narrow) | 109025820062 | 1 passed |

The expanded browser suite retains all 19 original cases and adds four real-API scenarios across three desktop browsers, for 31 cases. Each browser lane has its own PostgreSQL service, API and worker. The delayed-response test returns the actual API response after a controlled delay; it does not manufacture project or run data. No tests, meaningful assertions or quality thresholds were disabled or reduced, and no extra retry policy was introduced.

Local evidence is separate: 43 focused API/authentication/operations tests passed; the full local backend run passed 200 tests, skipped three PostgreSQL-only tests and measured 85.59% branch-aware coverage. All five local deterministic harnesses passed their committed synthetic fixtures. Local skips are not represented as local PostgreSQL verification; PostgreSQL acceptance comes from the CI execution above.

Successful desktop dashboard and narrow settings screenshots were downloaded and visually inspected. The run retains `failurelens-browser-diagnostics-chromium-desktop`, `-firefox-desktop`, `-webkit-desktop` and `-chromium-narrow` artifacts for seven days. Screenshots supplement behavioral assertions and do not replace them. The successful demo regression also asserts absence of uncaught browser page errors.

## Remaining master scope

This completes the bounded M5.3.1 stabilization, not the whole master project or every M5 requirement. M2 safe binary evidence and producer-pinned fixtures, real LedgerGuard-backed M6 evaluation, optional provider boundaries, live idempotent GitHub reports and broader operational acceptance remain open. The classification corpus still contains 200 synthetic cases and zero actual LedgerGuard executions. Docker image builds are not full runtime, offline, backup/restore or production-deployment proof.

See [the current delivery ledger](PROGRESS.md) and [preserved historical ledger](https://github.com/azerish25-ux/ai-quality-intelligence/blob/2de918e5709d12afba2e415edd3c020fac83ed7c/docs/PROGRESS-through-M5.3.md). Failed or superseded intermediate checks remain historical records rather than being relabeled successful.
