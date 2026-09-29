# FailureLens delivery ledger

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
