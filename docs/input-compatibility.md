# Input compatibility matrix

| Input | Current support | Evidence retained | Important limits |
|---|---|---|---|
| Normalized JSON API | Working | run/test fields, safe message evidence, details | Contract version `1.0`; 20,000 observations/request |
| JUnit XML | Working initial adapter | suites, classname/name, outcome, duration, failure/error/skipped text, stdout/stderr, file/line | DTD/entities rejected; declared dialect fixtures are intentionally small |
| Playwright JSON | Working initial adapter | nested suites/specs, project, attempts, status, duration, error, stdout/stderr | JSON reporter only; not blob report, HTML report, or trace archive |
| pytest JSON report | Not implemented | — | Pytest-produced JUnit can use the JUnit path |
| REST Assured/JUnit evidence | Partial | JUnit result only | Sanitized request/response correlation not implemented |
| k6 summary JSON | Not implemented | — | No percentile aggregation claims |
| Console text / JSONL | Partial | text embedded in supported reports | Standalone file ordering/timestamp adapter pending |
| HAR / network JSONL | Not implemented | — | No outbound fetching is permitted |
| PNG/JPEG screenshots | Not implemented | — | Pixel redaction and perceptual comparison pending |
| Playwright traces | Not implemented | — | No claim of trace analysis |
| GitHub commit metadata | Partial | accepted only through normalized source metadata | Trusted authenticated lookup distinction pending |
| Changed-file lists | Not implemented | — | Narrow test selection is not available |

The API route accepts a versioned normalized format, while the CLI currently detects `.xml` as JUnit and `.json` as Playwright JSON. Unsupported formats fail explicitly rather than being counted as successful ingestion.
