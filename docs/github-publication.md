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

References checked 2026-09-30:
[GitHub comment API](https://docs.github.com/en/rest/issues/comments) and
[Actions secure use](https://docs.github.com/en/actions/reference/security/secure-use).
