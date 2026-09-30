# GitHub advisory publication

`failurelens publish-github --run RUN_ID --repository OWNER/REPO --pull-number NUMBER`
publishes only a report rendered from persisted analyses. It requires an explicit
`FAILURELENS_GITHUB_TOKEN` in the publisher process environment, never a command-line
secret. Deterministic ingestion does not call this command or contact GitHub.
The repository must exactly match the run's stored repository; GitHub must confirm
an open PR in that base repository and an exact tested head SHA. Missing, abbreviated
or obsolete SHAs cannot produce a current report.

The default identity is `github-actions[bot]`; a GitHub App publisher must configure
its exact bot login with `--bot-login`. Human accounts are not supported. Give only
the publisher job `pull-requests: write` and repository read access. Keep artifact
parsing/model jobs read-only and secret-free. Do not run this publisher from PR code
or use `pull_request_target` to execute that code. The existing ingestion Action
continues to emit a job summary without requiring comment permission.

## Identity, replay, and races

One hashed project-purpose marker scopes the report within a repository/PR. Only a
matching bot-owned comment is updated; copied human markers are ignored. Multiple
owned matches fail closed instead of deleting comments. Listing follows pagination
with a hard bound. The result identifies status, comment ID, tested SHA and current
SHA. Identical retries do no write; changed reports update the existing comment.

Serialize callers for each repository/PR/project using a workflow concurrency group
and `cancel-in-progress: false`. GitHub provides no atomic PR-head/comment transaction:
head checks occur before and after the write. A detected head change replaces the
report with `HOLD_FOR_REVIEW` and an explicit stale notice. An old run cannot replace
a current-head report. A later head change requires a new publisher invocation to
reconcile it. This is not a continuously monitored status check or release gate.

The publisher deliberately does not blindly retry POST requests. If a response is
lost after a successful write, a subsequent serialized invocation first rediscovers
the comment and avoids duplication. API errors omit response bodies and credentials;
permission errors, rate limits, redirects, transport failures, malformed receipts,
closed PRs, and lookup limits fail explicitly. Report metadata is escaped, unwanted
mentions are disabled, and an empty analysis set never yields reassuring advice.

## Verification and remaining integration boundary

`PYTHONPATH=backend/src pytest backend/tests/test_github_publication.py backend/tests/test_github_report.py`
exercises the real HTTP client with a deterministic REST transport, including lost
acknowledgement, stale heads before/after writes, malicious metadata, pagination,
permissions/rate limits and comment ownership. These are contract tests, not proof
of live GitHub publication. Live publication, a separate trusted follow-up workflow,
publication persistence/API views and the full rich report contract remain open.
The read-only consuming workflow below is an independent integration boundary.

References checked 2026-09-30:
[GitHub comment API](https://docs.github.com/en/rest/issues/comments) and
[Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use).

## Read-only report preview

`GET /api/v1/runs/{run_id}/github-report-preview` uses the usual project-role
boundary and performs no external write. CLI `report --format json` and Markdown
share the same versioned projection and digest. It uses the latest analysis revision
per failure, collapses test/browser/parameterization attempts for outcome denominators,
retains retry counts, and exposes explicitly unknown baseline status. Investigations
include safe summaries, supporting/counterevidence IDs and missing-evidence notices.
Legacy unvalidated summaries and expired evidence bodies are withheld. Markdown is
capped at 50 KB. JSON is capped at 100 KB, with at most 50 investigation and 50 input
details; the two projections disclose their own omitted detail while preserving full
counters. JSON metadata receives the same declared-sensitive-value redaction; treat
all remaining strings as untrusted data, never commands. Explicit `advisory_status`,
`run_status` and input-state/required-input/shard counters are shared by the Action. This does not yet replace
the dashboard's complete impact/performance/history views.


## Executable read-only consumer

[`.github/workflows/github-report.yml`](../.github/workflows/github-report.yml) runs
on push, ordinary `pull_request` and manual dispatch. Two real pytest regression
shards write JUnit XML; their test exit codes remain authoritative. The consumer
uses a fresh PostgreSQL 17 service, upgrades Alembic, and calls the repository's
composite Action on a manifest-v2 bundle. The `$/integrations/github-action`
self-repository reference resolves Action code from the workflow commit, rather
than mutable checkout files. On PRs, the producer checks out and reports the exact
PR head separately. GitHub.com runner 2.336.0+ is required for `$/` references.
Both jobs install the hash-checked Python
graph. The Action builds the application outside the measured checkout with no
build-isolation dependency resolution. External consumers must pin the Action's
repository revision, supply Python 3.12+ and migrate their chosen database.

Only `contents: read` is granted. Checkout credential persistence is disabled, no
repository secrets or provider credentials are passed, and this workflow cannot
post comments. Ordinary PR code is executed only in this read-only disposable job.
This is not an OS-level egress sandbox: installing dependencies, retrieving GitHub
artifacts and uploading the declared output artifacts use the runner network.

`bundle.py` receives the two planned shard names from workflow code, rather than
discovering only successful files. It reads only those bounded regular XML files,
rejects symlinks/traversal/duplicates, preserves absent files as required manifest
entries and ignores all undeclared files. It neither executes commands from an
artifact nor loads evaluation labels. Equal input bytes produce equal bundle bytes.
The download steps may continue after missing artifacts so the report can retain
`missing` states; the final transport gate still fails unless completeness is
`complete`. A failed test shard remains failed even if its report was transported
successfully. Cancellation may stop reporting entirely.

The selected regression shards are marked `run-scope: unknown`; they are not a
full-suite evaluation and do not establish classifier quality. `shard-count` is the
workflow's declared plan. Required `expected-inputs`, manifest input states and
accepted-required counts determine completeness; test observations never substitute
for a missing artifact. Even a complete all-pass report with no analyzed failures
conservatively emits `HOLD_FOR_REVIEW` under the existing advisory policy.

### Action output contract

- `report-path`: sanitized Markdown, or empty if processing failed
- `report-json-path`: the versioned `github-report-v2` projection, or empty on failure
- `status-path`: fixed-field `github-action-status-v1` JSON, including safe error
  code on CLI/input validation failure after the runner starts
- `status`: `reported` or `failed`; this is processing success, not a release decision
- `ingestion-id`, `run-id`, `ingestion-state`, `run-status`: persisted scope and state
- `completeness`: `complete`, `partial`, `unknown` or `evidence_expired`
- `advisory-status`: `HOLD_FOR_REVIEW` or `NO_BLOCKER_IDENTIFIED_IN_OBSERVED_SCOPE`
- `report-digest`: SHA-256 of the entire unsigned projection serialized with
  Python JSON defaults, sorted keys and separators `(',', ':')`; remove only the
  top-level `report_digest` before recomputing

The Action requests one JSON snapshot, verifies its run identity/digest/status,
and derives the Markdown file and job summary from that same snapshot. Structured
outputs are constrained to fixed enums, UUIDs, hashes and runner-generated paths.
CLI error bodies are never copied into workflow logs, outputs or summaries. A
sanitized failure status is retained without inventing a usable report. Each
invocation gets a fresh private temporary output directory. The consumer uploads
only the named report/status files, never the database, original bundle or private
evidence storage. The digest detects corruption; it does not authenticate an
untrusted producer. Evidence IDs in these exports require the originating authorized
database and will not resolve once the ephemeral service is gone. Durable evidence
publication and publication receipts remain open.

### Verification and exact-source prerequisites

`PYTHONPATH=backend/src:. python -m pytest backend/tests/test_github_action.py
backend/tests/test_github_snapshot.py backend/tests/test_github_report.py
backend/tests/test_github_publication.py` exercises real CLI ingestion/reporting with
zero, one and two arriving shards, redaction canaries, output injection, missing
inputs, deterministic bundles, byte bounds, digest consistency and safe failures.
The local Action tests use SQLite and do not claim PostgreSQL or hosted Actions
execution. Fresh committed-source execution of `github-report.yml` must verify the
actual service migration, both producers, reusable Action, upload and transport gate.
No local Docker/PostgreSQL runtime was available for this batch.

## Trusted follow-up publication requirements (not enabled)

A future write-capable follow-up must execute only reviewed default-branch/pinned
publisher code and dependencies. It must not check out PR code, restore PR-provided
caches, run artifact scripts or install code from a downloaded artifact. A
`workflow_run` event is a wake-up, not proof that its artifacts or reported PR number
are trusted. Independently resolve the source run, repository, workflow identity,
event, attempt, artifact identity/digest and exact tested head through GitHub; resolve
the target open PR and current head through GitHub rather than artifact fields.
Enforce bounded content/schema, rebuild a safe projection, revalidate immutable
evidence scope/digests/availability, then reconcile only the configured bot-owned
project marker with serialized per-PR/project writes. A standalone Markdown artifact
or matching digest cannot authorize a write or establish evidence authenticity.

Persist attributable publication intent/result, source run and attempt, tested/current
SHA, report digest, bot/comment identity and safe failure status. Lost write responses
require reconciliation rather than blind retry. Re-check the head before/after
publication and preserve stale/HOLD behavior. A write-capable workflow, durable
publication/evidence storage and live target testing require a separate reviewed
implementation and explicit authorization; none is supplied by this read-only
consumer.

GitHub's [workflow-run security guidance](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run)
and [secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use)
were checked on 2026-09-30. The PostgreSQL service follows the documented
[service-container pattern](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers).

[GitHub self-repository reference contract](https://github.blog/changelog/2026-07-30-reference-same-repository-actions-with-self-repository-syntax/) checked 2026-09-30.
