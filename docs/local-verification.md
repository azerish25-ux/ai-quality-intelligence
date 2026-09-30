# Local verification without replacing historical evidence

`make verify` runs offline checks against the current source and writes a fresh
private directory outside the checkout. It never regenerates corpora, replaces
`evaluation/reports/latest`, removes `backend/verify-migration.db`, installs
dependencies, starts a provider or exports telemetry. Existing frozen inputs and
retained reports are included in the before/after source digest, including ignored
legacy files. A dirty or changed source fails the provenance result; it is not
clean committed-source acceptance.

Use already installed backend and quality environments. Installation and any
registry access are separate operator actions; see [the locked quality-tool
contract](quality-security.md). For example, with a fresh output directory:

```sh
make verify PYTHON=/tmp/loose-app/bin/python \
  VERIFY_ARGS='--quality-python /tmp/loose-quality-tools/bin/python --producer-fixtures /tmp/executed-producers --output /tmp/loose-local-run-001'
```

Omit `--output` for a unique `/tmp/loose-verify-*` directory. Explicit destinations
must not already exist and must resolve outside the checkout, including through
symlinks. The command prints the destination; `summary.json` records source
revision/digest, each check's status and actual child exit codes. Logs and nested
reports stay under that directory. Owned working directories, the migration
database and the copied frontend are removed on normal exit. Parent directories
are private; raw regression logs are local diagnostics, not upload-ready artifacts.

The verifier executes:

- The fresh backend coverage collector and its separate branch-target check.
  The collector requires clean source. Missing frozen legacy inputs or previously
  executed producer fixtures prevent the backend run, with an explicit NOT RUN
  result. Producer provenance and bytes are checked by the producer-contract tests;
  accepting a fixture path does not certify it. PostgreSQL skips and other test
  counts remain in the coverage report
- A SQLite migration upgrade, downgrade to `c7a9e2f4b610`, and upgrade again, using
  only an owned temporary database. A failed command stops that roundtrip
- The five existing legacy regression harnesses against their existing inputs,
  with distinct fresh report directories. These are not renewed held-out quality
  acceptance, a fresh companion execution or an operational-performance result
- `npm run build` and `npm test` using installed dependencies in a private copy of
  the frontend. Source `.env`/`.npmrc` files are excluded; compiler/test caches and
  outputs stay in the copy. Missing npm or dependencies are NOT RUN. No packages
  are installed, and package-manager network access is disabled
- The current `quality_checks.py` locks, lint, format, types, secrets and workflows
  gates. Secret candidates use the existing exact source-bound review policy;
  there is no replacement grep or silent fixture exemption

Each Python child receives an explicit local SQLite configuration, demo mode,
disabled provider/telemetry export, owned artifact/cache/temp directories and a
small environment. Inherited application settings, authentication, proxies,
package-manager configuration and Python/Node startup hooks are not forwarded.
Application tests and migrations run outside the checkout so a checkout `.env`
cannot activate production settings. This is environment and process hygiene,
not an operating-system filesystem or network sandbox. Tests may deliberately
exercise local synthetic transports.

## Results and acceptance

The summary keeps ordinary local regressions, the 90% overall/95% critical-module
branch targets, source provenance and required quality/security acceptance
separate. A successful backend collection still has to pass the independent
branch-target check; combined coverage must not be called branch-only coverage.

Both registry dependency audits are always **NOT RUN** in this offline wrapper.
The npm metadata audit is explicitly paused pending its separate authorization.
Skipped audits cannot satisfy required security acceptance, so `make verify`
returns nonzero even if every available offline check passes. It does not import
an older passing audit to certify new source or expose a bypass option. The
existing `quality_checks.py npm-audit --allow-npm-registry-audit` interface is
unchanged and may be used only after the transmission described in
[npm transmission approval](quality-security.md#npm-transmission-approval) is
authorized. Do not run that command while approval is denied or pending.

Exit **1** means an executed check/provenance failure or incomplete required
quality/security acceptance. Exit **3** means requested local regression work was
NOT RUN without an executed failure; exit **2** means invalid CLI/output setup.
Exit **0** is possible for the scoped commands below only when their requested
checks and clean-source provenance pass. It is never full-project acceptance.
Real PostgreSQL, browser lanes, Docker, fresh producer execution, frozen classifier
quality and operational performance remain separate exact-source checks.

```sh
# Existing legacy inputs, fresh external reports, no corpus generation:
make evaluate PYTHON=/tmp/loose-app/bin/python

# Current synthetic trust-boundary regressions in the isolated environment:
make security-test PYTHON=/tmp/loose-app/bin/python

# Focused runner regressions; no recursive suite, registry audit or live service:
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=backend/src:. \
  /tmp/loose-app/bin/python -m pytest -p no:cacheprovider backend/tests/test_local_verification.py
```

`make security-test` includes provider configuration/accounting/output/workflow,
project redaction, report/export/publication, workflow context and image child
isolation regressions alongside the original boundaries. It uses SQLite and
synthetic transports; it does not claim the separate PostgreSQL/Docker/provider
deployment acceptance. The focused runner tests check real child environment and
migration ownership, command failure propagation, external output preservation,
local frontend copying and audit/acceptance separation using disposable fixtures.
