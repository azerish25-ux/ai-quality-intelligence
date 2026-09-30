# GitHub advisory reports and publication

The default integration is read-only, works on GitHub-hosted runners with an
ephemeral PostgreSQL service, and needs no public application deployment. Report
previews, evidence exports and the Action do not post comments or approve releases.
The explicit publisher command runs separately with its own credential.

## Shared report and retained evidence

`GET /api/v1/runs/{run_id}/github-report-preview` and
`failurelens report --run RUN_ID --format json` use the same project-scoped
`github-report-v2` projection. Markdown is derived from that projection. It includes
exact tested/base SHA, external run identity/attempt, scope, input/shard completeness,
logical-test outcomes and retries, current analyses, supporting/contradictory
references and next investigations. Empty analyses or missing required evidence
cannot produce reassuring advice. Legacy/unvalidated or expired claims are withheld.

Logical identity includes test, suite, source path, parameterization and browser;
retries are not independent tests. New bounded sections expose real skipped reasons,
effective stored impact selections/exclusions and overrides, current cluster
revisions and stored performance comparisons with thresholds, sample counts,
confounders and evidence availability. Previewing does not create these records.
A stored regression, unavailable comparison, or selected subset that violates a
required full-suite fallback forces HOLD. Missing optional comparisons are not
assessed, rather than invented as favorable results.

New/existing/unknown comparisons require prior exact-base observations in the same
project/repository and compatible framework, environment, scope, worker and shard
cohort. A matching prior failed fingerprint supports existing; validated all-pass
comparable observations can support new. Missing, skipped, conflicting, future,
restricted or search-truncated baselines remain unknown. Comparisons use the latest
failed attempt of each logical test, including a test that subsequently passed on
retry. Existing never means harmless and cannot relax product-risk flags.

The JSON report is capped at 100,000 bytes and Markdown at 50,000 bytes. Full
aggregate counts and explicit omission counters survive whole-record trimming;
Markdown is regenerated when JSON details are removed. Strings are inert data,
not shell, HTML, Markdown instructions or producer-authenticity certificates.

The report's nested `evidence_export` descriptor binds a canonical
`github-evidence-v1` document named `evidence.json`. Its counts distinguish
requested, exported, rejected, unavailable and omitted references, plus unavailable
analyses and invalid/truncated reference hints. `distribution_status: not_published`
is the backend's publication state; prepared bytes do not prove a successful
artifact upload, comment publication or permission to grant another audience access.

Export the approved subset with:

```sh
failurelens export-evidence --run RUN_ID --report-digest REPORT_DIGEST --output evidence.json
```

The CLI freshly revalidates the report and its evidence before exclusively creating
the file; it refuses existing paths. The authorized route
`/api/v1/runs/{run_id}/github-evidence-export?report_digest=REPORT_DIGEST` returns
the same canonical bytes. A stale requested report produces HTTP 409.

Exports contain at most 100 whole entries and 500,000 bytes: exact approved
excerpts, narrowly allowlisted scalar observations, immutable parser locators,
project/run/execution scope, content/source digests and parser/redaction versions.
Original files, storage paths, arbitrary nested details and binary bodies are
excluded. Oversized quotes are omitted whole. Related baseline runs must be
explicit, in the same project and recorded no later than the selected run.
Immutable-byte, quotation, locator, observation, approval and retention checks are
shared with publication; passes/skips do not need a fabricated failure record.

Both JSON formats use sorted keys, compact separators, Python JSON ASCII escaping
and finite numbers. Remove only `evidence_digest` before recomputing the export
hash, or only `report_digest` for the report. Preserve the original bytes when
downloading: another language's number formatting can change the hash. A digest
identifies bytes, not producer authenticity. Treat every exported string as data;
unknown sensitive patterns may remain. Appropriate artifact access and retention
remain the operator's responsibility.

## Executable read-only consumer

[The consuming workflow](../.github/workflows/github-report.yml) runs on push,
ordinary pull requests and manual dispatch. Two actual pytest shards write JUnit;
their test exit codes remain authoritative. A fresh PostgreSQL 17 service is
migrated, then the composite Action consumes a manifest-v2 bundle. The
`$/integrations/github-action` self-repository reference resolves reviewed Action
code from the workflow commit, rather than mutable checkout files. GitHub.com
runner 2.336.0+ is required. On PRs, producers check out and report the exact tested
PR head separately. External consumers should pin the Action revision and provide
Python 3.12+ and the migrated database.

Only `contents: read` is granted. Checkout credential persistence is disabled;
provider/publisher credentials are absent. There is no `pull_request_target` or
trusted write-capable follow-up. This is not an OS egress sandbox: dependency
installation and authorized GitHub artifact transfers use the runner network.

`bundle.py` receives the planned shard names from workflow code. It reads only
bounded regular XML files, rejects symlinks/traversal/duplicates, ignores
undeclared files and preserves absent shards as required missing inputs. It never
executes artifact content or loads labels. Missing downloads can proceed to an
incomplete report, but the independent complete-transport gate still fails. A
successful report cannot turn a failed producer green. Cancellation may prevent
reporting entirely. These regression shards have `run-scope: unknown`; they do not
establish full-suite or classifier-quality acceptance.

Action outputs include sanitized Markdown (`report-path`), canonical JSON
(`report-json-path`), approved retained evidence (`evidence-path`) and fixed-field
processing status (`status-path`). Fixed enum/ID/hash outputs include processing,
ingestion/run state, completeness, advisory status, identities and report digest.
Empty paths and a fixed safe error remain on failure; CLI error bodies never enter
logs, outputs or summaries. Each invocation uses a fresh private directory.

The Action verifies the snapshot, obtains evidence bound to its exact digest, and
checks the output's regular-file status, bytes, canonical digest, receipt, counts
and project/run/related-run scope before exposing it. The consumer uploads only
the four declared output files. It never uploads the database, original bundle or
private evidence storage. Approved retained excerpts remain inspectable after the
ephemeral database disappears, until the actual artifact expires. Omitted or
restricted evidence is not reconstructed, and there are no invented public URLs.
Upload failures remain failed workflow steps.

Effective defaults are deterministic analysis and summary publication. Artifact-only
retains the same files without a report in the job summary; neither mode comments
or invokes a provider. Optional `config-path` plus `config-sha256` select strict,
non-executable JSON from a reviewed operator/workflow location. Supported settings
can select those modes or reduce fixed byte ceilings, never weaken completeness,
change identity or enable credentials/URLs/code. Matching bytes do not establish
trusted provenance. There is no PR auto-discovery. See the
[complete Action contract](../integrations/github-action/README.md).

## Explicit durable bot publication

```sh
failurelens publish-github --run RUN_ID --repository OWNER/REPO --pull-number NUMBER
```

Only the publisher process reads `FAILURELENS_GITHUB_TOKEN`; it is never a command
argument or an analysis/provider capability. The destination must match the run,
and trusted GitHub reads must identify an open PR in that base repository with
an exact tested head. Configure the exact bot with `--bot-login` (default
`github-actions[bot]`). A fixed authenticated GraphQL viewer query and trusted user
lookup must verify that Bot's numeric identity before any comment write. Human or
unverified actors fail closed. The client ignores ambient proxy/certificate
settings, suppresses raw transport logging and rejects the configured token in
comment text. Give only this process the needed comment-write capability.

The durable CLI uses a hashed immutable project-ID marker. It updates only the
configured bot's report; copied human markers are ignored and duplicate owned
markers fail closed. Invalid comment shapes never count as absence. A stable
report digest distinguishes snapshots even when Markdown is equal; unique write
receipt metadata does not force a needless update on identical replay.

Migration `f8d0c2e4a610` adds target reservations, publication attempts and bounded
write journals. Intent commits before each HTTP mutation; no transaction spans
HTTP. Optional source workflow run/attempt fields are stored as **unverified**
context, not workflow authenticity. Viewer-authorized, paginated receipt history is
available at `/api/v1/projects/{project_id}/github-publications` and its
`/{publication_id}` route. There is no HTTP publication endpoint. Receipts contain
bounded attribution, hashes, states and timestamps, never credentials/report bodies.

Receipts also retain the report schema, a digest/count of every latest analysis
revision and at most 50 visible analysis/failure IDs with integer revisions.
Omitted references have an exact count. The report's full analysis manifest is
hashed before detail trimming, so changing an omitted revision changes report
identity even when Markdown and aggregate counts look identical. No analysis text
or evidence body is copied into this revision metadata.

Serialize workflow callers per repository/PR/project with cancel-in-progress false.
Database reservations independently prevent concurrent application publishers.
GitHub has no atomic PR-head/comment transaction: trusted head checks occur before
and after writes, and a detected race requires a neutral stale/HOLD replacement.
An old run cannot overwrite a current-head report. Later head changes require a
new explicitly authorized invocation; this is not a continuous release gate.

A lost response or process crash keeps the reservation sticky. No lease expiry,
missing comment or automatic retry grants permission to resend an uncertain POST.
Every successful new/no-op completion rechecks the current report and evidence;
validation drift becomes failed or uncertain while preserving any observed write.

## Reconciliation and explicit neutral repair

```sh
failurelens reconcile-github --publication PUBLICATION_ID
failurelens reconcile-github --publication PUBLICATION_ID --repair-stale
```

Default reconciliation uses only read operations for an active/uncertain receipt.
It fences the original publisher and searches for the exact final bot-owned write,
including body digest, receipt marker, author and head. Missing/different content
stays uncertain. Observed delivery does not certify current evidence: report,
evidence or head drift remains explicit and cannot be called current success.
Already-terminal receipts return their historical recorded result with unchanged
timestamps; that shortcut is not a new GitHub or evidence check.

Only explicit `--repair-stale` may replace an exactly reconciled report with a
neutral HOLD. It never recreates an absent comment or overwrites a newer different
report. Wording distinguishes changed PR heads from changed evidence/projections
when the SHA is identical. Repair records its own committed write intent and fresh
validation digest, preserving the original report digest and historical write.
Later repair of an already-settled historical receipt is not automatic; a new
publication/reconciliation workflow must establish its current scope.

## Verification and remaining limits

Local tests exercise actual HTTP clients with deterministic transports, persisted
SQLite state, CLI paths, approved artifact bytes and authorization. They cover
missing permissions, identity errors, duplicate delivery, malformed data, stale
heads, lost acknowledgements, cancellation/fencing, current evidence changes,
privacy, limits and fork-safe defaults. Fixtures are not live GitHub integration.

New PostgreSQL contention/migration, hosted Action, browser and live publication
acceptance remain unverified for the current implementation until exact-source
execution. An authorized live comment requires a suitable approved target PR; none
is implied by these tests. Source delivery is separately tracked in PROGRESS.md.

A future trusted follow-up publisher is optional and remains disabled. It must run
reviewed pinned/default-branch code, independently resolve source workflow/run/
attempt/artifact/repository/PR/head through GitHub, treat downloaded content as
untrusted and avoid PR code/caches/secrets. A digest or artifact-provided PR number
cannot authorize a write. Never use pull_request_target to execute PR code with
write credentials.

Official references checked 2026-09-30:
[comment API](https://docs.github.com/en/rest/issues/comments),
[installation-token identity query](https://docs.github.com/en/apps/creating-github-apps/authenticating-with-a-github-app/authenticating-as-a-github-app-installation),
[Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use),
[workflow-run security](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#workflow_run),
[PostgreSQL services](https://docs.github.com/en/actions/tutorials/use-containerized-services/create-postgresql-service-containers),
[self-repository Action references](https://github.blog/changelog/2026-07-30-reference-same-repository-actions-with-self-repository-syntax/).
