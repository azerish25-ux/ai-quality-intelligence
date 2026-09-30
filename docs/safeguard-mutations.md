# Synthetic safeguard mutation sensitivity

This opt-in check asks whether existing focused regressions detect seven deliberate
safeguard bypasses. It executes the actual application functions and existing tests,
first unchanged and then altered in separate Python processes. It is **targeted
regression sensitivity**, not independent security certification, an OS sandbox
attestation, a classifier-quality score or renewed held-out acceptance. Frozen
corpora, labels, thresholds, evaluators and historical reports are unchanged.

## Reproduce

Use Python 3.12+ and the locked backend development dependencies. For committed
measurements, start from a clean checkout and use the existing archive installer:

```sh
bash scripts/install_committed_backend.sh
PYTHONPATH=backend/src:. python -m evaluation.mutation_runner \
  --confirm-synthetic-mutations --output /tmp/safeguard-mutations/report.json
```

The destination must be fresh and outside the checkout. Overwriting a report is
refused, including an existing frozen-report destination. Both Make and direct
invocations require explicit opt-in:

```sh
make safeguard-mutations \
  MUTATION_ARGS='--confirm-synthetic-mutations --output /tmp/safeguards-second.json'
```

`--case redaction` selects a focused probe; repeat `--case` to select several.
`--timeout 90` sets the per-process limit. Local development can explicitly use
`--allow-dirty-source`; those reports carry `development_only: true`, the current
HEAD and a separate digest of actual code/test bytes. They do not certify the HEAD
commit. CI never passes this option. Any source change during execution invalidates
all observed kills as errors, including in development mode.

## Fixed mutations and existing regression oracles

The complete node IDs and descriptions live in `evaluation/mutation_cases.py` and
are recorded in every result. The current probes are:

- Authorization: return administrator access without project/role checks;
  `test_auth.py::test_viewer_is_project_scoped_and_cannot_mutate_reviews`
- Redaction: remove only the authorization-header pattern;
  `test_redaction.py::test_redacts_declared_sensitive_classes_and_preserves_evidence`
- Missing citation: silently substitute an available evidence ID for an unresolved
  citation; `test_evidence_validation.py::test_forged_evidence_reference_is_withheld`
- Retry-as-run: count retry attempts as independent runs in the reported denominator;
  `test_history.py::test_retries_collapse_and_absent_tests_are_not_counted_as_passes`
- Timeout-to-flake: replace timeout abstention with `known_flake`;
  `test_analysis.py::test_timeout_without_corroboration_abstains`
- Missing-shard/input: return complete scope when an expected input is absent;
  `test_service.py::test_incomplete_run_is_explicit`. This exercises the shared
  expected-input completeness boundary, not a new distributed shard execution
- Stale report: reuse the fixture's synthetic tested SHA instead of the freshly
  observed PR head; `test_github_publication.py::test_stale_before_first_write_does_not_publish`

The redaction inputs, identities and revision values are synthetic. GitHub uses the
existing `httpx.MockTransport` REST fixture and the application database is disposable
in-memory SQLite. There is no paid provider invocation or real GitHub write.

## Isolation and result meanings

`evaluation/mutation_plugin.py` loads only via an explicit pytest plugin argument
and a runner-set opt-in environment variable. There are no production feature flags
or runtime imports of the mutation code. Only in-memory functions and imported
aliases are patched; there is no duplicate checkout/worktree or tracked-source edit.
Each baseline and mutant has a fresh process, private temporary directory, artifact
root and test database. The child does not inherit tokens, configured databases,
telemetry destinations, Python hooks or extra pytest plugins. Socket connection
attempts are blocked as an additional test tripwire, not an OS-level isolation claim.

All selected baselines run before any mutants. A failing baseline prevents its
mutant from running. The parent checks a fresh nonce, exact collected test ID,
loaded runtime source location, exit code, all pytest phases and evidence that the
mutation was applied and exercised. Status meanings are deliberately conservative:

- `killed`: its baseline passed; the exercised mutant produced an `AssertionError`
  originating in the selected test body; setup/teardown and provenance succeeded
- `survived`: its baseline passed; the mutation took effect and the test still passed
- `error`: collection or import failures, missing dependencies, skipped tests,
  setup/teardown failure, missing/mismatched receipt, unrelated runtime exceptions,
  timeout, ineffective mutation or changed/unavailable source provenance

Errors never count as kills. The command succeeds only when every requested
baseline passes and every mutant is killed. This is a small authored mutation set;
seven kills do not imply all faults or all weaknesses are detectable.

The compact fresh JSON contains source SHA, dirty/development state, source/test
content digest, each exact test ID and test-file digest, baseline/mutant results,
phase/exception origin, exercise counts, duration and captured-output digest. Raw
fixture text, credentials and subprocess logs are not retained in that report.
A report produced on dirty bytes remains development evidence after a later commit.

## Regression and CI coverage

`test_mutation_safeguards.py` checks real subprocess mutation kills and isolation,
real missing-test collection failure, explicit opt-in, overwrite prevention,
baseline ordering, dirty-source rejection, provenance invalidation, timeout,
credential/environment isolation and false-kill classifications. Run it with:

```sh
PYTHONPATH=backend/src:. python -m pytest backend/tests/test_mutation_safeguards.py
```

The dedicated `safeguard-mutations.yml` workflow uses pinned existing Actions,
read-only repository permission, the locked committed-source installer, no external
application services and a fresh uploaded JSON report. Normal CI dependency/artifact
services remain required. It is separate from frozen classifier-quality gates.

`make security-test` now covers current authorization, ingestion/archives, safe binary
and trace evidence, publication/citation validation, adversarial capability checks,
history, typed contracts, provider proposals, operational lifecycle and telemetry
boundaries as well as these runner regressions. It does not replace real producer,
PostgreSQL, Docker, browser or frozen benchmark verification.
