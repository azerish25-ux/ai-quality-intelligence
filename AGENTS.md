# Working on Loose Thread

Read `README.md`, `docs/PROGRESS.md`, and `docs/requirements-matrix.md` before changing
behavior. This is the existing `ai-quality-intelligence` repository; retain its
history and compatibility interfaces (`failurelens` package/CLI/MIME identifiers).

## Safety and evidence

- Never weaken or silently replace frozen corpus labels, manifests, thresholds or
  historical reports to obtain a green benchmark. Ordinary regression CI and quality
  acceptance are different gates.
- Runtime inference must not load evaluation labels, fault flags or future reviews.
  Once held-out failures guide development, disclose reuse and use genuinely new
  held-out families for renewed generalization claims.
- Product-risk evidence cannot be outscored into reassuring flake/infrastructure
  advice. Preserve abstention, contradictions, missing evidence and review history.
- Revalidate project/run/execution scope, immutable derivative digest and evidence
  availability at publication boundaries. A stored validation flag alone is not a
  guarantee that the current artifact is available.
- Do not add shell, GitHub mutation, release or test-deletion capabilities to analysis
  or provider code. Provider proposals remain explicitly unverified.
- No actual paid provider invocation, external release or companion-repository change
  without the required owner authorization. Never put credentials in code or logs.

## Development and verification

Use one checkout. Preserve unrelated work, existing migrations, executable modes and
source provenance. Stage intentional changes explicitly; do not force-push.

Use the locked Python graph (`backend/uv.lock`, its hash-checked
`backend/requirements.lock` export) and frontend `package-lock.json`. A lock update
must regenerate its export. Actual producer tools retain their separately documented
pinned fixture versions.

For local edits, run the relevant tests with the repository root on PYTHONPATH:

```sh
PYTHONPATH=backend/src:. python -m pytest backend/tests/<affected_test>.py
cd frontend && npm run build && npm test
```

The complete backend suite requires the executed producer fixtures and has separate
real-PostgreSQL cases. Missing producer fixtures are failures, not evidence of a
passed full suite. Use exact-source CI for PostgreSQL, producer, Docker and browser
verification when those capabilities are absent locally. Add tests for discovered
bugs instead of suppressing assertions or adding blanket retries.

For measured clean-source installation, commit intended code and use
`scripts/install_committed_backend.sh`. It installs a Git archive outside the checkout;
source dirtiness remains a failure. Do not ignore packaging side effects merely to
make provenance green.

Update the progress ledger with actual tested SHA, commands, outcomes and unresolved
scope. Verify the remote head and CI for the delivered revision. A different earlier
revision's passing CI is not evidence for the final commit.
