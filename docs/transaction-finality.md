# M6.4.1 — transaction-finality diagnostic development

## Delivered scope versus execution evidence

This change adds `transaction_finality` to the existing
`contract-observations-v1` adapter/analyzer/publication path. It also adds an
isolated HTTP/PostgreSQL producer, an independent SQL/receipt oracle, a bounded
family-level diagnostic-gap audit, and an exact-source verification workflow.
It does not create another inference pipeline or merge either historical corpus.

The initial implementation environment has no Docker/Compose, PostgreSQL server
or psycopg, and its terminal cannot resolve GitHub. The exposed GitHub connector
provides reads/artifact downloads but no publication operation. Consequently,
real companion execution, PostgreSQL replay, browser verification and remote CI
for this source must be reported as NOT RUN until there is actual run evidence.
SQLite/API/worker regression is not a substitute for those checks. Local source
and later execution checkpoints are recorded separately in `PROGRESS.md`.

## Why this is a separate relation

The existing atomic-transfer relation checks observed balances against a
*resolved financial outcome*. An HTTP error alone does not establish rollback.
A request may have committed even though delivery failed. Relabeling every 503
as `rolled_back` would manufacture both a receipt and a product diagnosis.

The new relation instead checks a narrower, explicit contract: a terminal
business rejection promises no financial effects, yet a committed primary-database
snapshot records a balance change or new transfer/journal effects. It requires
matching request and response identity, distinct accounts, matching source-versioned
response-contract digests, isolated observations, and all numeric measurements.
Nulls are missing evidence, not zeros. Numeric booleans/strings/floats, negative
counts, unsupported policies, duplicate JSON keys and extra answer fields are
rejected. Transport-only or unresolved responses, mismatched rejection status/code,
unknown snapshot basis and concurrent writers cannot authorize this diagnosis.

The published claim describes **reported observations supporting investigation**.
It neither identifies a faulty component nor alleges that PostgreSQL violated
atomicity. Conforming observations do not establish that the original test failure
is harmless. Contradictory findings and competing categories retain abstention.
Existing execution binding, project authorization, immutable derivatives and
publication recomputation remain in force. The independent campaign scorer has
separate arithmetic, validation and bounded wording rather than asking the
runtime inspector to certify its own answer.

## Controlled producer

`integrations/ledgerguard/rollback.py` requires clean LedgerGuard source pinned to
`13bdd62c924a3230825b6d9304f449f887c8e7fe`. It verifies the inspected
`FinancialCommands.java` Git blob `cc5a65192cc940cc48dfaca341b69c943440b507`, then
copies only tracked files to private disposable directories. The original checkout
is compared again on exit. No companion change is committed or published.

Both roles insert a conditional `TRANSFER` rejection immediately after the
stored procedure returns and before the normal JDBC commit. The control throws
SQL state `P4220` before commit; the existing handler attempts rollback. The
intervention deliberately commits first and then throws the same rejection.
TransferService maps this state to HTTP 422 / `TRANSFER_REJECTED`. This is an
**injected early-commit JDBC boundary fault**, not a claim about unmodified
LedgerGuard or PostgreSQL. The response semantics are a documented producer
contract tied to the source revision, not an authenticated universal truth about
arbitrary producers.

Each role runs in a separate randomly named Docker Compose project with private
random credentials. The runner requires the local Linux Docker socket at
`/var/run/docker.sock`, explicitly selects it, and removes inherited Compose,
LedgerGuard, PostgreSQL, RabbitMQ and Docker override variables from child
environments. Ambient settings cannot select an unrelated named volume, network,
Compose override file or remote Docker context. The parent environment is unchanged. Only PostgreSQL/API and the disposable seed are started;
background payment/outbox workers are not started. HTTP is loopback-only; the
client ignores external proxies. Requests run sequentially. For each request,
a repeatable-read SQL snapshot captures both account balances, related transfers
and double-entry journal rows before and after its actual HTTP receipt.

`rollback_oracle.py` independently requires the observed rejection, expected
zero/one new transfer, exact debit/credit entries and balance deltas, preserved
historical rows, unique identities, bounded integers and the original monetary
intent. Global reconciliation must still pass. Merely raising an exception is not
successful injection. An unavailable Docker runtime raises an explicit error;
there is no implicit synthetic fallback.

The producer freezes four fault/control pairs at four small synthetic-money
amounts, representing **one mechanism**, plus four explicitly synthetic
missing/ambiguous-evidence cases. Passing controls and repeated analyses do not
inflate the failure-case count. The independent oracle, mutation descriptions,
receipts and source inventory remain outside the public input directory. Private
passwords, cookies and complete HTTP headers are not retained in reports.

## Reproduction

Use the clean committed FailureLens tree, a clean pinned companion checkout,
Docker/Compose, and an empty disposable FailureLens PostgreSQL database:

```sh
python integrations/ledgerguard/rollback.py \
  --ledgerguard-source /path/to/pinned-ledgerguard \
  --output /tmp/finality/corpus --confirm-disposable-stack
# Configure FAILURELENS_DATABASE_URL, FAILURELENS_ARTIFACT_ROOT,
# FAILURELENS_DEMO_MODE=true, then (cd backend && alembic upgrade head).
python evaluation/replay_campaign.py --inputs /tmp/finality/corpus/inputs \
  --output /tmp/finality/replay --confirm-disposable-database
python evaluation/campaign_harness.py --corpus /tmp/finality/corpus \
  --replay /tmp/finality/replay --output /tmp/finality/report --development-only
python evaluation/diagnostic_gap_audit.py --corpus /tmp/finality/corpus \
  --replay /tmp/finality/replay --kind development \
  --output /tmp/finality/diagnostic-gaps.json
```

The workflow `.github/workflows/rollback-evaluation.yml` additionally requires
clean exact-source metadata, independently supported published claims, four
verified real interventions, four passing rollback controls, four correct synthetic
abstentions and PostgreSQL replay. It builds/tests the frontend and executes the
actual reviewer workspace at desktop/narrow widths with zero browser retries.
Snapshots/reports are bounded CI artifacts, not an invented deployed dashboard.

`build_synthetic()` is only an explicitly named local test helper. Its eight
cases are all synthetic and its executed count is zero. Test reports retain this
distinction, the real database dialect, and whether the source tree was dirty.

## Gap audit and remaining acceptance

The read-only gap audit invokes the appropriate existing independent scorer,
then groups retained cases by scenario family and split. It reports publication
rejection, missing/invalid observations, contradictions, unresolved capability or
unavailable legacy instrumentation. It cannot infer whether original evidence was
absent or a parser lost it; those cases require original/normalized artifact
review. It exports no raw diagnostic text or new causal verdicts.

The 260-case benchmark and 264-case campaign, their labels, frozen policies and
historical failures remain unchanged. This one-mechanism development slice does
not recover five-category benchmark quality, establish 20 new product mechanisms,
or complete M6. A genuinely new held-out corpus, complete temporal backtest,
full adversarial program, additional actual producer breadth, M2/M5 residuals and
M7–M10 still remain. Historical test cases inspected for gap analysis must be
marked as reused regression evidence, not newly independent measurements.
