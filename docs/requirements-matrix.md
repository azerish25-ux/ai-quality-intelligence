# Requirement-to-evidence matrix

This matrix summarizes the current revision against the master contract. `PASS` means executed evidence exists in this environment; `PARTIAL` means useful implementation exists but the full requirement is not closed.

| ID | Requirement | Status | Implementation/evidence |
|---|---|---|---|
| R-DELIVERY-01 | Resolve canonical repository and preserve history | PASS | `docs/PROGRESS.md`; Git Data API fast-forward workflow |
| R-DATA-01 | Explicit relational model | PASS | `backend/src/failurelens/models.py`; generated Alembic migration |
| R-INGEST-01 | Normalized ingestion with idempotency | PASS | `service.ingest_normalized`; service/API tests |
| R-INGEST-02 | JUnit XML | PARTIAL | parser + safe XML tests; producer breadth incomplete |
| R-INGEST-03 | Playwright JSON | PARTIAL | nested suite/attempt parser + tests; pinned real producer execution pending |
| R-INGEST-04 | All eleven specified input types | FAIL | Matrix in `docs/input-compatibility.md` |
| R-SEC-01 | Declared text redaction | PASS | `redaction.py`; redaction and canary tests |
| R-SEC-02 | Binary/screenshot/trace restriction | FAIL | Not implemented |
| R-EVIDENCE-01 | Precise evidence records and digests | PARTIAL | evidence table, locators, excerpts, digests; semantic citation validator incomplete |
| R-ANALYSIS-01 | Exactly five categories | PASS | enum/schema/rules/tests |
| R-ANALYSIS-02 | Safe abstention and contradiction policy | PASS | analysis rules and dangerous-downgrade test |
| R-ANALYSIS-03 | Explainable clustering | FAIL | fingerprint only; cluster persistence/scoring pending |
| R-HISTORY-01 | Honest historical flake statistics | PARTIAL | reviewed-history gate; full rates/denominators pending |
| R-IMPACT-01 | Change-impact test selection | FAIL | Not implemented |
| R-REVIEW-01 | Human review revision history | PARTIAL | append-only events/version conflict; roles pending |
| R-API-01 | Typed versioned API | PARTIAL | core endpoints/OpenAPI; full operation set pending |
| R-JOBS-01 | Durable leased jobs | PARTIAL | table/claim/retry/dead-letter tests; major work still synchronous |
| R-GITHUB-01 | Reusable Action | PARTIAL | composite Action/report output; live publication pending |
| R-UI-01 | Working React dashboard | PARTIAL | API-backed overview/runs/failure/evaluation source; browser build/E2E unverified locally |
| R-CORPUS-01 | At least 200 labeled cases | PASS | manifest: 200 synthetic cases |
| R-CORPUS-02 | At least 60 actual LedgerGuard cases | BLOCKED | 0 actual cases; companion is not yet an executable full-stack source |
| R-EVAL-01 | Dangerous-dismissal and five-class metrics | PASS | executable harness and committed report |
| R-EVAL-02 | Independent/generalizable evaluation claim | NOT RUN | Public synthetic corpus only; limitation documented |
| R-OPS-01 | Docker startup and PostgreSQL | PARTIAL | Compose/images/migration source; local Docker run unavailable |
| R-CI-01 | Verification workflows | PARTIAL | workflow committed; delivered-revision run must be inspected after push |
