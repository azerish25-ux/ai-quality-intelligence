# FailureLens delivery ledger

## M6.4.1 producer isolation correction

After the retained measurement checkpoint, review identified that Compose gives
ambient shell variables precedence over an explicit environment file. That could
select unrelated named resources despite a random project argument. The finality
runner now strips inherited Compose/application/Docker overrides per child
process and explicitly selects the local Linux Docker Unix socket. Parent
environment variables are not changed. Both direct commands and SQL snapshot
commands use the same isolation, and cleanup remains scoped to the random project.
The shared command/snapshot helper accepts an optional explicit environment;
existing callers retain their previous default behavior.

Twelve regressions cover hostile ambient resource names, remote contexts,
command/snapshot isolation and startup-failure cleanup. No new real Docker or
companion execution is claimed by this correction. The full pre-correction local
suite at `301478f56ce4013ae8e96bd58c07789a884efcd9` also passed 823 tests with four
PostgreSQL-only skips; the corrected revision needs its own complete verification.

## M6.4.1 clean local verification checkpoint

Verified source `158d288252d348ca55e3d2a33e109de882196567` (implementation
`6cc87174438c38ad71fad2c0bdf978c6d3255722`, then the saved benchmark-envelope
correction). The complete backend suite passed **823 tests**, with **four
PostgreSQL-only skips**, using the original baseline's downloaded producer fixtures
(artifact `11012442275`, SHA-256
`664632f099d66af2252d4ccf4cb8f696d20b0bb21fdf49aab78749f339bc01d7`).
This is local regression against retained producer bytes, not fresh producer CI.
The 146 new tests cover the finality boundary, independent oracle/replay and audit.

A clean-source SQLite/API/worker run correctly classified all eight explicitly
synthetic development cases: four product diagnoses, four abstentions, four/four
independently supported claims, all authorized/resolvable citations and five
identical substantive analyses per case. Every integrity gate passed. The exact
report and lossless safe snapshot are retained in
`evaluation/reports/transaction-finality-development-v1/`; bounded extraction and
independent rescoring reproduce its metrics. Corpus minimums still fail and broad
five-category macro F1 is undefined. No held-out or full-M6 success is claimed.

The new audit independently scored the retained 260-case benchmark and recorded
104 mismatches across all splits, with 134 legacy uninstrumented abstentions.
Its 44 test-partition product cases remain abstentions; no labels or historical
results were overwritten. The first audit attempt exposed the different
`published` versus `analysis` replay envelopes; the explicit reader correction and
actual-retained-archive regression passed. Component, prior full-stack, frozen
benchmark and M6.4 diagnostic snapshot verifiers also passed independently.

New Playwright sources passed TypeScript syntax transpilation and the new workflow
parsed as YAML. Full frontend build/browser execution did not run because offline
installation lacks locked packages. No coverage percentage is claimed: the initial
coverage-enabled whole-suite command timed out before completion; the completed
whole-suite command above did not enable coverage.

`git push origin main` was attempted and returned exit 128:
`Could not resolve host: github.com`. Connected reads still work, but no write
operation is exposed in this session. These commits are **local-only**, not pushed.
Actual new HTTP/PostgreSQL companion execution, PostgreSQL replay, browser journeys,
remote CI, renewed held-out evaluation and full M6 remain unverified/incomplete.
Later documentation/retention commits require separate final-revision verification.

## M6.4.1 transaction finality — local source checkpoint

Starting `main`: `304d0c8875e8a751f9b5f7b807356da2d2c90ea4`.
The additive transaction-finality relation, independent scorer/oracle, isolated
companion producer, diagnostic-gap audit and exact-source workflow are implemented.
Existing corpus bytes, failed targets and seven earlier contract kinds are preserved.
See [transaction finality](transaction-finality.md) for the mutation and scope.

Before committing this source, the 171 previous diagnostic regressions passed.
The 97 new finality boundary regressions and 12 gap-audit/workflow tests passed.
The initial eight-case synthetic SQLite/API/worker replay classified all cases
correctly and independently supported all four claims, but its clean-committed-source
integrity gate failed because the implementation was still uncommitted. The gate
has not been weakened. A clean-source checkpoint requires a subsequent actual run.

Actual new companion HTTP/PostgreSQL, PostgreSQL replay and desktop/narrow browser
execution are NOT RUN in this environment. Docker/PostgreSQL are absent; offline
frontend installation failed because required locked packages were not cached.
Terminal GitHub resolution and the absence of a connector write action currently
block publication. No remote checkpoint or new remote CI is claimed here. This is
not renewed held-out acceptance or completion of M6.

## M6.4 executed development checkpoint

The measured source `dc0aaf1202bffc7557f1a04b0aa5afdfdc8ce5fb` passed fresh component execution, PostgreSQL replay, independent scoring, build and all sixteen diagnostic browser journeys in run `36519135228`. All 32 development cases were classified correctly; this is not held-out quality recovery. The exact report, retained failures, snapshot verification and remaining work are in [M64-DELIVERY.md](M64-DELIVERY.md). Historical checkpoints below retain their original scope. Subsequent source revisions require their own CI.

## M6.4 diagnostic development — implementation checkpoint

Starting repository: `azerish25-ux/ai-quality-intelligence`, existing `main`,
`580ab0734602aff9a182f8bb56ea68201988f836`. The credential-free exact-source
export change was published at `17cd55af5e231d58796bc44e1b4911438b12a088`.
Baseline CI run `36515163885` passed all ten jobs: producers, backend/PostgreSQL,
LedgerGuard component replay, legacy evaluation, frontend, Docker and four browser
lanes. That baseline does not certify subsequent code.

The existing analyzer, contract adapter, publication validator and independent
campaign scorer now support four additional bounded diagnostic relations. The
reviewer workspace distinguishes missing observations, conflicting observations,
publication rejection and unresolved evidence/capability. Competing product-risk
signals preserve abstention regardless of a leading non-product score.

Local full backend verification passed **670 tests**, with four PostgreSQL-only
skips and **83.63% branch-aware coverage** against the unchanged 75% gate.
The focused group contains 112 new diagnostic/evaluator regressions and 59
retained contract tests (171 total). This includes the ordinary API/worker and
independent SQLite replay of 20 explicitly synthetic development cases, with 16
supported published diagnoses and four correct missing-measurement abstentions.
It is not PostgreSQL, browser, kernel OOM or fresh LedgerGuard execution evidence.
Exact-source execution and delivery results will be recorded as a separate
checkpoint rather than inheriting success from the baseline.

The new companion producer captures actual fingerprints, calendar dates and
projection snapshots and checks each against a separately executed scalar probe
and the existing independent oracle. Three already-known mechanisms have four
paired variants each. Twenty other cases are explicitly synthetic. The existing
campaign scorer can score this development-only slice without relabeling it as
a held-out result or weakening the original minimums/targets. See
[diagnostic development](diagnostic-quality.md).

The old corpus, frozen policies and retained reports are not rewritten. No new
100-case/20-product-family held-out evaluation, full temporal backtest or full
M6 acceptance is claimed by this implementation checkpoint. No model API or
companion write is used.


## M6.3 reconciliation — preserve both published and saved evaluation lines

The current source preserves the published frozen campaign/structured-contract implementation and integrates the previously saved three-commit M6.3 line as a separate `domain-observations-v1` and `benchmark-v1` path. The two evaluation datasets, endpoints, reports, and workflow names remain distinct. This reconciliation does not convert either quality result into full M6 acceptance and does not rewrite historical measured reports.

### Retained `benchmark-v1` measured checkpoint

Historical implementation commit: `6afa859537114ed97f3f5ee95e2f3a6bfed92981`. Frozen corpus/replay commit: `f1269c3ce52d4bf64f8614aacd34d99903a99b5f`. Retained measurement commit: `48365903077571306a63078fb7a114490f1069c1`. Those original local SHAs identify the saved line before reconciliation; the integrated publication replays their logical changes on top of the already-published campaign source.

The retained benchmark measures 260 cases and 718 API/worker ingestions in SQLite, with five identical substantive analyses per case, 33/33 later-history exclusions, 260/260 resolved published references, 126/126 supported published claims under the declared controlled rubric, and zero sensitive-canary disclosures in 40 tagged inputs. Its 108-case test partition reports **0/44 product recall, macro F1 0.3048218029350105, 18/92 = 19.5652% non-abstained coverage and 0/44 dangerous dismissals**. All 44 product cases abstain; 74 total test classification errors remain retained. Recall, macro F1 and coverage **FAIL** the unchanged targets.

These are different cases from M6.1's 48/60 result, not a same-dataset regression from 80% to zero. The structured contracts work on their evidence-bearing development cases; they do not establish broad diagnosis on unknown product mechanisms. The compact replay snapshot and exact metrics remain under `evaluation/reports/benchmark-v1/`; independent offline verification reproduces the retained metrics.



## M6.3 — structured contracts and frozen campaign source checkpoint

Starting source: `0ca3003472917af004fe62870221b67527cf4e71`, existing `main`.
The three strict diagnostic contracts, exact execution binding and recomputed
publication predicates are implemented. The independent frozen-campaign runner,
scorer, prior/future-history fixture loader, retention verifier and API-backed
reviewer panel are implemented. The frozen corpus contains 264 cases / 87
agent-reviewed catalogue groups, with 160 synthetic test cases across sixty
test-only groups. The sixty retained actual component executions remain in
development, alongside twelve synthetic structured supplements for three old
families. Historical component and full-stack reports are not rewritten.

Local checks before the final scope-hardening adjustment: 465 backend tests
passed, four PostgreSQL-only tests skipped, 83.03% branch coverage (75% gate).
After explicitly requiring operation-aware fingerprint scope and hardening the
calendar lower boundary, all 59 contract regressions passed. Campaign integrity
regressions cover frozen metadata, split leakage, reviewed history, unsafe
archives, runtime file/network/process tripwires and independently altered
outputs. Frontend syntax checks passed; full type/build/browser verification is
reserved for exact-source CI, not claimed from syntax transpilation.

The corpus and acceptance policy are frozen in this source checkpoint **before
final test inference**. No full-test metrics are claimed at this checkpoint.
Development/calibration smoke execution validates the real SQLite/API/worker
path and shows quality failures; it is not a PostgreSQL or held-out result.
Fresh exact-source PostgreSQL/browser evaluation is a required delivery check.

Full M6 and the complete master project remain PARTIAL. The new public synthetic
challenge is not independently blinded or expert-adjudicated. Wider adversarial
coverage, temporal backtesting, stronger diagnostic coverage and later M7–M10
scope remain. See [campaign contract](campaign-evaluation.md).

## Historical M6.2 checkpoint (unchanged below)

## M6.2 — accepted full-stack retry-boundary source

**Scoped HTTP/PostgreSQL execution, evidence and reviewer view: PASS. Full M6 and the project: PARTIAL. The retained M6.1 80% product-recall result still FAILS its unchanged 90% target.**

Repository `azerish25-ux/ai-quality-intelligence`, existing `main`. This work started at `076b42a5f76d41c457ed9bcefb3830ad533b36b7`. Feature source `4c040b1503301b34aabedc821cad1cfec7e99da5` and redaction correction `b31be357fc35aa4b9c225f28147ab32367d95a18` were committed and pushed without force. The accepted execution source is `b31be357fc35aa4b9c225f28147ab32367d95a18`, tree `1059fad286337bded480b73bf82a87b32ecf34c2`.

[Full-stack run 36499736145](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36499736145), job `109187473637`, passed actual LedgerGuard HTTP/PostgreSQL controls and interventions, FailureLens PostgreSQL replay, independent scoring and desktop/narrow Chromium journeys. [CI run 36499736103](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36499736103) passed all ten existing jobs: producers, backend/PostgreSQL, component evaluation, legacy regressions, frontend, Docker and four browser lanes. Later evidence/scorer commits require their own exact-revision CI and do not inherit these results.

### Delivered behavior and measured scope

The companion stays clean and pinned to `13bdd62c924a3230825b6d9304f449f887c8e7fe`. A disposable API/PostgreSQL stack receives real HTTP requests. Both paired roles lose the first committed response. The healthy retry preserves the upstream idempotency key; a deliberately faulty loopback retry proxy changes it. Independent SQL/receipt checks verify one versus two committed effects, with global accounting reconciliation passing both. **The injected retry boundary is defective; this does not allege a defect in unmodified LedgerGuard.** No companion changes were published.

Each role's report, numeric measurements and events travel as one three-input bundle through the existing ingestion API and durable worker. Roles stay in different runs. Re-imports are idempotent, current-run observations bind to the correct test, authorized derivatives retain producer digests, and the publication validator recomputes exact numeric predicates and bounded claim wording. Missing or conflicting observations do not justify confident blame. Labels and the independent oracle stay outside inference; the file-open tripwire is not an OS sandbox.

| Executed development measurement | Actual result |
|---|---|
| Paired scenarios / mechanisms | Four amount variants / one mechanism |
| Total role observations | Eight: four faulty interventions and four transport-only controls |
| Correct product-defect classifications | 4/4 |
| Product abstentions / dangerous dismissals | 0/4 / 0/4 |
| Healthy controls with cautious abstention | 4/4 |
| Verified numeric derivatives / bounded claims | Eight / four |
| Repeated substantive results | Five identical analyses per role |
| Five-category macro F1 | Not established |
| Model requests / compute cost | Zero external requests / compute cost unmeasured |

Four dependent amounts are not independent population evidence. This narrow development slice does not replace the older component challenge, resolve its twelve abstentions or complete the diverse five-category corpus.

### Inspection, retention and corrections

The actual API-backed full-stack panel and its desktop/narrow screenshots were inspected. It shows source revision, scope, controls, interventions, failed/undefined targets and limitations. API UUID links require the originating database; saved safe derivatives and advisory HOLD reports remain independently inspectable.

Execution artifact `11005245282` is 63,478 bytes, SHA-256 `111386cf5a9d4c9aa1ea06af6ddfcd5a1b123c327d395f9c68a3cf207cef47cb`, expires `2026-10-28T23:49:23Z`. Browser artifact `11005285226` has SHA-256 `713e7b9ef2d79516851bec169f805ba2dca11ea5029b64a870fbba90cc92bbe5`, expires `2026-10-05T23:49:22Z`. The compact lossless execution snapshot and exact report are committed under `evaluation/corpus/ledgerguard-fullstack-v1/` and `evaluation/reports/ledgerguard-fullstack-v1/`. `retention.json` distinguishes original and repacked digests. Independent offline rescoring reproduced the original metrics exactly; `python evaluation/verify_fullstack_snapshot.py` does not claim fresh execution.

The original full-stack run `36498925385` at `4c040b1` failed independent scoring because generic phone redaction damaged a numeric fragment of a SHA-256 identifier. Token boundaries were corrected without removing phone/credential protection. The fresh `b31be357` run passed. Scorer regressions additionally reject unsupported causal wording, empty published claim records, and forged role metadata even with recomputed repetition hashes.

The initial local full suite reported 328 passes, four PostgreSQL-only skips and sixteen missing-producer-fixture failures. The exact baseline fixture artifact was restored and its GitHub SHA-256 checked. The final complete local run passed 372 tests with four PostgreSQL-only skips and 82.70% branch-aware coverage. The new retention/evaluation regression group passed 51 tests. These are local checks, separate from actual PostgreSQL and browser CI. No test, threshold or retry policy was weakened.

Temporary publication workflow `36498849911` could create the tested Git tree but its workflow token could not update workflow files. The authorized connected account published the exact tree instead; all temporary payload/workflow files are absent from the delivered source. There is no new branch, public deployment, release, paid-model use or companion write.

### Remaining scope

Continue with independent five-category scenario diversity, family-grouped frozen splits, temporal/unknown-family challenges and broader claim/adversarial evaluation. Operation-scoped idempotency, stale projection ordering and weekly recurrence remain component abstention mechanisms; this slice adds numeric duplicate-effect diagnosis, not all three fixes. Concurrency, rollback, asynchronous workers and the companion UI are outside this experiment. M2/M5 residuals, M7 provider contracts, M8 complete GitHub publication, M9 hardening and M10 final audit remain unfinished. See [full-stack reproduction](fullstack-evaluation.md) and [requirement matrix](requirements-matrix.md).

### Preserved history

The full preceding M6.1 and M6.2-implementation checkpoint is preserved in the [immutable prior ledger](https://github.com/azerish25-ux/ai-quality-intelligence/blob/b31be357fc35aa4b9c225f28147ab32367d95a18/docs/PROGRESS.md). Earlier milestones are also retained in [PROGRESS-through-M6.1.md](PROGRESS-through-M6.1.md). Their counts and pending states apply to their named revisions, not the current milestone.
