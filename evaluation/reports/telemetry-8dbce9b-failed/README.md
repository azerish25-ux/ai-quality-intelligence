# Failed local-collector workflow at 8dbce9b

Source `8dbce9b327d943d85a1fce7d77d190853b8f2951`, workflow
[36687238268](https://github.com/azerish25-ux/ai-quality-intelligence/actions/runs/36687238268),
job `109795790067`, artifact `11084066157`.

Original ZIP SHA-256:
`7cbc9373bd504ff1aad078bb40b6b110496d8455047dfd0db3f3ace68a3a07ea`.
The ZIP was checksum-verified; `result.json` retains its exact original bytes.

**Overall result: FAIL, exit 22.** The inner `result.json` records only the earlier
successful trace-pipeline phase, not the whole workflow. Actual PostgreSQL-backed
ingestion completed through the separate API and durable worker. Eleven collected
stage names were observed; fake sensitive/baggage canaries were absent and the
runtime Internet probe was blocked. The viewer HTML loaded, but `/api/services`
returned 404 because Jaeger 2.21 uses the stable `/api/v3/services` route.

The services assertion and later collector-outage checks did not pass in this run.
The endpoint repair requires fresh execution; no old failure is relabeled as success.
