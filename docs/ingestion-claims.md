# Durable ingestion claim ownership

The ingestion worker binds an immutable claim to the job ID, project, kind,
worker owner and attempt generation returned by claim admission. The captured
identity is not reconstructed from refreshed ORM fields. Reusing the same worker
name does not authorize an older attempt to act as its successor.

Claim admission uses a conditional database update, so a stale candidate cannot
overwrite a newer claim. PostgreSQL also uses `FOR UPDATE SKIP LOCKED` when selecting
candidates; SQLite does not implement that selection lock, making the conditional
update necessary. Provider attempts and retention processing retain their separate
execution contracts. No provider invocation or external publication is added.

## Transaction boundaries

Ingestion processing attaches a session-local guard to business flushes, commits
and direct ORM DML. A conditional update checks the captured identity and acquires
the job row's write lock before the transaction publishes changes. The update
preserves the job's timestamp; checking a fence is not a heartbeat. The ingestion
must belong to the captured project and current job. Public ingestion heartbeat,
completion and failure helpers also verify their supplied target and generation.

The lease must still be valid when the database lock is actually acquired,
including after a blocked statement returns. Once acquired, an uninterrupted
transaction may finish after the clock reaches expiry: a successor cannot claim
the locked row. A later transaction must check ownership and expiry again.
An expired lease cannot be revived by a heartbeat. This is a transaction ownership
rule, not a claim that processing always finishes within the lease duration.

A fence belongs to its exact transaction/savepoint lifetime. Rollback invalidates
cached ownership. Successful savepoint release also conservatively drops the
cache; a later operation may reject an expired lease even though the database
retained its lock. The current ingestion path does not rely on such lock promotion.
[PostgreSQL lock lifetime](https://www.postgresql.org/docs/17/explicit-locking.html)
and [SQLAlchemy session events](https://docs.sqlalchemy.org/en/20/orm/events.html)
describe the underlying mechanisms.

## Recovery and side effects

Losing ownership stops the old attempt from committing further source, analysis,
ingestion or job mutations. Work committed while it owned an earlier transaction
remains intact; the successor reuses the existing run rather than duplicating it.
Cancellation remains terminal. An owned malformed job receives bounded terminal
diagnostics without altering a foreign ingestion. Expired ingestion jobs that have
exhausted their allowed attempts receive a bounded terminal transition instead of
remaining running forever; provider and retention jobs are excluded from that path.

File creation is not a database transaction. Private storage remains content-bound
and the existing deletion outbox remains transactional. Deletion flushing occurs
after the worker's own successful terminal commit, under its separate project and
live-reference checks. The claim guard is not a sandbox for arbitrary code using
an independent database connection, nor a replacement for project authorization.

## Evidence and limits

At published `5356ac6`, two deterministic two-session SQLite cases reproduced a
predecessor completing a successor's job, including a reused worker name. Three
legitimate controls passed. Resuming the successor after the overwrite could leave
the job succeeded while its ingestion stayed running. The original failed evidence
is retained. The implementation adds current-owner and interruption controls, plus
independently authored PostgreSQL interleavings with bounded database timeouts.

Local collection does not execute PostgreSQL. Exact-source hosted execution,
source-bound coverage and the unchanged strict branch gates remain required.
The delivery ledger identifies which revision was actually measured; this contract
alone does not establish complete project acceptance.
