# Requirement-to-evidence matrix

`PASS` means implemented behavior has executable evidence. `PARTIAL` means useful implementation exists but the full master requirement is not closed.

| ID | Requirement | Status | Implementation/evidence |
|---|---|---|---|
| R-DELIVERY-01 | Resolve canonical repository and preserve history | PASS | `docs/PROGRESS.md`; non-force Git Data API delivery |
| R-DATA-01 | Explicit relational model | PASS | `models.py`; Alembic initial + durable-ingestion migrations |
| R-INGEST-00 | Actual report -> durable job -> run/evidence -> automatic analysis | PASS | `storage.py`, `service.py`, `jobs.py`, raw API, `test_durable_ingestion.py`, browser E2E |
| R-INGEST-01 | Normalized ingestion with idempotency | PASS | `ingest_normalized`; service/API tests |
| R-INGEST-02 | JUnit XML | PARTIAL | Parser, nested suites, safe XML, raw/ZIP path, executed integration tests; broader producer dialect fixtures remain |
| R-INGEST-03 | Playwright JSON | PARTIAL | Suite/spec/attempt parser, retries, attachments metadata, raw/ZIP path, tests; pinned real producer fixture remains |
| R-INGEST-04 | All eleven specified input types | FAIL | `docs/input-compatibility.md` |
| R-STORAGE-01 | Bounded restricted source storage and immutable digest | PASS | streamed content-addressed storage, permissions, size/SHA revalidation, tests |
| R-SEC-01 | Declared text redaction | PASS | `redaction.py`; redaction/canary tests |
| R-SEC-02 | Binary/screenshot/trace restriction and safe derivative | FAIL | Original source restriction exists; review/mask and safe binary derivatives not implemented |
| R-EVIDENCE-01 | Precise evidence records and digests | PARTIAL | immutable source digest, typed locators, excerpts, parser warnings; semantic support validator incomplete |
| R-ANALYSIS-01 | Exactly five categories | PASS | enums/schema/rules/tests |
| R-ANALYSIS-02 | Safe abstention and contradiction policy | PASS | deterministic rules and dangerous-downgrade tests |
| R-ANALYSIS-03 | Explainable clustering | FAIL | fingerprint only; cluster persistence/scoring/revisions pending |
| R-HISTORY-01 | Honest historical flake statistics | PARTIAL | prior-only/reviewed-history gate; full rates and denominators pending |
| R-IMPACT-01 | Change-impact test selection | FAIL | Not implemented |
| R-REVIEW-01 | Human review revision history | PARTIAL | append-only events/version conflict; identity/roles pending |
| R-API-01 | Typed versioned API | PARTIAL | raw/normalized ingestion, status/retry/cancel, runs/failures/analysis/review; full operation set pending |
| R-JOBS-01 | Durable leased jobs | PASS | transactional queueing, `SKIP LOCKED`, leases/heartbeat, recovery, retry/dead-letter, cancellation safety, real handler/tests |
| R-GITHUB-01 | Reusable Action | PARTIAL | durable one-shot Action and sanitized report output; live PR publication pending |
| R-UI-01 | Working React dashboard | PARTIAL | real API upload/status/retry/cancel/run/failure/evaluation UI and Chromium journey; all master views/roles pending |
| R-CORPUS-01 | At least 200 labeled cases | PASS | manifest: 200 synthetic cases |
| R-CORPUS-02 | At least 60 actual LedgerGuard cases | BLOCKED | 0 actual cases; companion scenario execution remains future M6 work |
| R-EVAL-01 | Dangerous-dismissal and five-class metrics | PASS | executable harness and committed report |
| R-EVAL-02 | Independent/generalizable evaluation claim | NOT RUN | Public synthetic corpus only; limitation documented |
| R-OPS-01 | Docker startup and PostgreSQL | PARTIAL | Compose, migrations, worker, CI PostgreSQL browser journey; broader recovery/load evidence pending |
| R-CI-01 | Verification workflows | PARTIAL | backend, evaluation, frontend, Chromium, and Docker jobs committed; status is exact-revision dependent |
