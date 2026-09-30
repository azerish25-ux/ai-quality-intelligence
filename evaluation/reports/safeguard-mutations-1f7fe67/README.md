# Actual CI safeguard mutation results

Source `1f7fe672ee940a4bf117517e399e134b5d05ed88`, workflow
[36690815411](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36690815411),
job `109807335679`, artifact `11086270170`.

The original ZIP was SHA-256 verified as
`0d561dfdf859c296c257a56fc23e9397316791c0a616575a254610819321182a`.
`report.json` retains the original bytes.

All seven baseline tests passed; **seven exercised mutants were killed, zero
survived and zero errored**. Source was clean and remained unchanged. The report
names exact tests, runtime source and code/test digests, and records assertion
origin rather than counting collection/setup errors as kills.

This is a small authored safeguard-sensitivity check, not independent security
certification, OS sandbox attestation or a new classification dataset. No real
provider or live GitHub mutation was performed. Original quality failures remain.
