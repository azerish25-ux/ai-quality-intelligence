# Read-only GitHub Action

This composite Action ingests declared reports, performs deterministic analysis,
and retains a digest-bound Markdown report, JSON report, and inert evidence JSON.
It accepts no commands, provider configuration, publishing tokens, or comment mode.
Use a reviewed, immutable Action revision and give the consuming job only
`contents: read`. The repository consumer continues to support ordinary fork PRs
without secrets or write permissions; it never uses `pull_request_target`.

## Modes and optional configuration

With no configuration, `analysis-mode` is `deterministic` and
`publication-mode` is `summary`. Explicit unsupported modes fail before ingestion.
`artifact-only` retains the same report/status/evidence outputs without appending
the report to `GITHUB_STEP_SUMMARY`. Neither mode activates a provider, publishes
a comment, changes a test result, or relaxes completeness. The subprocess
environment disables provider and telemetry export and excludes the known
provider/GitHub token variables.

The optional `config-path` and `config-sha256` inputs must be supplied together.
The reviewed operator/workflow must select both the path and the expected
lowercase SHA-256. The Action never searches a PR for a configuration file, reads
a config path from an artifact, or calculates a new expected digest to bless an
unreviewed file. A PR's matching file and digest do **not** establish provenance.
Operator selection and trusted workflow review are separate from the byte
integrity check. Untrusted configuration remains data even when its digest matches.

Only regular, nonexecutable UTF-8 JSON files up to 16,384 bytes are accepted.
Symlinks in any path component, traversal, duplicate keys, malformed JSON,
nonfinite numbers, unknown fields, credential fields, executable settings and
arbitrary endpoint URLs are rejected. There is no YAML, template expansion,
environment interpolation, import, subprocess setting, or plugin loading.

The complete supported shape is:

```json
{
  "schema_version": "github-action-config-v1",
  "analysis_mode": "deterministic",
  "publication_mode": "artifact-only",
  "limits": {
    "report_bytes": 100000,
    "markdown_bytes": 50000,
    "evidence_bytes": 500000
  }
}
```

Only `schema_version` is required. Omitted fields use the defaults above.
Limits may be reduced: report/evidence floors are 4,096 bytes and the Markdown
floor is 1,024 bytes. Limits never increase the hard safety caps or silently trim
a digest-bound output. An output exceeding a configured limit fails closed.
An explicit mode input conflicting with the same config field fails rather than
silently choosing one. Expected-input/shard requirements, database location,
project/repository identity, and evidence approval cannot be changed by config.

Supply configuration from a reviewed operator-controlled location. Compute its
digest during review and record that exact digest in reviewed workflow code;
do not derive both inputs from the PR checkout or PR artifact during execution.
The example repository consumer deliberately uses explicit deterministic/summary
modes and no optional file.

## Export and output boundary

The Action obtains one JSON report, verifies the run and canonical report digest,
then invokes `export-evidence --run RUN_ID --report-digest EXACT_REPORT_DIGEST
--output GENERATED_PATH`. The CLI freshly revalidates the report and referenced
evidence, exclusively creates a private canonical `evidence.json` no larger than
500,000 bytes, and returns a small receipt. The Action reads only that generated
regular file without following symlinks, checks byte count, digest, nested count
descriptor, report/run/project scope and permitted related-run scope, and only
then exposes the `evidence-path` output. Digests identify bytes; they do not
authenticate producers or authorize publication.

The evidence export contains only a bounded, approved reference subset, with
explicit missing/rejected/omitted counters. It is inert JSON: excerpts may contain
untrusted instructions or mention-like text and must never be executed or rendered
as trusted Markdown/HTML. Original artifacts, private storage paths, binary
bodies and unapproved evidence are excluded. Unknown sensitive patterns can
remain, so artifact retention/access must be appropriate for the project.
`distribution_status: not_published` reports the backend's external publication
state; a workflow artifact upload is not a GitHub publication receipt.

Each invocation creates a fresh private directory. Outputs are fixed enums,
validated IDs/hashes and generated file paths. Failure leaves report/evidence
path outputs empty and emits only fixed safe error codes. CLI error bodies are
never copied to logs or summaries. The consumer uploads exactly `report-path`,
`report-json-path`, `evidence-path` and `status-path`, with no directory glob.
The original shard test status and the independent complete-transport gate remain
authoritative. Report generation never converts a failing test job into success.

These constraints are not an OS egress sandbox. Dependency installs and authorized
GitHub artifact transfers still use runner networking. The Action has no live or
paid-provider invocation and requires no comment capability.

## Verification

```sh
PYTHONPATH=backend/src:. python -m pytest backend/tests/test_github_action.py backend/tests/test_github_action_config.py
```

The tests run actual CLI ingestion/report/export with SQLite and zero/one/two
arriving shards, exercise artifact-only fork behavior, then corrupt real export
fixtures to check missing/malformed/tampered, scope, symlink, count, receipt and
size failures. They also test strict config bytes/schema/provenance boundaries,
command/mention injection, redaction canaries, and disabled credential forwarding.
They do not claim hosted Actions, PostgreSQL or live GitHub publication acceptance.
