# M6.4 measured diagnostic development delivery

## Scope and source

Repository `azerish25-ux/ai-quality-intelligence`, existing `main`. Starting source:
`580ab0734602aff9a182f8bb56ea68201988f836`. Coordinated implementation:
`39c4ea034fe5f412a4a2b79f164a0cac68fe80b9`. Accepted diagnostic execution source:
`dc0aaf1202bffc7557f1a04b0aa5afdfdc8ce5fb`.

[Diagnostic run 36519135228](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36519135228),
job `109247955935`, passed fresh component execution, PostgreSQL API/worker replay,
independent scoring, source cleanliness, frontend unit tests/build and all sixteen
actual-API desktop/narrow Chromium diagnostic journeys. Captured desktop/narrow
screenshots were inspected. This is scoped development acceptance, **not completed
M6.4 quality recovery, full M6, or renewed held-out generalization**.

The four new contracts cover atomic transfer measurements, tenant isolation,
status-only test expectations and isolated runner memory-limit termination.
They extend the existing adapter/analyzer/publication path. Independently computed
predicates reject forged categories, claims and execution bindings. Competing
product-risk observations block a non-product disposition. The existing reviewer
workspace shows missing, conflicting, rejected and unresolved diagnostic states.
See [diagnostic contracts and reproduction](diagnostic-quality.md).

## What actually ran

The clean companion remains pinned to
`13bdd62c924a3230825b6d9304f449f887c8e7fe`. JDK 21 executed twelve interventions
and twelve passing controls over **three already-known mechanisms**, with a
separately executed scalar oracle and richer measured observations. Four related
variants per mechanism are not independent families. No companion changes were
published. This is component execution, not HTTP/PostgreSQL financial effects.

Twenty additional synthetic cases exercise the four new contracts and missing
observations. They are not actual kernel OOM, authorization-server, or database
fault executions. All thirty-two cases traverse the real FailureLens PostgreSQL,
ingestion API, durable worker and evidence-publication validator.

| Measured development result | Value |
|---|---:|
| Cases / catalogue groups | 32 / 7 |
| Fresh component interventions / passing controls | 12 / 12 |
| Synthetic cases | 20 |
| Product / test / infrastructure / insufficient / known-flake cases | 20 / 4 / 4 / 4 / 0 |
| Correct published classifications | 32/32 |
| Product-defect recall | 20/20 |
| Product abstentions / dangerous dismissals | 0/20 / 0/20 |
| Non-abstained coverage on non-abstention labels | 28/28 |
| Correct missing-measurement abstentions | 4/4 |
| Independently supported published claims | 28/28 |
| Identical substantive analyses per case | 5 |
| Broad five-category macro F1 | Undefined: no known-flake cases |
| New held-out cases | 0 |
| External model calls | 0 |

Zero observed dangerous dismissals is not a population-risk guarantee. Variants
share mechanisms. The retained report shows uncertainty, unchanged minimum-corpus
failures, unsupported broad five-category acceptance and incomplete adversarial
coverage rather than treating this slice as a replacement benchmark.

## Verification and retained evidence

The full local backend suite before retention additions passed 670 tests, with
four PostgreSQL-only skips. Combined line/branch coverage was 83.63% against the
unchanged 75% gate. The focused implementation group passed 171 tests: 112 new
diagnostic/evaluator regressions and 59 existing contract regressions. Local
results are separate from GitHub PostgreSQL/browser execution.

The accepted workflow passed all 39 frontend unit tests and the production
TypeScript/Vite build. Its sixteen browser checks retain every expected finding,
missing-measurement state, resolvable supporting reference and narrow-layout check;
retries remain zero. No assertion or numerical target was reduced.

The compact lossless snapshot and exact report live under
`evaluation/reports/diagnostic-development-v1/`. `retention.json` records the
original GitHub artifact digest/expiry separately from the deterministic ZIP/XZ
repack. File contents, labels, predictions and measurements are unchanged. Run:

```sh
python evaluation/verify_diagnostic_snapshot.py
python -m pytest backend/tests/test_diagnostic_snapshot.py
```

This checks bounded files/archives, exact digests and independent rescoring. It
is **not fresh companion, PostgreSQL or browser execution**. Seven retention
regressions cover tampering, symlinks and trailing compressed data. Browser images
remain bounded CI artifacts rather than permanent repository assets.

General verification for the executed source is
[CI run 36519135251](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36519135251).
Subsequent retention/documentation commits require their own exact-revision CI;
this record does not grant a later commit the tested source's results.

## Retained failures and corrections

Run `36517924155` on `aec6c655f22219384835af3a95265d14596ea807` produced correct
development diagnoses but failed the clean-source gate because packaging created
`backend/build` and package metadata. Installation now builds an exact committed
archive outside the measured tree. The cleanliness gate remains strict.

Run `36518321762` on `0b2e72f955a920bb58be9d132a625a56aa60e268` passed measurement
and build checks but failed all sixteen browser checks. The test read the run-detail
response as a bare run and generated `project=undefined`. It now validates the
actual `{run, failure_types, failure_count}` envelope and run/project identity.
The corrected source passed all sixteen checks. The existing campaign workflow's
same packaging-generated cleanliness failure was corrected without waiving its
integrity or failed quality targets.

## Still incomplete

The historical 260-case benchmark and 264-case campaign remain separate and
unchanged. Their failed quality targets are not resolved by these 32 development
cases. In particular, the retained benchmark's 0/44 product recall, 0.3048 macro F1
and 18/92 non-abstained coverage remain historical failures, not rewritten successes.

A newly frozen, genuinely family-held-out evaluation with at least 100 test cases,
40 product cases across 20 distinct product mechanisms, a complete temporal
backtest, broader adversarial coverage and additional actual producer evidence
remain required. M2/M5 residuals and M7-M10 work also remain. No paid provider,
public deployment, release or change to the companion repository was performed.
