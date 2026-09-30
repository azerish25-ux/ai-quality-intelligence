# M5.3 operational lifecycle

This checkpoint implements account/session administration, project evidence retention,
full-dataset review queries and policy-governed audit CSV exports. It does not claim
that M2, all of M5, M6, or the complete master specification is finished.

## Rollout and defaults

Apply `cd backend && alembic upgrade head` before starting the new API and worker.
The head is `b7d3a9e5c620`, following `a4f6e8c2d901`. In addition to lifecycle tables,
the migration reconciles the existing evidence parser-version width and an index
on the already-unique performance baseline link. A downgrade restores the previous
schema; it cannot restore expired evidence bytes or erased text.

**Review retention before starting the worker against an existing database.**
The default policy is 7 days for restricted sources, 90 days for safe evidence
bodies, and 365 days for project audit events. Defaults apply to existing projects
as well as new ones. The API can be started without the worker to inspect and
change each project's policy first. Age uses persisted `created_at`, not an
untrusted timestamp supplied inside a report. Allowed durations are 1–3,650 days;
restricted source retention cannot exceed evidence retention.

The worker scans at most 10 due projects per sweep, at most once per minute, and
revisits a project after five minutes. It processes at most 20 records per resource
class per cleanup slice. Empty projects do not generate no-op jobs or audit events.
A stopped worker does not enforce elapsed retention deadlines: monitor worker
health, job progress and storage-deletion failures. A running ingestion defers
cleanup without consuming its retry budget.

## Retention preview, authorization and cleanup

Project viewers may inspect the saved policy. Only project administrators can
change it, preview affected data, queue cleanup or inspect cleanup jobs/tombstones.
Settings includes proposed-policy preview, an explicit acknowledgement, optimistic
policy revisions, saved-policy cleanup preview and a separate confirmation button.
The manual cleanup API requires a matching policy revision, a cutoff no more than
15 minutes old, and a digest of the actual candidate IDs/counts. A changed candidate
set or policy produces a conflict rather than executing a different deletion plan.
Future cutoffs are rejected. Once saved, policies are enforced automatically;
manual confirmation is not required for every scheduled sweep.

The run is the evidence-body expiration unit. Expiry clears the run's evidence
excerpts/observations/locators, failure messages/features, execution details,
analysis prose/claims/provenance, review free text, derivative metadata and the
associated current-run analytical text described in `retention._scrub_run`.
Related cluster revision text is also removed to avoid retaining copied excerpts.
Recorded outcomes, test identities, run/repository metadata, numerical measurements,
opaque references, digests, recorded categories, and attributed decision/version
history remain. This is evidence retention, **not complete personal-data erasure**
of all metadata, independent records, or downstream historical aggregates.

Logical expiry and a deletion outbox commit before files are unlinked. Safe
storage namespaces are project-specific. Each deletion rejects traversal/symlinks
and checks all live source/derivative references, including references outside the
project. Shared bytes are retained while a live reference needs them. A crash
before unlink or after unlink but before the completion commit is retryable;
missing bytes do not cause a retry to resurrect or republish the evidence.
Blocked unsafe paths produce an explicit partial job status, not silent success.
Already-expired ingestion IDs cannot be retried or replayed to recreate orphaned
sources; a genuinely new import must have a new external ID or attempt.

Tombstones retain opaque resource identity, expiry time, reason code and policy
revision. Project audit expiry replaces deleted rows with these minimal records.
Global account/security audit events are **not** pruned by a project's policy.
Their retention, database backups, logs outside this application, previously
exported reports and files copied elsewhere require a separate operator process.
These controls are not a secure-erase guarantee against storage or database
administrators and do not retroactively recall material already delivered to a user.

## Expired evidence and advisory output

Authorized evidence lookups return HTTP 410 with `evidence_expired`; unauthorized
cross-project requests retain not-found behavior. Historical analysis responses
keep a separate recorded category but publish `insufficient_evidence`, no current
confidence/citations, and an explicit expiry state. Regeneration cannot treat an
expired run as fresh evidence. Reassuring release advice remains blocked. Markdown
reports show `EVIDENCE_EXPIRED` and `HOLD_FOR_REVIEW`; expired history cannot provide
known-flake reassurance. The workspace and deep-linked older runs expose expiry
rather than broken previews. API responses use private/no-store caching and
`nosniff`; the dashboard refreshes a selected run's expiry status periodically.

Analysis detail responses also use `evidence_state=unavailable` when retained
metadata exists but current bytes, integrity, approval or required prior reviewed
support can no longer be verified. They keep `recorded_category` separately,
withhold current claims and confidence, and block new reassuring reviews. This
read-only projection does not rewrite the stored analysis or append a review.
Evidence metadata inspection verifies the copied excerpt/observation against its
current immutable derivative; unavailable or corrupt material returns 409.

Overview category totals describe recorded analysis revisions. Review-queue
category filters, counts and pagination describe recorded latest analyses, while
their expiry decoration reflects the owning run's retention state. These are
historical index fields, not current verification results. Opening an investigation
refreshes current validity; submitting a reassuring review checks it again within
the review transaction. Same-project human citations may refer to other runs, but
each cited item must be currently verifiable in its own actual scope.
Request-local caching holds at most 128 successful derivative bodies and 4 MiB of
payload, with least-recently-used eviction. Failures are not cached; oversized
valid bodies are read without cache retention. At most 16 exact-scope history
contexts are retained, and contexts with more than 256 review IDs bypass the cache
intact. Eviction causes recomputation/revalidation and never truncates evidence or
history. These limits bound additional retained cache data, not the full request's
ordinary database/history computation. Availability is checked during the current
request/transaction and cannot guarantee that an operator leaves files unchanged
afterward.

## Account and session operations

`GET /api/v1/auth/sessions` returns only the signed-in user's session metadata.
`POST /api/v1/auth/sessions/{id}/revoke` revokes an owned session. Password changes
require the current password, rotate the current browser cookie and revoke all
old sessions and recovery tokens. The new password minimum is 14 characters.

System administrators, not merely project administrators, can inspect an account's
sessions, revoke all sessions, activate/deactivate it, or issue recovery. These
mutations require reauthentication and a reason; account changes/recovery also
require the current lifecycle version. Account and session locks follow a stable
order. The last active system administrator cannot be deactivated. Startup only
creates the first administrator in an empty users table: it never reactivates or
promotes an existing user and changing bootstrap environment variables cannot
create an additional privileged account later.

Recovery is an **administrator-assisted credential reset**, not a public
forgot-password form. The administrator must independently verify the recipient.
Issuance immediately invalidates the old password and sessions, returning a
cryptographically random token once. Only its hash is stored; it expires after
15 minutes and can be consumed once. Successful redemption revokes old sessions
again and requires a fresh sign-in. Tokens/passwords are absent from URLs, normal
audit details and validation-error payloads. Keep the displayed token private.

For loss of the only administrator credential, an already trusted local database
operator can explicitly run:

```bash
failurelens recover-account --username '<existing-username>' \
  --reason 'Identity verified through the operator recovery process' \
  --confirm-local-administrator-access
```

An inactive account additionally requires `--activate`. This command never creates
an account or promotes its role. It emits a one-time recovery token to the trusted
terminal and audits the actor as a local database operator, **not a verified web
identity**. It is not exposed through HTTP or invoked by bootstrap/startup.

## Full-dataset review and audit export

`GET /api/v1/projects/{id}/review-queue/page` selects the latest analysis for every
failure and latest review decision using SQL, then filters and paginates. The
response includes exact total, limit, offset and stable ordering. Older unresolved
investigations remain reachable beyond the former 500-row client window. Search
escapes literal `%`/`_`; native PostgreSQL enum columns are explicitly cast to text.
The dashboard retains URL filters/pages and can fetch a deep-linked older run
outside its initial recent-run list.

`GET /api/v1/projects/{id}/audit-events/page` is reviewer-authorized.
`POST /api/v1/projects/{id}/audit-events/export` is administrator-authorized,
respects the saved enable/disable policy and maximum rows, and audits the export.
An oversized result returns 413 instead of truncating silently. Exported fields
exclude arbitrary details and credential material; spreadsheet formula prefixes
are escaped. The export uses the complete filtered result, not just the displayed
page. Disabling this endpoint is not DRM: authorized readers can still read and
manually copy records available to their role.

## Verification and remaining limits

Local checkpoint: 197 backend tests passed, three real-PostgreSQL tests skipped
because PostgreSQL was unavailable, 85.50% branch-aware backend coverage. SQLite
upgrade/downgrade/re-upgrade and `alembic check` passed. All five deterministic
harnesses ran; their synthetic-only provenance limitations remain unchanged.
The standalone API client passed strict TypeScript checking and six executable
Node request-contract checks. Modified TS/TSX files passed syntax transpilation.

Six Vitest cases and two additional API-backed Playwright journeys are included.
CI seeds six disposable browser fixtures (three desktop engines, two attempts),
including runs outside the initial recent-run window. Generate equivalent fixtures
only in an isolated demo database using `scripts/seed_operations_browser.py
--confirm-disposable-database --output <path>` and set
`FAILURELENS_OPERATIONS_FIXTURES=<path>` before running Playwright.

**Full locked frontend build/Vitest/browser execution, real PostgreSQL concurrency,
and Docker checks have not been executed for this checkpoint in the local runtime.**
npm installation failed with DNS errors. Exact remote CI must be inspected after
publication; green M5.2 workflows do not verify M5.3. Masked images/rich trace serving,
global security-audit pruning, assignment/notifications, backup/restore, real
LedgerGuard evaluation and the other unclosed master requirements remain separate.

## Disposable offline/recovery verification

`scripts/compose_recovery_smoke.sh --confirm-disposable-stack` allocates a uniquely
named Compose project and synthetic-only database, starts the real stack, checks
that runtime outbound Internet is unavailable, seeds three analyses, and verifies
restart persistence. It stops API/worker writers, takes a PostgreSQL custom-format
backup plus the artifact volume, restores into a separate database and fresh
artifact directory, then runs the real publication evidence validator against the
restored citations. Cleanup removes only that uniquely named disposable stack.
Requires Docker/Compose; the ordinary `failurelens` project is never targeted.

Default dashboard/API ports bind to loopback. The application network is internal;
dependencies/images are downloaded at build time, while the deterministic runtime
has no default Internet route. An operator adding an optional provider must make
an explicit network-policy/configuration decision; no runtime fallback adds egress.

For real backups, quiesce API and worker together, back up PostgreSQL and the entire
artifact volume as a matched pair, protect archives like the original private data,
and test restore into an empty isolated database/volume before switching traffic.
These archives are not encrypted by the script. Their directory/file modes are
restricted; encryption, offsite destination, retention and key management remain
operator responsibilities. Never feed an untrusted SQL/archive into restore tools.
CI execution of the new smoke gate is pending publication at this checkpoint.

The loopback API port is served by the fixed-route Nginx gateway. Only that gateway
joins the edge bridge; API/worker/PostgreSQL stay internal-only. This preserves host
access without granting the deterministic analysis processes Internet egress.
