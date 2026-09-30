# Dedicated quality and security gates

The `Loose Thread quality and security` workflow is independent of the existing
ordinary regression CI. Seven matrix jobs run on pushes, pull requests and
manual dispatch, with `fail-fast: false`. The npm audit is a separate, default-off
manual job because it transmits lock-derived metadata to a third party. Skipped
npm work is explicitly **NOT RUN**, never a pass. A failing scan is a failing job. There
is no `continue-on-error`, accepted-finding baseline, ignored advisory, severity
waiver or automatic dependency fix. A green existing regression workflow does
not imply that these gates pass or that the full project is ready.

## Locked tools and actual scope

`tools/quality/uv.lock` is a separate tooling graph, exported byte-for-byte to
`tools/quality/requirements.lock` with uv **0.12.19** and installed using
`pip --require-hashes`. It does not alter the runtime dependency graph. The
runner verifies installed versions against its manifest before scanning:

- [Ruff 0.16.9](https://pypi.org/project/ruff/0.16.9/): pinned stable default
  lint rules and formatter over every Git-tracked `.py`/`.pyi` file, plus new
  non-ignored files locally. Explicit filenames, Python 3.12 target, no
  configuration overrides, exclusions or `noqa` suppression; no auto-fix
- [mypy 2.3.1](https://pypi.org/project/mypy/2.3.1/): all `backend/src`, including
  untyped function bodies and unused-ignore checking. This is gradual type
  checking, **not** strict annotation completeness. Tests, migrations,
  evaluation scripts and integrations are not part of the backend type claim.
  It uses installed dependencies from a separate backend-lock environment
- [pip-audit 2.10.1](https://pypi.org/project/pip-audit/2.10.1/): backend development
  and quality-tool hash-locked graphs, independently, using PyPI's public
  advisory service. Dependency collection failures and unavailable audits fail.
  Runtime export parity is checked separately; environment markers apply to the
  executing platform. This does not certify other operating-system graphs,
  container base images, arbitrary source vulnerabilities or undisclosed CVEs
- npm **11.17.0**, supplied with pinned [Node 24.19.0](https://nodejs.org/en/blog/release/v24.19.0): the complete frontend
  package-lock graph including development, optional and peer dependencies,
  using the public npm advisory service. Scripts are disabled; no packages are
  installed or upgraded by the audit. The expected npm version is verified from
  [Node’s tagged source](https://github.com/nodejs/node/blob/v24.19.0/deps/npm/package.json).
  Any reported vulnerability fails
- [detect-secrets 1.5.0](https://pypi.org/project/detect-secrets/1.5.0/): current
  source text, including tests, fixture data, workflow files and lockfiles.
  Credential verification is explicitly disabled. File-wide lock/Swagger
  filters and inline allowlists are disabled; the pinned detector's remaining
  standard per-candidate heuristics are retained. A supplemental signed-URL
  query check records only a location and rule name. Every candidate fails and
  needs review; a candidate is **not** proof that a real credential exists.
  Binary/archived contents and Git history are not certified. Non-UTF8 files are
  listed in reports rather than silently claimed scanned
- [zizmor 1.30.1](https://pypi.org/project/zizmor/1.30.1/): every workflow and
  reusable `action.yml`/`action.yaml`, in offline auditor mode, with strict
  collection and ignores disabled. All reported severities fail. Online-only
  checks such as remote action provenance cannot be claimed from this scan
- `locks`: `uv lock --check --offline` for both Python projects, exact export
  comparison for development/runtime/tool requirements, and frontend
  manifest-to-lock direct dependency agreement

No GitHub token, credential-testing service, paid service, new permission grant,
container execution or package-manager auto-remediation is required.
Dependency names/versions go to their public advisory registries; secret values
and repository content do not go to credential-verification services.

## Reports and failure semantics

`scripts/quality_checks.py` captures tool output privately and emits a bounded
JSON report with tool versions, source revision, working-tree cleanliness,
combined source digest, scope, actual tool exit codes, categories and locations.
Reports omit source snippets, tool messages, fixes, secret values and secret
hashes. CI uploads only these reports, including after failure.

Each report is at most 1 MiB and includes at most 2,000 finding locations. The
full candidate count and category totals remain; `omitted_finding_count` makes
any truncation explicit. Truncation never changes gate status. Source changes
between start and finish invalidate the measurement. Missing tools, malformed
results, incomplete dependency collection, timeouts and nonzero results without
findings are errors, not clean scans. A scanner's zero exit with secret
candidates is converted into a failing gate.

Exit status: **0 pass**, **1 findings**, **2 incomplete/error**, **3 not run (npm transmission approval absent)**. Artifact upload
failure also fails CI. Reports from a dirty working tree are development evidence,
not exact committed-source acceptance. The new runner has dedicated regression
tests for these boundaries; a focused test pass is not a full backend-suite pass.

## Reproduce locally

Run from the repository root. All virtual environments, caches and reports below
are outside the measured checkout. Python 3.12+ is required; CI uses 3.13.

```sh
python -m venv /tmp/loose-quality-tools
/tmp/loose-quality-tools/bin/python -m pip install --require-hashes -r tools/quality/requirements.lock
python -m venv /tmp/loose-quality-app
/tmp/loose-quality-app/bin/python -m pip install --require-hashes -r backend/requirements.lock
export UV_CACHE_DIR=/tmp/loose-quality-uv-cache
export XDG_CACHE_HOME=/tmp/loose-quality-cache
export NPM_CONFIG_CACHE=/tmp/loose-quality-npm-cache
/tmp/loose-quality-tools/bin/python scripts/quality_checks.py lint --output /tmp/loose-quality/lint.json
/tmp/loose-quality-tools/bin/python scripts/quality_checks.py format --output /tmp/loose-quality/format.json
/tmp/loose-quality-tools/bin/python scripts/quality_checks.py types --app-python /tmp/loose-quality-app/bin/python --output /tmp/loose-quality/types.json
```

Use the same command for `locks`, `python-audit`, `secrets` and `workflows`.
The npm audit requires the named npm version and explicit permission described
below; without its opt-in flag the runner writes `not_run` and exits 3 before
invoking npm or reading the dependency tree. Preserve each exit
status; do not append `|| true` to obtain a successful gate. Advisory-service
network access is required for dependency audits; a blocked lookup is not a pass.

Intentional tool upgrades require all three tooling files and fresh verification:

```sh
uv lock --project tools/quality
uv export --project tools/quality --no-emit-project --no-header --format requirements-txt -o tools/quality/requirements.lock
```

## npm transmission approval

The optional manual input `npm_audit` defaults to false and is ignored for push
and pull-request events. Its job is skipped unless the operator explicitly
approves it for a manual dispatch. Default workflow summaries state that the npm
audit was not run; seven other checks continue independently. Do not dispatch it
on someone's behalf without their approval of this transmission.

The requested destination is **https://registry.npmjs.org** for a vulnerability
check of `frontend/package-lock.json`, including production, development,
optional and peer dependencies. Per [npm's audit endpoint documentation](https://docs.npmjs.com/cli/v11/commands/npm-audit/#audit-endpoints):

- The bulk endpoint receives package names and their version lists
- If bulk lookup fails, npm can send the **full dependency tree represented in
  package-lock.json**, together with npm/Node versions, operating system,
  architecture and NODE_ENV, to the same registry's quick-audit endpoint
- This is dependency/lock metadata, not an upload of application source files;
  private package names or Git dependency URLs can appear in that tree

The initial diagnostic npm audit returned findings, but the later re-audit was
blocked on transmission authorization and was not retried. Its absence is not a
pass. The owner's separate dependency fix does not grant permission to transmit
metadata again. After explicit approval, one local invocation can use:

```sh
/tmp/loose-quality-tools/bin/python scripts/quality_checks.py npm-audit --allow-npm-registry-audit --output /tmp/loose-quality/npm-audit.json
```

## Initial diagnostic baseline, 2026-09-30

The initial read-only reconnaissance used base revision `1f7fe672`, with ongoing
working-tree edits. These are preserved historical diagnostic counts, not clean
source acceptance or the final stricter gate measurement:

- 165 tracked Python files; Ruff found **741** lint findings and **154** files
  needing formatting. Largest categories: C408 219, B008 174, I001 162, F401 49
- Gradual backend mypy found **175** errors. Largest categories: union attribute
  44, argument type 35, index 25, operator 21, assignment 21. An AST-only inventory
  separately found 709/1,511 functions without return annotations and 625 with
  unannotated arguments across all tracked Python; these are not mypy errors
- pip-audit checked **78** backend/tool graph entries with no known advisories
- Reconnaissance with the preinstalled npm 11.9.0 found **two affected packages**, including critical
  [GHSA-5xrq-8626-4rwp](https://github.com/advisories/GHSA-5xrq-8626-4rwp) and moderate
  [GHSA-82fw-gwwq-j7x9](https://github.com/advisories/GHSA-82fw-gwwq-j7x9), against
  Vitest 4.0.18 / its mocker. The owner subsequently pinned Vitest 4.1.11 and
  regenerated the frontend lock; the original failed scan is not rewritten
- Initial secret reconnaissance found **782** candidates: 741 high-entropy hex,
  25 keyword, 15 basic-auth and one private-key marker. That first pass retained
  upstream lockfile filtering, so it is not the final no-file-exemption count.
  Most observed candidates are fixture/demo text and historical content digests;
  none are auto-accepted. A separately inspected expired signed URL was at
  `.github/workflows/m63-transfer-once.yml:15`. The owner retired that obsolete
  workflow from the current tree, preserving Git history. No query value is
  reproduced here, and no credential was tested online
- Offline workflow auditor: **34** findings: 13 anonymous definitions, nine
  unpinned images, eight checkout-credential persistence, two template expression
  injections and two missing concurrency limits. Existing-workflow repairs are
  coordinated separately; this change does not bulk-rewrite those files

The inherited formatting/type/lint debt and unresolved secret candidates remain
visible failures. They must be remediated or individually investigated in
separately reviewed changes. New gates do not weaken frozen evaluation labels,
quality targets, historical failures or ordinary coverage thresholds.

## Gate implementation verification

Local working-tree verification on 2026-09-30 passed **29 dedicated runner
regressions**, both from the repository root and from the backend test working
directory. The new runner and tests pass their pinned Ruff lint/format checks;
the runner passes its gradual mypy check. Exact lock/export parity and the
whole-repository offline workflow audit passed with **zero findings** after the
separately owned workflow repairs. Earlier workflow failures remain documented.

A subsequent full working-tree scan still reported lint/format/backend-type and
secret-candidate failures. The detailed source-free reports retain their own
source digest and scope; these counts can change during concurrent development.
The npm re-audit is **NOT RUN** pending transmission approval. No hosted run or
clean committed-source acceptance of this newly added workflow is claimed here.


The aggregate **Complete quality and security acceptance** job requires every
independent check and a genuinely successful npm audit. It fails when the audit
is skipped, cancelled, failed or not authorized, including ordinary push/PR runs.
Thus default-off transmission never turns missing security evidence into a green
release/readiness gate. This is a new dedicated gate, not a disabled predecessor.
Before authorizing the standard npm path, inspect lock metadata offline for private
identifiers, credential-bearing URLs and other secrets. Ordinary approval cannot
authorize sending highly sensitive credential material; remove such material from
the payload or use a separately reviewed restricted advisory client.
