# Backend branch coverage and M9 acceptance

Ordinary backend regression acceptance retains its existing **75% combined
statement-and-branch gate**. It does not mean 75% branch coverage, and it does not
meet the master's separate **90% overall branch-only** and **95% for every declared
critical file** targets. The pre-collection local diagnostic was
2,998/3,840 = **78.0729% branch-only**, versus **87.4706% combined**. Those historical
counts are not a measurement of this new collector or subsequent source changes.
The master coverage target remains unaccepted until a fresh committed-source run
passes the strict check below. Passing tests of the collector is separate evidence.

## Scope declared before measuring

The overall denominator includes every Python runtime file under
`backend/src/failurelens`, including CLI, workers, schemas, demo code and unexecuted
modules. There are no module omissions, threshold overrides, generated passing
baselines, or special acceptance treatment for difficult branches.
An additional Python runtime namespace outside the current `failurelens` package
is rejected until the collector's overall scope is explicitly expanded; it cannot
silently disappear from the denominator.

The following 33 files each have an independent 95% branch-only target. The full
file is measured when security-sensitive work and routine work share a module.
Paths below are relative to `backend/src/failurelens`, with `.py` implied.

| Group | Files | Rationale |
| --- | --- | --- |
| Evidence and storage | `evidence_validation`, `contract_evidence`, `transaction_evidence`, `domain_evidence`, `binary_evidence`, `trace_evidence`, `github_evidence`, `storage`, `image_codec`, `image_worker` | Evidence scope, integrity, availability, bounded parsing and decoding |
| Authorization and configuration | `auth`, `accounts`, `config`, `api`, `operations_api`, `binary_api`, `provider_api`, `github_api` | Identity, roles, deployment configuration and mixed API permission boundaries |
| Redaction | `redaction`, `redaction_keys` | Source sanitization and correlation-key handling |
| Dangerous dismissal and reports | `analysis`, `history`, `providers`, `impact`, `github_report`, `github_report_sections`, `github_snapshot` | Non-reassurance, prior-only history, recommendations and published evidence selection |
| Publication and provider execution | `service`, `provider_service`, `provider_jobs`, `provider_proxy`, `github_publication_service`, `github_publication` | Revalidation at shared service boundaries, provider execution and external publication |

This is an explicit critical-file policy, not a certification that all security
boundaries or dangerous behaviors in the repository are covered. Other modules
remain in the overall denominator. Branch coverage does not establish assertion
quality, independent held-out performance, PostgreSQL behavior, or security immunity.
Policy changes require review before a new measurement; lowering targets or
removing difficult files to obtain acceptance is not supported.

## Fresh collection and independent checking

Use the hash-locked backend environment. The current lock supplies coverage.py
7.16.2 and pytest-cov 7.1.0. Coverage's subprocess patch requires at least 7.10;
the collector rejects an older runtime. It uses coverage.py directly and disables
pytest-cov for its pytest process, so plugin auto-loading can safely be disabled.
The normal pyproject coverage configuration also enables the subprocess patch.

Run from the repository root with an output directory that does not already exist:

```sh
PYTHONPATH=backend/src:. python scripts/backend_coverage.py collect --output /tmp/loose-backend-coverage
python scripts/backend_coverage.py check --report /tmp/loose-backend-coverage/report.json
```

After `scripts/install_committed_backend.sh` in CI, omit `PYTHONPATH`; the imported
installed package must have exactly the same Python file inventory and bytes as
the committed checkout package. Both these exact roots may contribute execution
data. Arbitrary copied roots, stale installations, symlinks, missing modules and
different source bytes are rejected. No basename-based path alias can merge them.
The collector can be invoked from another directory. It resolves selectors and
import paths explicitly and runs pytest in a fresh external working directory,
so the repository's `.env` is not loaded as the test working-directory settings.
The caller remains responsible for supplying the intended disposable database,
artifact directory, producer fixtures and disabled optional provider/export settings.

Collection requires a clean tree and verifies the full backend runtime/test Python
inventory, coverage scripts, configuration and locks against actual Git HEAD blob
bytes. This catches ignored extra Python files and ignored modifications that a
plain `git status` check could miss. The same source and installed-package checks
run again after the tests. A new output directory and coverage shards dedicated to
that invocation prevent reuse of an old database. Deliberate mutation runs retain
their existing environment isolation and cannot contribute their mutated data.
No held-out labels or corpus contents are read by the collector.

The retained pair is:

- `report.json`: exact source and data digests, canonical file paths, tool version,
  six integer coverage counts per runtime file, test outcome counts, fixed gates
  and a committed/development measurement label
- `coverage-data.sqlite`: canonical repository-relative paths and actual executed
  line-to-line arcs, with no source text or captured test output

Only this pair is intended for publication. Raw per-process shards and generated
configuration contain local paths and remain private. Rich upstream coverage JSON
and JUnit test output are transient; the retained report does not copy source,
function names, exception messages, environment values or arbitrary skip reasons.
PostgreSQL-only skips are counted separately, and every other skip remains in the
total skipped count. SQLite execution with skipped PostgreSQL tests is not
PostgreSQL acceptance.

Checking requires the clean current committed source, both retained files and the
same coverage.py version. It verifies the SQLite digest, branch mode, exact runtime
path inventory and source bytes, then independently recalculates both covered counts
and denominators from the retained arcs and current source. Missing files,
line-only data, malformed/boolean/floating counts, inconsistent summaries, stale
source, mismatched data, changed targets and altered pass flags fail closed.
Threshold decisions use integer cross-multiplication, so 89.9999% cannot round up
to pass 90%, and 94.9999% cannot pass 95%. A critical file with no branch
opportunities is an error requiring policy review, not an automatic pass.

The retained pair is evidence from a trusted test collector and artifact chain,
not a signed or tamper-proof execution attestation. Someone able to replace both
the executed-arcs database and its bound report can fabricate a different dataset.
Checksums and recomputation prevent a counts-only edit or accidental mixing from
becoming acceptance; they do not replace CI execution provenance or code review.

Exit status distinguishes the two commands:

- `collect`: 0 means tests succeeded and the unchanged 75% combined gate passed;
  1 means regression/combined failure; 2 means incomplete or invalid evidence
- `check`: 0 means the committed-source 90% overall and every 95% critical-file
  branch target passed, along with regression/combined checks; 1 means coverage
  targets were missed; 2 means invalid, stale, incomplete or development evidence

For explicitly developmental focused work only:

```sh
PYTHONPATH=backend/src:. python scripts/backend_coverage.py collect --development --output /tmp/loose-coverage-development -- backend/tests/test_image_worker_coverage.py backend/tests/test_image_process_boundary.py
```

This retains honest measured counts and ordinary test/combined results while
forcing `master_branch_acceptance` to false. `check` refuses a development report,
even when its numeric branch targets happen to be met. A focused collection can
legitimately fail 75% because the entire runtime still remains in its denominator.

## Isolated image worker and normal subprocesses

pytest-cov 7 no longer auto-instruments subprocesses. The locked coverage runtime's
`patch = ["subprocess"]` measures normal Python children that inherit its coverage
configuration. It does not rewrite an explicitly supplied `Popen` environment.

Production `image_codec` remains unchanged: direct sibling worker path, Python
`-I`, minimal environment, closed inherited descriptors and the existing timeout.
The environment/PYTHONPATH/descriptor isolation canaries continue to use that real
uninstrumented production launch.

`test_image_worker_coverage.py` separately invokes the real worker through the
trusted test-only `scripts/isolated_worker_coverage.py` harness. It keeps `-I`,
the same minimal environment and closed descriptors. Trusted absolute code/data
paths and an exact worker digest travel through command arguments; artifacts and
options still arrive only on stdin. The harness verifies the worker bytes, starts
branch measurement and runs that unchanged file with `runpy.run_path`. It rejects
stale code and existing or dangling-symlink destinations. Production never imports
the harness or receives coverage configuration through its minimal environment.

Paired direct/instrumented executions assert identical results for PNG/JPEG decode,
encoding, thumbnailing, burned-in masks, malformed/empty/oversized input, pixel
limits, invalid masks and animated images. Real child data is inspected to prove
that worker arcs were recorded. Normal inherited-child collection also has an
executed subprocess regression. Instrumentation adds work to the measured test
child; it is not a claim about production decoder resource or security guarantees.

## CI integration and current verification

The workflow retains the existing PostgreSQL backend job and exact archive
installation. Its `Test and coverage` command runs from `backend`:

```sh
python ../scripts/backend_coverage.py collect --output /tmp/loose-backend-coverage
```

An unconditional, fail-on-missing upload retains
`/tmp/loose-backend-coverage/report.json` and
`/tmp/loose-backend-coverage/coverage-data.sqlite`, named
`backend-branch-coverage-${{ github.sha }}`. Raw shards and test logs are not uploaded.
The existing backend job continues to use collection's unchanged regression and
75% combined result; a below-master branch result is visible in the report.

A separate `Backend branch acceptance` job runs even when its dependency fails,
checks out the same revision with persisted credentials disabled, installs the
same locked backend runtime, downloads only that exact-revision artifact, and runs:

```sh
python scripts/backend_coverage.py check --report /tmp/loose-backend-coverage/report.json
```

Missing artifacts, failed regression runs, download failures and strict target
failures fail this acceptance job. The actions retain their reviewed pinned
revisions. There is no `continue-on-error`, automatic green baseline, ignored exit
code, source omission or conditional skip that turns missing evidence into
acceptance.

Local working-tree verification passed **81 focused cases** across the new
collector/report and real image-worker coverage tests plus the existing image
process-isolation canaries. Both scripts pass gradual mypy, and all four new Python
files pass Ruff lint and formatting. The workflow's dedicated regression also
passes locally. These changes are implemented but **not yet verified by a fresh
clean full-source collection or hosted CI** at this checkpoint; no master coverage
acceptance is claimed.
