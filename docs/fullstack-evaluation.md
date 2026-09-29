# M6.2 — HTTP/PostgreSQL retry-boundary evaluation

This development milestone extends the existing component challenge. It does not
replace that challenge's retained **48/60 (80%) product recall**, failed 90% target,
or the requirement for a diverse, family-separated five-category evaluation.

## Declared mechanism and independent observations

`integrations/ledgerguard/fullstack.py` starts the hash-pinned, unmodified
LedgerGuard API and PostgreSQL in a unique disposable Docker Compose project.
It creates private temporary credentials, uses only the companion's fictional
money fixtures, and removes only its own containers/network/volumes. Companion
tracked-source bytes are checked before and after; no changes are published there.
The UI, RabbitMQ, payment workers, concurrency and rollback are outside this slice.

Each of four amounts has a healthy control and a faulty intervention. Both send
one logical transfer twice. A loopback proxy consumes the first actual committed
HTTP response and closes the client socket before sending response headers. The
client really observes a disconnected response stream and preserves its key/body.
The healthy proxy forwards the same key on retry. The faulty proxy deliberately
replaces the forwarded key on retry. **The fault is in this retry boundary, not a
claim that the unmodified LedgerGuard service mishandles identical keys.**

Independent, read-only PostgreSQL snapshots retain transfer IDs, journal entries
and account balances before and after. `fullstack_oracle.py`, outside inference,
compares actual upstream receipts, key/body digests, exact debit/credit entries,
committed transfer counts and balance deltas. The control must have one effect;
the intervention must have two. Both must pass the companion's global accounting
reconciliation: balanced books alone do not establish one effect per logical
request. A surviving intervention, failed control, compiler/service failure or
changed source is not counted as a valid case.

The economic control passes even though its transport observation failed. The
JUnit-compatible XML records that real transport failure, not a claim that a JUnit
framework produced the report. Its ground-truth disposition is cautious
`insufficient_evidence`: one reconciled effect is not universal infrastructure or
release reassurance. The intervention is a product defect in the tested system's
retry boundary. Four amounts are **one** mechanism, not four independent families.

## Multi-artifact inference and publication

Each role has one digest-backed bundle: a transport test report, primitive
transaction measurements and bounded event observations. Replay v2 keeps these
three required inputs in one run, and keeps the two roles in separate runs. Replay
v1 remains compatible with retained component archives. Extra manifest metadata,
undeclared files, traversal, symlinks, duplicate paths, changed bytes and oversized
artifacts are rejected. `transaction-observations-json` is an explicit bounded
adapter, not a format guessed from arbitrary logs.

Measurements contain observations, not a category, fault flag, root-cause label
or oracle verdict. They bind to exactly one test identity/attempt/browser and an
explicit report-input relationship. They are not attached indiscriminately to all
failures in a run. Immutable approved derivatives preserve their producer digest.

The deterministic analyzer recomputes numeric relationships. Duplicate effects
require matching logical request digests, valid scoped receipts, unchanged prior
effects, exact journal entries and consistent balance deltas. Missing, ambiguous,
malformed or contradictory measurements do not justify a product classification.
The publication validator independently recomputes the typed predicate and checks
the bounded claim wording and authorized evidence. It does not accept a producer's
`product_defect=true` assertion or blame a particular component from counts alone.
This is evidence-supported triage, not a trust guarantee about arbitrary producers.

`evaluation/replay.py` uses the actual API, durable worker and persistence. It
checks duplicate-ingestion idempotency, run completeness, authorized evidence and
five substantive analyses. Labels, wire-level intervention details and the
independent oracle stay in evaluation-only files. The Python open-audit tripwire
is defense against accidental reads, **not an operating-system sandbox**.

The separate scorer reopens the actual producer bytes, independently checks the
HTTP/SQL oracle, verifies exported derivatives against the corresponding role,
rechecks repetition digests and requires advisory `HOLD_FOR_REVIEW` reports. It
preserves failed measured targets and never silently alters labels or thresholds.

## Execution and inspection

Prerequisites: Docker Engine/Compose, the pinned companion checkout, Python and
`backend[dev]`, and an empty disposable Loose Thread PostgreSQL database. Do not point
either database at existing user data. The companion checkout must be clean at
`13bdd62c924a3230825b6d9304f449f887c8e7fe`; API port 18080 must be unused.

```bash
export FAILURELENS_DATABASE_URL='postgresql+psycopg://failurelens:failurelens@127.0.0.1:5432/failurelens_fullstack'
export FAILURELENS_DEMO_MODE=true
export FAILURELENS_ARTIFACT_ROOT=/tmp/failurelens-m62-private-artifacts
export FAILURELENS_FULLSTACK_EVALUATION_METRICS_PATH=/tmp/failurelens-m62/report/metrics.json
(cd backend && alembic upgrade head)
python integrations/ledgerguard/fullstack.py --ledgerguard-source /path/to/pinned-ledgerguard --output /tmp/failurelens-m62/corpus --confirm-disposable-stack
python evaluation/replay.py --inputs /tmp/failurelens-m62/corpus/inputs --output /tmp/failurelens-m62/replay --repeats 5 --confirm-disposable-database
python evaluation/fullstack_harness.py --corpus /tmp/failurelens-m62/corpus --replay /tmp/failurelens-m62/replay --output /tmp/failurelens-m62/report
```

The permanent `.github/workflows/fullstack-evaluation.yml` executes this path on
real PostgreSQL, then runs actual API-backed desktop and narrow Chromium journeys.
Its output directories refuse overwrite. The scorer exits 1 for integrity failure
and 2 for a failed scoped quality target. Full five-category macro F1 remains
undefined on this two-disposition slice. No model request is made; compute cost is
not measured. Case-level proportion intervals are not independent-family or
population confidence: the four amounts share one mechanism.

The existing dashboard retains its original component evaluation panel. A second
panel loads the authenticated `/api/v1/evaluations/fullstack` endpoint when a report
is mounted. It labels the development/HTTP/PostgreSQL scope, shows actual control
and intervention effects/classifications, tested source, failed targets and limits.
Its table supports keyboard expansion, captions, scoped headers and narrow-screen
scrolling. Persisted UUID links require the originating database; safe derivative
files and Markdown exports remain independently inspectable.

## Verification and acceptance boundaries

New regression coverage includes numeric relations, confusing negatives, absent
and conflicting observations, strict schema/size checks, cross-test binding,
forged citations/counts, actual socket disconnect/retry behavior, independent
oracle tampering, bundle isolation, API/worker replay, scorer forgeries and report
access. Synthetic unit fixtures are explicitly labeled as such and are not counted
as LedgerGuard executions.

The executed source `b31be357fc35aa4b9c225f28147ab32367d95a18` passed
[full-stack run 36499736145](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36499736145),
job `109187473637`, including real HTTP/PostgreSQL execution, label-free replay,
independent scoring and both browser layouts. All ten existing regression jobs in
[run 36499736103](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36499736103)
also passed. Downloaded desktop and narrow screenshots were inspected. These
results describe that exact source, not an untested later revision.

The measured development slice has four correctly identified duplicate-effect
interventions, four transport-only controls with cautious abstention, zero of four
dangerous dismissals, eight verified numeric derivatives and four bounded claims.
Five substantive analyses agree for each role. This is one mechanism with four
dependent amount variants; it is not an eight-family or five-category benchmark.

The first full-stack run `36498925385` at `4c040b1` failed scoring after successful
HTTP execution and replay. A phone-shaped digit sequence inside a random SHA-256
identifier was over-redacted. The fix preserves identifier token boundaries while
still redacting phone tokens, named sensitive fields and credentials. Regression
tests include the problematic digest shape through the complete replay. The failed
run is not counted as acceptance.

## Durable evidence and offline verification

The original 63,478-byte execution artifact `11005245282` is retained losslessly
under `evaluation/corpus/ledgerguard-fullstack-v1/execution.zip.xz` (17,316 bytes).
Every original artifact member is preserved; ZIP storage and outer compression
were changed, so original and repacked digests are recorded separately. Exact
metrics, predictions and the report are in `evaluation/reports/ledgerguard-fullstack-v1/`.
Its `retention.json` records the tested source, originating run/job, original
GitHub artifact SHA-256 and expiry, snapshot digests, and browser artifact metadata.
No credentials, databases, compiled classes or companion source are included.

```bash
python evaluation/verify_fullstack_snapshot.py
```

This command checks compressed and expanded bounds, member safety and all digests,
then independently rescores the saved API output and requires exact metric/report
agreement. It is **offline verification, not a fresh HTTP/PostgreSQL/browser run**.
Snapshot regressions reject changed bytes, symlinks, expansion/trailing data,
unauthorized nested ZIP paths, forged role records and unsupported claims even
when a forger recomputes repetition hashes. The default local dashboard reads the
retained report and displays its actual `b31be357` source. CI uses a fresh report
for its own tested revision. Earlier component reports remain byte-for-byte unchanged.

Remaining work includes truly independent five-category families, frozen
family-grouped splits, broader temporal/unknown-family/adversarial evaluation,
structured evidence for the outstanding component abstention mechanisms, remaining
M2/M5 requirements, optional-provider contracts, GitHub publication and operational
hardening. M6.2 does not close full M6 or final project acceptance.
