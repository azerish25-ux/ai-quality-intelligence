# Input compatibility matrix

## M2.1 support overlay

The historical foundation matrix below is superseded for screenshots/traces and
producer fixtures by [safe-binary-evidence.md](safe-binary-evidence.md). Screenshots
now require actual bounded decoding and have a reviewer-controlled immutable mask
workflow. Playwright trace schema 9 / producer 1.63.0 supplies bounded safe event
citations and a digest-verified local-inspection command. Approved derivatives have
authorized preview/download, expiry and revocation. Originals remain restricted and
are not offered for download. Real producer execution is checked by the CI fixture
job; exact passing execution must be read from the delivered revision's CI/ledger.


Support depth is stated explicitly. “Working adapter” means the format is parsed, bounded, assigned a stable input record, and exercised by automated fixtures. It does **not** imply universal producer compatibility or that every binary artifact is safe to display.

| Input | Current support | Evidence retained | Important limits |
|---|---|---|---|
| Normalized JSON API | Working | Run/test fields, attempts, safe messages, details, precise JSON Pointer locators | Contract `1.0`; one received input regardless of observation count; 20,000 observations/request |
| JUnit XML | Working adapter | `testsuite`/`testsuites`, nested suites, properties, classname/name, outcomes, duration, failure/error/skipped text, output, file/line/timestamp | DTD/entities rejected; producer-dialect fixture matrix remains incomplete |
| Playwright JSON reporter | Working adapter | Suites/specs/test IDs, locations, projects/browsers, attempts/retries, outcomes, duration, errors, stdout/stderr, attachment metadata | JSON reporter only; pinned real-producer fixture remains open; blob/HTML reports are not treated as JSON reports |
| FailureLens ZIP bundle | Working schema `2.0` transport | Explicit input IDs, required/optional status, paths, kinds, digests, media types, metadata, parser versions, warnings, missing/rejected/restricted states | Schema `1.0` remains readable; schema `2.0` is the generation target; arbitrary nested archives remain rejected |
| pytest JSON report | Working adapter | Node IDs, parameterization, setup/call/teardown phases, collection errors, skips, xfail/xpass semantics, captured output, duration and crash details | Compatible with the documented `pytest-json-report` shape; pinned producer execution fixture remains open |
| REST Assured/JUnit evidence | Working foundation | JUnit results plus sanitized request/response evidence summaries, methods, routes, statuses and assertions | Correlation is explicit through manifest metadata/input identity; executed Java producer fixture and deeper response-field policy remain open |
| k6 `handleSummary` JSON | Working adapter | Metric types, units, counters/rates/trend values, configured quantiles, thresholds, tags, workload/context metadata; breached thresholds become observations | Summary JSON only; streaming sample JSON is not accepted; missing quantiles are never invented |
| Console text / JSONL | Working adapters | Stream/source/timestamp metadata where supplied, stable line/index locators, bounded safe previews, error-level counts | UTF-8 only; retained windows are bounded and truncation is visible; terminal controls are removed for display |
| HAR / network JSONL | Working adapters | Method, sanitized URL, status/error, timing, browser/attempt metadata and exact entry/line locators | No URL is fetched; headers/bodies are not yet exposed as broad evidence; test correlation requires supplied evidence |
| PNG/JPEG screenshots | Restricted metadata adapter | Digest, dimensions, pixel count, media type, review state and optional expected/actual/diff relationship metadata | Original remains restricted; no claim that text redaction sanitizes pixels; review/mask workflow and perceptual comparison remain open |
| Playwright traces | Restricted bounded-index adapter | Trace archive digest, entry list, supported trace stream name, bounded action/event/error/network counts and version hints | Original remains restricted; no trace HTML is executed; rich resource extraction and controlled local viewer workflow remain open |
| GitHub commit/workflow metadata | Working metadata adapter | Repository, commit/base SHA, branch, PR, workflow/run/attempt, trigger, minimized author display, explicit trust provenance | Uploaded metadata is self-reported unless an authenticated integration marks it otherwise; it never grants authorization |
| Changed-file lists | Working impact input | Base/head, added/modified/deleted/renamed paths, old/new paths, diff/coverage references, pagination/completeness, declared trust and transport-bound effective trust | Incomplete, truncated, untrusted, unmapped or critical changes force full-suite execution; artifact bytes cannot promote their own trust |

## Manifest `2.0`

A multi-artifact run is described by a root `manifest.json`:

```json
{
  "schema_version": "2.0",
  "inputs": [
    {
      "id": "playwright-shard-1",
      "kind": "playwright-json",
      "path": "reports/playwright-1.json",
      "required": true,
      "sha256": "<optional expected digest>",
      "media_type": "application/json",
      "metadata": {"shard": 1, "expected_shards": 2}
    },
    {
      "id": "browser-console",
      "kind": "console-jsonl",
      "path": "logs/console.jsonl",
      "required": false
    },
    {
      "id": "failure-shot",
      "kind": "screenshot",
      "path": "screenshots/failure.png",
      "required": true,
      "metadata": {"relationship": "actual", "test_identity": "checkout"}
    }
  ]
}
```

Completeness is evaluated from **declared required inputs**, not the number of tests inside a report. A present but rejected/unsupported/restricted required input counts as received but prevents a reassuring `complete` result. A missing required input is persisted as `missing`. Optional failures remain visible without increasing the required-input denominator.

## Transport and safety behavior

- Raw HTTP and CLI uploads are content-addressed under a project-scoped restricted path.
- Size and SHA-256 are revalidated by the worker before parsing.
- Ordinary files default to 50 MiB; bundles default to 250 MiB uploaded, 500 MiB expanded, 2,000 entries, and a 100:1 entry ratio.
- Decoded images default to a 25-megapixel limit.
- Unsafe paths, control characters, drive prefixes, symlinks, encrypted entries, case-folded collisions, undeclared nested archives, DTD/entities, malformed encodings, MIME/format mismatches, and unsupported schemas fail with explicit codes.
- An explicitly declared Playwright trace may itself be a bounded ZIP; other nested archives remain forbidden.
- Valid sibling inputs survive when another manifest input is missing, rejected, or unsupported. The overall run becomes partial and stores per-input diagnostics.
- Duplicate submission of the same project/external ID/attempt/source digest returns the existing ingestion rather than duplicating work. Distinct attempts remain distinct even when bytes match.
- Changed-file JSON may contain a producer-declared trust label, but it is stored only as `declared_trust`. The effective `trust` used by impact policy is bound at the API/CLI/Action transport boundary through `comparison_trust`; ordinary uploads default to `self_reported`. A payload cannot make itself `trusted_workflow`.
- Narrow impact selection additionally requires matching non-empty base/head SHAs, a complete non-truncated changed-file input and a project-scoped immutable mapping snapshot. Any missing invariant is persisted as a safety reason and returns `FULL_SUITE_REQUIRED`.
