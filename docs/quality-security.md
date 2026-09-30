# Dedicated quality and security gates

The `Loose Thread quality and security` workflow is independent of the existing
ordinary regression CI. Seven matrix jobs run on pushes, pull requests and
manual dispatch, with `fail-fast: false`. The npm audit is a separate, default-off
manual job because it transmits lock-derived metadata to a third party. Skipped
npm work is explicitly **NOT RUN**, never a pass. A failing scan is a failing job. There
is no `continue-on-error`, automatic clean baseline, ignored advisory, severity
waiver or automatic dependency fix. Explicit secret-candidate reviews use the
source-bound contract below; they do not waive unexplained credentials. A green existing regression workflow does
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
  query check records only a location and rule name. Every candidate remains in the raw report; unresolved candidates and invalid
  or stale review entries fail. A candidate is **not** proof that a real credential
  exists. Only explicit, exact source-bound reviews can resolve a candidate.
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
findings are errors, not clean scans. A scanner's zero exit with unresolved secret
candidates or review-policy errors is converted into a failing gate. Reviewed
locations remain visible with their decisions; raw, reviewed and unresolved
counts are separate, and truncation does not change any of them.

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

The initial diagnostic npm audit returned findings. The exact-source re-audit is
**NOT RUN**; a dependency update alone is not fresh audit evidence. After explicit
approval of the described transmission, one local invocation can use:

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
  Vitest 4.0.18 / its mocker. Vitest was subsequently pinned to 4.1.11 and
  the frontend lock regenerated; the original failed scan is not rewritten
- Initial secret reconnaissance found **782** candidates: 741 high-entropy hex,
  25 keyword, 15 basic-auth and one private-key marker. That first pass retained
  upstream lockfile filtering, so it is not the final no-file-exemption count.
  Most observed candidates are fixture/demo text and historical content digests;
  none are auto-accepted. A separately inspected expired signed URL was at
  `.github/workflows/m63-transfer-once.yml:15`. That obsolete workflow was retired from the current tree, preserving Git history. No query value is
  reproduced here, and no credential was tested online
- Offline workflow auditor: **34** findings: 13 anonymous definitions, nine
  unpinned images, eight checkout-credential persistence, two template expression
  injections and two missing concurrency limits. Existing-workflow repairs are
  coordinated separately; this change does not bulk-rewrite those files

These historical formatting/type/lint and secret-candidate failures are retained
as diagnostic evidence. Current results require a new measurement and explicit
review of each secret exception. New gates do not weaken frozen evaluation labels,
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


## Reviewed secret candidates

`tools/quality/reviewed-secrets.json` is an explicit review index, not scanner
input and not an automatically accepted baseline. Its bounded canonical parts live
in `tools/quality/reviewed-secrets/`; the index and every part remain in scan scope. The complete original offline
scan still runs across every supplied file, including this policy. A second pass
with the same pinned detector configuration reconciles all candidate identities
and every detected line occurrence before any review can apply. Signed-URL
findings cannot be excepted by this policy.

Each entry names one exact file, detector and matched-value SHA-256, binds the
complete source-file digest and sorted occurrence/context digests, and records
a classification, reason, evidence, reviewer, date and review reference. Context
is the matched line and up to two surrounding lines on each side. Classification
separates integrity identifiers, synthetic test canaries, nonsecret configuration
literals and authenticating public disposable-database defaults. Demo credentials are not nonexistent credentials:
their reviewed local/CI scope must not be reused for production.

New values, changed files/context, extra occurrences, different paths or detectors,
and scanner/configuration changes invalidate the relevant review. Duplicate,
unknown, malformed, deleted/stale or out-of-inventory entries fail the gate; one
invalid entry disables all policy acceptance for that measurement. Review metadata
is not an access-control mechanism: a policy change requires repository review of
the actual source, meaning and exposure. No generator or automatic accept command
is provided. Real private credentials require removal/rotation, never an exception.

The policy is canonical JSON with an exact schema and no self-referencing entries.
Legacy schema 1 remains supported only without a parts directory. Schema 2 has an
ordered manifest with per-part counts and SHA-256 digests plus the exact logical
schema-1 digest. It permits at most 64 parts, each smaller than 80,000 bytes. Missing,
extra, reordered, duplicate, unscanned or noncanonical parts fail closed. Reads use
directory-relative descriptors and reject symlinks and nonregular files, including
symlinked ancestors. Disk inventory and scanner inventory must both match.
Parsing is bounded in aggregate to 4 MiB, 2,000 entries, 2,048 characters per text field and
10,000 detected-line occurrences per entry. Excessive JSON nesting fails with a
fixed source-free error; JSON nesting is limited to twelve levels.
No policy file receives a scan exemption. Hash candidates in specific value, source
and context fields, and the index's recomputed part/logical digests, are classified
as validated policy metadata only after every field
has been recomputed against its referenced source candidate. Acceptance also binds
the detector, exact file and field line, matched-value digest and complete occurrence set. An arbitrary hash in
a reason, added field, copied location or mismatched guard remains unresolved or
invalidates the policy. This avoids a recursive hash baseline without trusting
hash-like strings generally.

Reports retain raw candidate locations and counts, detected-line occurrence totals, reviewed
classification totals, unresolved counts and bounded policy-error codes. Unresolved locations are listed
first so reviewed metadata cannot displace them from a bounded report. They
never include values, candidate/context fingerprints, reasons or source snippets.
Source-candidate and validated policy-metadata counts are also reported separately.
Policy hashes belong only in the reviewed artifact; do not attach private raw
scanner output to CI. A passing secrets gate does not certify scanner blind spots,
archives, Git history, unknown credentials or unchanged defaults reused elsewhere.

### Review record, 2026-09-30

The earlier clean source `f7d847f` contained 892 distinct candidates across 1,724
detected lines: 844 integrity identifiers, 26 synthetic test canaries and 22 public
disposable PostgreSQL credential candidates. Independent current-source review
checked subsequent formatter/import/type cleanup against that source and explicitly
reviewed formatter-exposed candidates and occurrence changes. Frozen corpus and
historical report bytes remain unchanged. The clean source `9369ee2` review contained 900 source candidates: 845 integrity
identifiers, 32 synthetic canaries, 22 public disposable PostgreSQL credential
candidates and one policy-path configuration literal. The five quality-runner
additions are four fake scanner-result literals and that exact local path.
The individual policy entries record the current source guards; the earlier scan is not presented as current acceptance.

The M7 application update explicitly reviewed 15 additional candidates: three
Alembic revision identifiers, ten synthetic fixture/redaction canaries and two
authenticating public disposable-PostgreSQL fixture candidates. It preserves all
897 unchanged records and updates only three existing `ci.yml` records for the
new disposable provider-browser service and the unchanged pinned-revision context.
The resulting policy contains **915 source candidates**: 848 integrity identifiers,
42 synthetic canaries, 24 public disposable PostgreSQL credential candidates and
one configuration literal. The synthetic account passwords authenticate only their
isolated fixtures; the provider-token and redaction canaries are not real provider
credentials. The PostgreSQL fixture password really authenticates its disposable
database. The optional deployment overlay instead requires private operator-owned
database settings with no published default; review rejected the initial copied
demo password in that broader deployment scope.

These reviews bind the final inspected source files and complete detected-line
occurrences, including the credential-echo and preview-boundary regressions.
Policy-metadata totals and gate status must come from the current full scan after
the reviewed edits; neither earlier counts nor this review text imply acceptance.
No credential verification, network audit, real-provider request or production
deployment was performed for this review.

The 77 dedicated runner regressions exercise scanner reconciliation, source and occurrence
mutation, new/copied candidates, stale/deleted/duplicate entries, strict policy
shape and metadata handling, source-free counts, signed URLs, default-off npm and
aggregate rejection of a skipped audit. Current-source gate reports provide the
actual measured revision/digest and working-tree state; this review record alone
is not a full quality/security acceptance claim.

### M8 review record, 2026-09-30

The M8 GitHub report, evidence-export and publication update explicitly reviewed
six additional candidates: two public Alembic revision identifiers and four
synthetic fixture canaries or placeholders. The source-bound policy now contains
**921 source candidates**: 850 integrity identifiers, 46 synthetic test candidates,
24 public disposable PostgreSQL credential candidates and one configuration
literal. All **912 unchanged records** remain byte-for-byte identical. Only the
source/occurrence guards of the two existing disposable-database records in
`github-report.yml` and the existing outsider-account record in
`test_github_snapshot.py` were refreshed; their classifications, reasons and
evidence are unchanged.

The new malformed-export canary verifies that rejected payload text does not
enter Action status or step-summary output. The evidence-download password really
authenticates only the temporary outsider account in the disposable in-memory
test database. The receipt-history password-hash placeholder is unused for
authentication because the test supplies explicit principals. The frontend
observation placeholder is inert evidence-schema rejection data under a stubbed
fetch response. None is a private provider/GitHub credential or a production
account default. The two existing workflow credentials still authenticate only
their disposable PostgreSQL service; this update does not expand that scope.

An independent offline review inspected the frozen source and every new or
changed candidate context, including final migration, receipt-revision and
evidence-download changes. The 77 quality-runner regressions passed with scanner,
schema, source, occurrence and metadata guards unchanged. Raw policy-metadata
totals, unresolved counts and gate status must come from the full current-source
scan after these edits. A dirty-tree measurement is development evidence, not
exact committed-source acceptance. No credential verification, network audit,
real-provider request or live publication was performed for this review.


### Bounded policy packaging, 2026-09-30

The 1,047,671-byte original canonical policy is retained in the verified M8 recovery
checkpoint. Before changing any review, independent reconstruction of sixteen
canonical parts reproduced all original bytes: SHA-256
`d0cea726eaa156d5d2fe5437c87a6104f601113e074035bcb52ebbdb7fcbe016`, 921 ordered
entries and 1,760 occurrence guards, with identical scanner configuration. The
largest part is 69,985 bytes. Packaging does not reorder, infer or generate reviews.

The new loader changes `scripts/quality_checks.py`, which is itself covered by
`quality-regression-0001`. The original scanner correctly rejected all policy
acceptance until this entry's guard was reviewed. Independent source inspection
confirmed the unchanged `SECRET_REVIEW_FILE` literal is still the same nonsecret
repository path. Only that entry's file digest and occurrence/context guards were
refreshed; its candidate, classification, reason and provenance are unchanged.
The other 920 entries, including four guards for the unchanged legacy test file,
remain identical. The migration proof and explicit before/after guard delta are
retained with verification evidence. This is an explicit source review, never an
automatic accept operation.

All 129 focused tests pass, including 49 new multipart regressions. They exercise
file/line/value metadata binding, recomputed-digest attacks, reordered entries,
scanner inventory omissions, malformed manifests, duplicate entries/review IDs,
symlinked files/ancestors, named pipes, canonical parsing and resource limits.
Required npm audit remains NOT RUN; this packaging change cannot make aggregate
security acceptance pass without its required audit.
