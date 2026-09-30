# Contributing

Loose Thread is an evidence-grounded triage application with deliberately conservative
publication policy. Read [architecture](docs/architecture.md), [security](docs/security.md),
[requirements](docs/requirements-matrix.md) and [current limitations](docs/limitations.md).

## Setup

The primary application path is `docker compose up --build`. It runs a synthetic,
loopback-only demo; it is not a production authentication configuration. The gateway
serves the dashboard at `http://localhost:8080` and API at `http://localhost:8000`.
For development, Python 3.12+ and Node compatible with the package manifests are also
needed. `make bootstrap` installs the resolved Python graph and npm dependencies.
See [dependency updates](docs/dependencies.md) before changing versions.

## Changes

Keep changes focused and preserve backwards-compatible identifiers. Add explicit
migrations for schema changes, typed API/client contracts for new fields, and tests
covering negative scope, missing evidence, cancellation/repetition and recovery.
Treat all uploaded content and provider outputs as untrusted. Never include genuine
credentials or customer records in fixtures; use fake canaries and synthetic data.

Use the repository's established branch/delivery policy. A draft PR is appropriate
when review is requested; the existence of a draft does not authorize merging.
Do not rewrite others' history or replace unrelated source to simplify a patch.

## Verification

- `make test`: backend tests/coverage, with real producer exports configured
- `npm --prefix frontend test` and `npm --prefix frontend run build`: client tests/types/build
- `make test-e2e`: requires the real API, worker, database and dashboard
- `make evaluate`: legacy deterministic regression suites, not new held-out acceptance
- Frozen benchmark/campaign workflows: independent provenance and quality gates
- `scripts/compose_recovery_smoke.sh --confirm-disposable-stack`: actual disposable
  offline-runtime, restart and restore checks; requires Docker/Compose and shell tooling

Report failed, skipped and not-run stages separately. Never change a quality target,
label or split as a substitute for improving the system. A public agent-authored
benchmark is not an independently blinded study. Preserve old results and include
source/input/configuration digests for each new measurement.

For benchmark measurements, use a clean committed checkout and the archive installer.
Editable development installations may create packaging metadata and do not bypass
that cleanliness requirement.
