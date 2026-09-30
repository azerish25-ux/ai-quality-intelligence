# Loose Thread delivery ledger

## M6.4.1 closeout — verified 2026-09-29

Canonical repository: `azerish25-ux/ai-quality-intelligence`; delivery branch: `main`.
Verified implementation source: `1381cfafb0d67f129d2e5ae12f6cd1315a2a8d02`,
tree `a178a04d67bd43da570624ec4c57d0539d1f166b`.

**The clean-source CI repair and scoped transaction-finality delivery are verified.
Full M6 and the complete master project remain PARTIAL.** A later documentation
commit does not change the source named by these measurements and needs its own CI.

The preceding ledger is preserved byte-for-byte in
[PROGRESS-through-M6.4.1.md](https://github.com/azerish25-ux/ai-quality-intelligence/blob/2de918e5709d12afba2e415edd3c020fac83ed7c/docs/PROGRESS-through-M6.4.1.md), original blob
`4921e06d9a3c611b353bb35ee179365d2a499dd7`. Its local-only, blocked and NOT RUN
statements describe their original checkpoints, not the subsequent delivery below.
Earlier archived ledgers, frozen corpora, labels, thresholds and reports are unchanged.

### Implemented and published

- `aca0d1a2cea056ba2b07c7f67c45f4df304ebf27`: ordinary backend CI uses
  `scripts/install_committed_backend.sh`. It installs a Git archive of the exact
  commit outside the measured checkout, refuses uncommitted source and checks
  source cleanliness and unchanged HEAD after installation. No broad ignore rule
  or integrity exemption was added. Campaign provenance now includes changed paths.
- `9b68283d1e5e32115e76ab1a45c3efe5310089d4`: explicitly installs the existing
  setuptools build backend in the development environment for real offline
  package-build regressions. Runtime dependencies and coverage gates are unchanged.
- `1381cfafb0d67f129d2e5ae12f6cd1315a2a8d02`: retains actual PostgreSQL evidence,
  adds bounded independent snapshot verification/export, and names failed integrity
  gates together with source changes in the finality replay regression.

There are **42 new tests**: 25 real-build/source-provenance regressions and 17
retention/oracle/scope regressions. Modified, staged, deleted and untracked measured
source remain detectable. Corrupted artifacts, fabricated PASS flags, false
held-out claims and overwritten export destinations are rejected.

### Exact-source verification

At `1381cfafb0d67f129d2e5ae12f6cd1315a2a8d02`:

| Verification | Actual result and evidence |
|---|---|
| Ordinary CI | All ten jobs passed in [36575299066](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36575299066): backend, producer fixtures, frontend, legacy evaluation, component execution/evidence integrity, Docker validation/builds and four browser lanes. |
| Backend PostgreSQL suite | **881 passed, zero failed or skipped**, one deprecation warning; **86.13% branch-aware coverage**, unchanged 75% gate. [Job 109429887731](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36575299066/job/109429887731). The log confirms installation leaves the measured source clean. |
| Actual finality execution | [36575299122](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36575299122), job `109429246401`, passed actual HTTP/PostgreSQL controls/interventions, API/durable-worker replay, independent scoring and desktop/narrow journeys. |
| Campaign execution | [36575299051](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36575299051) passed its existing integrity/safety and API-backed browser checks. This is not a waiver of quality targets. |
| Frozen benchmark | [36575298977](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36575298977) **FAILED the unchanged quality-target step** after passing replay, integrity scoring and desktop/narrow browser verification. No thresholds or cases were altered to turn it green. |
| Local targeted verification | 90 selected finality/provenance/retention tests passed on the clean exact source. This includes 48 existing tests plus 42 new tests; local SQLite replay is not local PostgreSQL execution. |

The fresh finality report was downloaded and its artifact SHA-256 verified:
`a9fca10b57753681097c8de0cc50761dcd199bdd7752b76259a26585719980e1`
(artifact `11037146300`). It reports eight cases, four executed fault/control pairs,
one mechanism, four synthetic insufficient cases, four supported published claims,
twelve valid citations and five repeated analyses. All integrity gates pass;
five-category macro F1 is undefined and full corpus minimums fail.

Browser artifact `11036906385` was checksum-verified
(`365d80c53832936dfa4f3baf552e3e94c7ffc7f48ce624c3328d240ab3a3e78f`).
Representative desktop/narrow diagnostic captures were visually inspected, including
violated and missing-observation states. Their text retains the investigation and
non-reassurance boundary. These are actual captured diagnostic regions, not a claim
that a new whole-dashboard visual audit was performed.

### Preserved failures and their resolution

At `b7327b4`, backend CI reported 838 passed and one failure because in-place
packaging created untracked `backend/src/failurelens.egg-info/`. The clean-source
integrity gate correctly rejected that measured checkout. The isolated archive
installation fixes the cause rather than bypassing the check.

The first repair run at `aca0d1a`, [36573002193](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36573002193),
passed the original finality regression but exposed two new offline build tests
without setuptools in the clean Python 3.13 test environment (862 passed, two
failed). The explicit development dependency fixed that prerequisite. Backend job
`109425649445` at `9b68283`, run `36574064400`, then passed; all 881 tests passed at
`1381cfa`. No tests were skipped or assertions weakened to resolve these failures.

### Permanent original execution evidence

The first successful actual finality execution belongs to
`b7327b437d8fc4cb009918d1d4d31b6bf36f508a`,
[run 36567980376](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36567980376),
job `109404555847`. It is retained independently of the expiring CI artifact in
[transaction-finality-postgresql-v1](../evaluation/reports/transaction-finality-postgresql-v1/README.md).

All 48 original artifact member bodies are preserved byte-for-byte, including
public inputs, safe derivatives, predictions, exact report/metrics, independent
SQL/receipt oracles and diagnostic-gap audit. Metadata records the original
artifact digest, each retained file digest and the documented lossless repack.
The earlier all-synthetic SQLite snapshot remains separate and unchanged.

```sh
python evaluation/verify_finality_snapshot.py
python evaluation/verify_finality_snapshot.py --extract-to /tmp/finality-retained
```

The export destination must not exist. Both commands verify bounded archive
extraction, exact digests, independent rescoring and recomputed paired oracles.
They do **not** claim fresh Java, Docker, PostgreSQL or browser execution.

### Remaining boundary

The experiment injects a controlled JDBC early commit in disposable copies of a
pinned companion, not a defect in unmodified LedgerGuard or PostgreSQL. Four amount
variants remain one mechanism. Labels are agent-reviewed, not independently blinded
or expert-adjudicated. The companion repository was not modified or published to.

No new held-out acceptance is claimed. Broader diagnostic coverage, genuinely new
held-out families, a complete temporal/adversarial program, remaining M2/M5 scope,
optional-provider boundaries, full GitHub publication, operational hardening and
final audit remain unfinished. Continue from the actual failures using the existing
diagnostic-gap audit; do not reimplement the delivered finality relation or overwrite
historical reports. See [requirements-matrix.md](requirements-matrix.md) and
[transaction-finality.md](transaction-finality.md).

## M8 publication foundation — 2026-09-30

Starting source `af7a041`. Added an opt-in CLI GitHub publisher with exact-SHA,
trusted PR lookup, bot-owned project markers, bounded pagination, idempotent
reconciliation, safe stale-head replacement and sanitized operational failures.
The ingestion path remains secret-free and does not automatically publish.
Empty analysis reports now require review, and untrusted Markdown metadata is escaped.
See [publication contract](github-publication.md) for tests and remaining scope.
Frozen evaluation files, labels and thresholds are unchanged. This is not M8 or
full-project completion; live publication and complete report/workflow scope remain.

### M8 read-only projection

Added project-authorized API preview and a shared versioned JSON/Markdown projection.
Outcome denominators collapse retries; only the latest analysis per failure is
reported. Unvalidated legacy summaries and expired evidence are withheld; links,
images, mentions and declared secrets in metadata are neutralized. Five new API/data
regressions and a Markdown injection regression pass locally. The preceding publisher
batch is remotely delivered as `c3d98983c4e69fe66a3b640c5602bcce7df6489d` (tree
`884308c01c606e78c0d1db6674255c3361d74087`), with all seven workflows actually triggered.
A local complete suite attempt cannot substitute for CI: real producer fixtures were
not generated locally (16 explicit failures), and four PostgreSQL cases skipped.
No gate was removed. Exact-source CI results remain pending at this checkpoint.

## M7 optional-provider boundary foundation — 2026-09-30

Implemented an explicitly disabled-by-default HTTP proposal adapter and a DB-backed
bridge selecting independently revalidated safe evidence. Deterministic analysis is
never replaced. Bounded transport, cancellation, budgets, circuit failure handling,
unknown-cost semantics, proposal schema/citations and product-risk downgrade gates
are covered by transport fixtures. No paid or real-model request was made. Persistent
invocation/budget/UI scope remains open; see [provider contract](optional-provider.md).
Previous report-preview batch delivered to main as `9d8a5b93326fdeb8569554e73ea3b080ac0e7fd8`.
All ten ordinary CI jobs at preceding `c3d9898` passed in run `36652899198`.
This statement does not certify later source, and frozen benchmark failure is retained.
