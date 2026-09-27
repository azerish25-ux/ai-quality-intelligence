# Requirement-to-evidence matrix

`PASS` means the required behavior has executable evidence. `PARTIAL` means useful implementation exists but the full master requirement is not closed. The matrix intentionally distinguishes adapter foundations from producer-backed, safety-complete support.

| ID | Requirement | Status | Implementation/evidence |
|---|---|---|---|
| R-DELIVERY-01 | Resolve canonical repository and preserve history | PASS | Canonical repository/default branch recorded; this checkpoint was developed from exact source export `3ba6cc6a…`; final remote delivery remains subject to exact-head verification |
| R-DATA-01 | Explicit relational model | PASS | `models.py`; Alembic initial, durable-ingestion, and `run_inputs` migrations |
| R-INGEST-00 | Actual report -> durable job -> run/evidence -> automatic analysis | PASS | `storage.py`, `service.py`, `jobs.py`, raw API, durable integration tests, browser E2E source |
| R-INGEST-01 | Normalized ingestion with idempotency | PASS | `ingest_normalized`; one input independent of observation count; service/API tests |
| R-INGEST-02 | JUnit XML | PARTIAL | Nested suites, properties, safe XML, raw/ZIP integration and adversarial tests; broader executed producer-dialect matrix remains |
| R-INGEST-03 | Playwright JSON | PARTIAL | Suites/specs/attempts/retries/attachments and nested hierarchy tests; pinned real-producer fixture remains |
| R-INGEST-04 | All eleven specified input families | PARTIAL | Versioned adapter registry includes pytest, REST Assured evidence, k6, console, HAR/network, screenshots, traces, GitHub metadata and changed files; producer-pinned fixtures and depth limits remain open |
| R-INGEST-05 | Honest manifest/shard completeness | PASS | Manifest `2.0`, persisted `run_inputs`, required/optional semantics, missing/rejected/restricted states, and regression tests proving observations are not inputs |
| R-STORAGE-01 | Bounded restricted source storage and immutable digest | PASS | Streamed content-addressed storage, permissions, size/SHA revalidation and archive/resource tests |
| R-SEC-01 | Declared text redaction | PASS | `redaction.py`; token/authorization/cookie/PII rules, terminal controls, URL query sanitization, canary tests |
| R-SEC-02 | Binary/screenshot/trace restriction and safe derivative | PARTIAL | Screenshot/trace originals are restricted and yield bounded metadata/index records; immutable masked image derivative and richer safe trace derivative are not implemented |
| R-EVIDENCE-01 | Precise evidence records and digests | PARTIAL | Per-input parser provenance, digests, JSON/XML/text locators and warnings exist; publication-grade semantic-support validator/source-map verification remains open |
| R-ANALYSIS-01 | Exactly five categories | PASS | Enums/schema/rules/tests |
| R-ANALYSIS-02 | Safe abstention and contradiction policy | PASS | Deterministic rules and dangerous-downgrade tests; incomplete runs constrain analysis |
| R-ANALYSIS-03 | Explainable clustering | FAIL | Fingerprint only; cluster persistence/scoring/revisions pending |
| R-HISTORY-01 | Honest historical flake statistics | PARTIAL | Prior-only/reviewed-history gate; full rates and denominators pending |
| R-IMPACT-01 | Change-impact test selection | FAIL | Changed-file evidence is ingested, but selection/recommendation logic is not implemented |
| R-REVIEW-01 | Human review revision history | PARTIAL | Append-only events/version conflict; identity/roles and richer corrections pending |
| R-API-01 | Typed versioned API | PARTIAL | Raw/normalized ingestion, status/retry/cancel, runs/failures/analysis/review and `GET /runs/{id}/inputs`; full operation set pending |
| R-JOBS-01 | Durable leased jobs | PASS | Transactional queueing, `SKIP LOCKED`, leases/heartbeat, recovery, retry/dead-letter, cancellation safety and real handler tests |
| R-GITHUB-01 | Reusable Action | PARTIAL | Durable one-shot Action and sanitized report output; live idempotent PR publication and stale-head reconciliation pending |
| R-UI-01 | Working React dashboard | PARTIAL | Real API upload/status/retry/cancel/run/failure/evaluation UI plus persisted input/completeness panel; all master views/roles pending |
| R-CORPUS-01 | At least 200 labeled cases | PASS | Manifest: 200 synthetic cases |
| R-CORPUS-02 | At least 60 actual LedgerGuard cases | BLOCKED | 0 actual cases; companion scenario execution remains future M6 work |
| R-EVAL-01 | Dangerous-dismissal and five-class metrics | PASS | Executable harness and committed report |
| R-EVAL-02 | Independent/generalizable evaluation claim | NOT RUN | Public synthetic corpus only; limitation documented |
| R-OPS-01 | Docker startup and PostgreSQL | PARTIAL | Compose, migrations, worker and CI PostgreSQL/browser paths; broader recovery/load/backup evidence pending |
| R-CI-01 | Verification workflows | PARTIAL | Backend, evaluation, frontend, Chromium and Docker jobs exist; exact delivered revision must be inspected before claiming CI success |
