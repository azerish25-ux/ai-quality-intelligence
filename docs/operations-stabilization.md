# M5.3.1 — Operational workflow stabilization

## Scope and source

Development started from `eb577742114b403f055dd0f4e961215644786989` on `main`. Its CI run `36440635256` passed backend/PostgreSQL, frontend, deterministic evaluation and Docker configuration/build checks, but recorded 10 passing and 9 failing browser tests. The failures were impact-run selection in three browsers, old-investigation retention navigation in three browsers, history navigation in Firefox/WebKit, and narrow-layout section navigation.

Source implementation was published as `652943c23d6f366c87edd60e4663c629dc386b1b`. A temporary checksum-bound publisher verified the exact source preimages/postimages, passed the locked frontend unit/type-check/build commands and the 43-test API/authentication/operations subset, then performed a non-force push. The temporary publisher and its payload have been removed. They are not an application feature or a persistent automation.

## Corrected behavior

- The existing run-detail wire envelope (`run`, `failure_types`, `failure_count`) now has an explicit FastAPI response schema. The TypeScript client validates and unwraps that envelope rather than treating it as a flat run. Lifecycle fields therefore reach old-run lookup and evidence-expiry polling correctly. Failures with no exception type remain counted in an explicit `unknown` bucket.
- Project/run navigation captures selection intent before asynchronous requests. Old runs are fetched individually when absent from the bounded recent list. Explicit unavailable or mismatched-project links report an error rather than silently selecting another investigation. Stale requests cannot restore a superseded project.
- Demo loading uses the exact project and run returned by the seed endpoint even after newer passing or change-only runs exist. Impact tests navigate to their actual project/run instead of depending on project-list ordering.
- Back/Forward restoration no longer treats the currently loaded list as the complete resource catalogue. History filters and old investigation links remain addressable.
- In-page section navigation is separate from investigation navigation, closes the compact menu, moves keyboard focus and scrolls to the target without a competing smooth-scroll/popstate transition.
- Retention browser verification reads the real API envelope and continues to require worker-driven expiry, an evidence HTTP 410, and an understandable expired investigation after reload.

## Acceptance evidence

Local focused verification: 43 API, authentication and operations tests passed. This is separate from full PostgreSQL and browser acceptance.

The ordinary `FailureLens CI` workflow is the authority for the exact delivered SHA. The expanded suite retains the existing 19 browser cases and adds four real-API regression scenarios across Chromium, Firefox and WebKit (31 total cases). They cover demo selection with multiple projects/newer runs, Back/Forward to runs outside the recent page, unavailable/mismatched-project URLs, and delayed real project responses. The latency test delays a response obtained from the real API; it does not fabricate response data.

Successful dashboard and narrow-layout screenshots are written into `frontend/test-results` and retained by the existing browser-diagnostics artifact policy. Tests still assert real behavior; screenshots are supplementary evidence. The demo regression also checks uncaught browser errors.

Full browser acceptance for this source must be read from its actual CI execution; no previous green run is substituted. No tests, meaningful assertions or quality thresholds have been disabled or reduced, and no extra retry policy was introduced.

## Remaining master scope

This is a bounded M5.3 stabilization change, not full-project completion. Unfinished M2 safe binary evidence/producer fixtures, real LedgerGuard-backed M6 evaluation, optional provider boundary, live idempotent GitHub reports and broader operational acceptance remain open. The classification corpus still contains 200 synthetic cases and zero actual LedgerGuard executions.
