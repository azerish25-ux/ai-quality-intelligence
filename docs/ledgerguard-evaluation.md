# M6.1 — executed LedgerGuard component challenge

This milestone executes actual, hash-pinned LedgerGuard production Java components and replays their reports through FailureLens's real API, durable worker, persisted evidence, authorization and publication validator. It is **not full M6 acceptance** or proof of full-stack banking behavior.

## Scope and provenance

`integrations/ledgerguard/source.json` pins the companion to `13bdd62c924a3230825b6d9304f449f887c8e7fe`, whose original P08D control workflow is run `36464316280`. Fourteen production core source files are SHA-256 checked before and after execution. Nothing is committed or pushed to the companion. No second bank, database implementation or reimplementation of these components is copied into FailureLens.

The runner compiles the production source with JDK 21 into a temporary directory. Each intervention shadows exactly one changed class; the original checkout stays unchanged. Fifteen mechanisms each have four input variants and paired healthy controls: 60 passing controls and 60 failing interventions. These are **component-level controlled executions**, not HTTP integration, transaction-commit, concurrency, rollback or independently reconciled database executions. All money and identity inputs are synthetic.

| Mechanism | Independent contract observation |
|---|---|
| Wallet credit | Posted balance increases by the exact credit |
| Reserved-fund availability | Available balance equals posted minus reserved |
| Reservation consumption | Consuming a hold decreases both posted and reserved balances |
| Reservation release | Releasing a hold decreases reserved funds |
| Money addition | Minor-unit addition preserves the exact sum |
| Decimal scale | CAD minor units use the declared currency exponent |
| Journal balance | Unbalanced journal construction is rejected |
| Journal currency | Mixed-currency entries are rejected |
| Idempotency actor scope | Different actors produce distinct intent fingerprints |
| Idempotency operation scope | Different operations produce distinct intent fingerprints |
| Cumulative refund | Prior and new refunded amounts accumulate correctly |
| Reversal eligibility | Reversal after refund is rejected |
| Weekly recurrence | The next occurrence advances one calendar week |
| Webhook authenticity | A forged signature is rejected |
| Projection ordering | A stale incoming version cannot overwrite a newer projection |

The Java probe prints measurements only. Python independently computes arithmetic/calendar expectations or the specified rejection contract. An expected producer exception alone is not enough: every paired healthy control must match the independent expected value and every intervention must differ. Unexpected compiler/runtime failures, source changes and surviving interventions fail the runner. The exported XML is a custom contract runner's JUnit-compatible report, not a claim that a JUnit framework runner was used.

## Trust and inference boundary

`inputs/manifest.json` accepts only strict opaque case IDs, repository/revision and bounded digest-backed relative XML references. Ground truth, mutation mechanisms, oracle values, labels and command provenance are in separate evaluation-only files. Extra label/fault fields, traversal, symlinks, duplicate cases and changed bytes are rejected.

`evaluation/replay.py` is a separate process and does not import the generator/catalog. A Python file-open audit tripwire rejects accidental label/provenance reads; this is **not an OS sandbox**. The ordinary application never imports benchmark labels. Replay requires an explicitly confirmed, empty disposable database and synthetic demo mode. It never clears a populated database.

Each report is uploaded through the real API, processed by the durable worker and re-uploaded to prove idempotency. Published analysis comes from the API, not a direct classifier shortcut. Five repeat requests must retain substantive results. The runner resolves authorized evidence, checks source/derivative digests and exact excerpts, saves inspectable safe derivatives and renders the same advisory Markdown report as the application. API UUID links need the originating database; exported safe files remain inspectable independently.

Only after inference finishes does `evaluation/executed_harness.py` open the labels and score predictions. It compares a deliberately trivial constant-product baseline, rules only, rules with eligible prior history and full published deterministic decisions. The two intermediate comparisons use the same validated persisted observations; the headline results score API-published output. This component slice has no qualifying reviewed flake history and does not establish the value of historical retrieval.

## Reproduction

The permanent `ledgerguard-evaluation` job in `.github/workflows/ci.yml` checks out the pinned companion read-only, runs JDK 21 production components, migrates real disposable PostgreSQL, executes the label-free replay and uploads exact-revision evidence for 30 days. All four browser lanes read that run's real metrics through the API.

After dependencies from `backend[dev]` and JDK 21 are available, use an empty disposable PostgreSQL database, an accessible pinned companion checkout and unused output directories:

```bash
export FAILURELENS_DATABASE_URL='postgresql+psycopg://failurelens:failurelens@127.0.0.1:5432/failurelens_evaluation'
export FAILURELENS_DEMO_MODE=true
export FAILURELENS_ARTIFACT_ROOT=/tmp/failurelens-m6-private
(cd backend && alembic upgrade head)
python integrations/ledgerguard/run.py --ledgerguard-source /path/to/pinned-ledgerguard --output /tmp/failurelens-m6/corpus
python evaluation/replay.py --inputs /tmp/failurelens-m6/corpus/inputs --output /tmp/failurelens-m6/replay --repeats 5 --confirm-disposable-database
python evaluation/executed_harness.py --corpus /tmp/failurelens-m6/corpus --replay /tmp/failurelens-m6/replay --output /tmp/failurelens-m6/report
```

Output directories refuse overwrite. The corpus includes safe primitive observations, source/harness digests, compiler/runtime command records, control/intervention oracles and exact source revision. Large class files and dependency caches are not exported or committed. The source worktree's dirty state is recorded rather than silently attributing uncommitted work to HEAD.

The scorer's default exit code enforces **execution, evidence integrity and no dangerous critical reassurance**. Quality targets are a separate explicit table. Add `--enforce-quality` with a new output directory to require every quality target: exit 2 means measured quality targets failed; exit 1 means integrity/safety failure. A green scoped execution job does not establish full M6 acceptance. CI preserves the same 90% recall, 75% coverage and 5% dangerous-dismissal targets; it does not tune them to current results.

## Measurement limits and remaining work

This public, agent-authored challenge is not a frozen or blinded five-category test set. Four variants per mechanism are dependent; 60 cases are not 60 independent causes. Case-level Wilson intervals are only an independence illustration. Equal-family bootstrap intervals also do not establish deployment risk. Labels are agent-reviewed, not independently human-adjudicated.

A correct abstention is not a dangerous dismissal, but it reduces product recall. The implementation's initial local SQLite replay recognizes 48/60 product defects, abstains on 12 and records 0/60 dangerous dismissals. **80% recall fails the unchanged 90% target.** Do not alter rules using these inspected examples and then describe them as fresh held-out evidence. These preliminary local measurements have a dirty source tree and are not substituted for exact-revision PostgreSQL CI.

Five-class macro F1 is null because this slice contains only product-defect ground truth. Zero canary leakage is not redaction recall: no new canary slice is included here. Semantic claim checks use the application's deterministic typed predicates, not independent universal causal adjudication. Deterministic mode makes zero model requests, but compute cost is not measured.

Full M6 still needs a diverse five-category corpus with at least 200 cases and 80 genuine independent mechanisms, valid family-grouped development/calibration/test splits, at least 100 held-out test cases (40 product cases across 20 product families), temporally valid history and unknown-family challenges, broader claim/redaction/adversarial metrics and frozen acceptance policy. Full-stack LedgerGuard DB/HTTP/committed-effects scenarios remain additional work. M2/M5 residual scope, M7–M10 and final project acceptance remain independent requirements.

## Legacy corpus correction

`evaluation/corpus_audit.py` reports 200 old synthetic cases, 100 declared family identifiers, **five conservative root-cause templates** and five mechanisms crossing development/calibration/test. It preserves old corpus bytes and historical metrics; those scores remain rule-regression evidence. The new component cases are not relabeled synthetic fixtures and the old cases are not inflated into new independent families.

```bash
python evaluation/generate_corpus.py
python evaluation/corpus_audit.py --output /tmp/failurelens-legacy-audit.json
```
