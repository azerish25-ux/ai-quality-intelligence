# M6.2 HTTP/PostgreSQL retry experiment

Tested FailureLens: `b31be357fc35aa4b9c225f28147ab32367d95a18`; LedgerGuard: `13bdd62c924a3230825b6d9304f449f887c8e7fe`.

Development pairs: 4; distinct mechanisms: 1; total role observations: 8.
Product recall: 1.0; product abstentions: 0; dangerous dismissals: 0/4.
Transport-only controls with cautious abstention: 4/4.

The unmodified companion is not alleged to be defective; the deliberate fault is key corruption in the retry proxy.
These measurements do not replace the older 80% component challenge or establish full M6 acceptance.

## Execution/integrity gates
- PASS: independent_http_sql_oracles
- PASS: role_isolation_and_bundle_idempotency
- PASS: five_identical_substantive_repetitions
- PASS: producer_bound_authorized_derivatives
- PASS: all_reports_advisory_hold
- PASS: zero_dangerous_critical_dismissals
- PASS: postgresql_pipeline

## Unchanged scoped quality targets
- PASS: product_recall_at_least_90_percent
- PASS: dangerous_dismissal_at_most_5_percent
- PASS: coverage_at_least_75_percent
- PASS: all_transport_only_controls_abstain
- NOT ESTABLISHED: five_category_macro_f1_at_least_0_80

## Limitations
Development-only, agent-authored scenarios; four amounts are one mechanism, not four independent families.
The faulty retry boundary is outside LedgerGuard. Different forwarded keys are correctly treated as different requests by the unmodified service.
A passing global balance reconciliation does not prove one economic effect per logical request.
The control passes the economic oracle but retains a real failed transport observation; cautious abstention is expected.

Saved API UUID links require the originating database. The retained safe derivatives and Markdown reports remain inspectable offline.
