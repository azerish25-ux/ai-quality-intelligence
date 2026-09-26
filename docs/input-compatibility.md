# Input compatibility matrix

| Input | Current support | Evidence retained | Important limits |
|---|---|---|---|
| Normalized JSON API | Working | run/test fields, safe message evidence, details | Contract version `1.0`; 20,000 observations/request; synchronous compatibility path |
| JUnit XML | Working M1 adapter | nested suites, classname/name, outcome, duration, failure/error/skipped text, output, file/line/timestamp | DTD/entities rejected; broader producer-dialect fixture set remains |
| Playwright JSON | Working M1 adapter | nested suites/specs, test ID, project/browser, attempts/retries, status, duration, errors, output, attachment metadata | JSON reporter only; not blob/HTML/trace parsing; pinned producer fixture remains |
| FailureLens ZIP bundle | Working M1 transport | chosen report, manifest/warnings, original bundle digest | Schema `1.0`; safe bounded extraction/index; embedded auxiliary attachments are not yet correlated |
| pytest JSON report | Not implemented | — | Pytest-produced JUnit can use the JUnit path |
| REST Assured/JUnit evidence | Partial | JUnit result only | Sanitized request/response correlation not implemented |
| k6 summary JSON | Not implemented | — | No percentile aggregation claims |
| Console text / JSONL | Partial | text embedded in supported reports | Standalone ordering/timestamp adapter pending |
| HAR / network JSONL | Not implemented | — | No outbound fetching is permitted |
| PNG/JPEG screenshots | Not implemented | source upload inside future bundles is not treated as safe evidence | Pixel limits, masking/review, and perceptual comparison pending |
| Playwright traces | Not implemented | — | No claim of trace analysis |
| GitHub commit metadata | Partial | self-reported normalized/raw query metadata | Authenticated lookup and trust distinction pending |
| Changed-file lists | Not implemented | — | Narrow test selection is unavailable |

## Transport and safety behavior

- Raw HTTP and CLI uploads are content-addressed under a project-scoped restricted path.
- Size and SHA-256 are revalidated by the worker before parsing.
- Ordinary files default to 50 MiB; bundles default to 250 MiB upload, 500 MiB expanded, 2,000 entries, 100:1 entry ratio, and no nested archives.
- Unsafe paths, control characters, drive prefixes, symlinks, encrypted entries, collisions, DTD/entities, empty reports, malformed structures, and unsupported formats fail with explicit codes.
- Duplicate submission of the same project/external ID/attempt/digest returns the existing ingestion rather than duplicating work.
- Distinct run attempts remain distinct even when bytes match.
