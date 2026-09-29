# M6.4 diagnostic-quality development

This delivery extends the existing deterministic analyzer, manifest 2.0 contract
adapter, publication validator, campaign scorer and reviewer workspace. It does
not introduce a third inference pipeline or substitute one historical benchmark
for another. Full M6 and renewed held-out quality acceptance remain incomplete.

## New observable relations

The additive `contract-observations-v1` measurement variants are:

| Kind | Supported interpretation | Required scope and counterexamples |
|---|---|---|
| `atomic_transfer` | Product-risk investigation when both account deltas disagree with a resolved all-or-nothing receipt | One request, distinct accounts, integer minor units, isolated snapshots and zero concurrent writers. A rollback requires both balances unchanged. Conservation alone cannot hide an incorrect transfer amount. |
| `tenant_isolation` | Product-risk investigation when returned resource content belongs to another tenant | A tenant-member principal, declared same-tenant policy, matching requested/returned resource identity and observed status. A success status alone is insufficient; a denial status cannot hide leaked body content. |
| `status_expectation` | Test-expectation investigation when the actual status is allowed and the assertion requires a disallowed status | Matching versioned/deployed contract digests and a status-only assertion. If the response violates the contract, do not blame the test. If two permitted statuses differ, require more context. |
| `runner_memory_limit` | Infrastructure-interruption investigation supported by runner memory and termination observations | An isolated test-runner cgroup, matching killed process, bounded memory measurements, increasing OOM-kill counter and signal 9. Host-wide events, counter resets and system-under-test processes cannot establish this diagnosis. |

These are **reported observations under a declared contract**, not proof that an
arbitrary producer is truthful. They do not prove the responsible implementation
or why resource exhaustion occurred. Non-product findings do not clear other
product behavior. A competing product-risk signal blocks a non-product disposition
regardless of score margin. Missing, malformed, cross-execution or conflicting
observations preserve abstention. Previous v1 variants remain supported.

The publication boundary independently recomputes category, bounded wording and
predicates against authorized immutable derivatives. It rejects category swaps,
forged evidence IDs, altered text and predicates. The separate evaluation scorer
has its own arithmetic, scope checks and claim strings; it does not call the
runtime inspector to certify the runtime's answer.

## Reviewer-visible diagnostic gaps

`Analysis.validation_results` adds optional `diagnostic_findings` and
`diagnostic_gap` fields. The existing failure workspace renders them; older
analysis records need no migration and never acquire invented findings.

- `publication_rejection`: a proposed result did not survive publication checks.
- `missing_or_invalid_observations`: required observable data is absent or invalid.
- `contradictory_observations`: measurements or competing diagnostic signals conflict.
- `unresolved_evidence_or_capability`: the system cannot safely separate a data gap
  from a capability gap; it does not pretend that a hidden root cause is known.

A conforming narrow check is explicitly not a declaration that the failure or
product is harmless. Finding reasons contain bounded descriptions, not new copies
of ungoverned raw observations.

## Fresh development measurements, not fresh held-out families

`integrations/ledgerguard/DiagnosticProbe.java` executes the pinned companion's
operation fingerprints, projection snapshots and weekly calendar calculation.
`diagnostics.py` uses the same source inventory, isolated class-shadow mutations,
JDK 21 and independent scalar oracle as the original component harness. Each of
12 controlled interventions has a passing control and a separately executed
scalar probe; richer observations must agree with that probe's actual return.
No companion source is modified or published.

These are **three already-known mechanisms with four related variants each**.
They are not twelve independent families, not new held-out examples, and not
HTTP/PostgreSQL transaction execution. The weekly component dates are ordinary
January local dates, not a fresh DST experiment. Their replay clock is synthetic;
actual execution provenance is recorded separately.

Twenty additional synthetic cases exercise the four new diagnostic variants:
four positive nuisance variants and one missing-measurement case per kind.
They are explicitly not real database, authorization-server or kernel OOM
executions. Kernel OOM must never be fabricated by pretending `kill -9` is an
OOM event. Together this development slice has 32 cases, seven catalogue groups,
12 actual component interventions, 12 separately retained passing controls and
20 synthetic cases. Controls and repeated analyses do not inflate case counts.

## Reproduction

Use an empty disposable database and a new output location. The companion path
must match `integrations/ledgerguard/source.json`; do not change that pin merely
to obtain a favorable result.

```sh
python integrations/ledgerguard/diagnostics.py \
  --ledgerguard-source /path/to/pinned-ledgerguard \
  --output /tmp/failurelens-diagnostics/corpus
# Configure FAILURELENS_DATABASE_URL, FAILURELENS_ARTIFACT_ROOT and DEMO_MODE=true.
# PostgreSQL must first be migrated: (cd backend && alembic upgrade head).
python evaluation/replay_campaign.py \
  --inputs /tmp/failurelens-diagnostics/corpus/inputs \
  --output /tmp/failurelens-diagnostics/replay --confirm-disposable-database
python evaluation/campaign_harness.py \
  --corpus /tmp/failurelens-diagnostics/corpus \
  --replay /tmp/failurelens-diagnostics/replay \
  --output /tmp/failurelens-diagnostics/report --development-only
```

Omitting `--ledgerguard-source` deliberately creates only the 20 synthetic
fixtures for local regression tests. It does not claim companion execution.
The producer freezes inputs, labels, family assignments, policy, source and
execution provenance before replay. Fault configuration and oracle receipts
remain outside the public input directory. Process-local tripwires are not an OS
sandbox. The ordinary application never imports this producer or its labels.

`--development-only` refuses a corpus containing calibration or test cases. It
reports the original corpus-minimum failures and unchanged numerical targets;
it does not reinterpret them as achieved held-out acceptance. The default scorer
still requires full corpus minimums and a nonempty test split. Add
`--enforce-quality` to make missed numerical targets return exit 2. Integrity,
unsupported published claims and mandatory safety failures return exit 1.
A development report must not be served as the existing campaign test report.

The diagnostic CI job uses fresh PostgreSQL, five analyses per case and the
ordinary API/worker/evidence path. Browser checks inspect each contract's actual
persisted analysis at desktop/narrow widths and the missing-measurement state.
Job artifacts retain corpus, producer receipts, predictions, report and images.
A green development job does not overrule either frozen benchmark's failed
quality targets. Exact executed revisions/results belong in `PROGRESS.md`.

## Remaining acceptance work

The old campaign and `benchmark-v1` bytes, failed measurements and thresholds
remain unchanged. This work does not establish a recovery on their unknown
product mechanisms. Test failures already inspected remain regression evidence.
A renewed generalization claim still requires a newly frozen, genuinely
family-held-out evaluation of at least 100 test cases, including at least 40
product cases across 20 distinct product mechanisms, plus the required temporal
backtest, broader adversarial program and observable-evidence adjudication.
Creating new names for the seven diagnostic relations is not a substitute.
