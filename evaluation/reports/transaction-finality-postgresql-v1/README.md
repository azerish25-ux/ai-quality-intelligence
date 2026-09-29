# Retained PostgreSQL transaction-finality evidence

Measured FailureLens source: `b7327b437d8fc4cb009918d1d4d31b6bf36f508a`.
[Original executed workflow](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36567980376).

Four actual HTTP/PostgreSQL fault/control pairs exercise one injected early-commit
mechanism; four further ambiguous/missing-evidence cases are synthetic. The replay
correctly identifies four product defects and abstains on four insufficient cases.
Four published claims and twelve citations pass the independent checks. Broad
five-category macro F1 is undefined and the full corpus minimums fail. This is
**development evidence, not held-out acceptance or completed M6**.

`report.md` is copied without alteration. `execution.zip.xz` contains all original
member bodies: corpus, independent SQL/receipt oracles, predictions, safe evidence,
complete metrics JSON, per-case scores and diagnostic-gap audit. `retention.json`
records the verified original GitHub artifact checksum, lossless repack checksum,
per-file checksums and the single documented audit-path relocation. The earlier
`transaction-finality-development-v1` SQLite snapshot remains untouched.

From the repository root with backend dependencies installed:

```sh
python evaluation/verify_finality_snapshot.py
python evaluation/verify_finality_snapshot.py --extract-to /tmp/finality-retained
```

The second command requires a nonexistent destination. It verifies checksums,
rescoring and every retained SQL/receipt oracle before exporting inspectable data.
Neither command performs a new Java, Docker, PostgreSQL or browser execution.
