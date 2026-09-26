# API and CLI

## Durable artifact ingestion

`POST /api/v1/projects/{project_id}/ingestions` supports two contracts:

1. `Content-Type: application/json` with no `filename` query parameter preserves the versioned normalized observation API.
2. A raw request body plus `external_id` and `filename` query parameters stores and queues JUnit XML, Playwright JSON, or a FailureLens ZIP bundle.

Raw upload example:

```bash
curl --request POST \
  --header 'Content-Type: application/xml' \
  --data-binary @junit.xml \
  'http://localhost:8000/api/v1/projects/<project-id>/ingestions?external_id=gha-901&filename=junit.xml&attempt=1&expected_inputs=25'
```

A raw upload returns `202 Accepted` with an `IngestionRead` resource. Parsing and analysis happen in the database-backed worker, not in the HTTP request.

## Ingestion lifecycle operations

- `GET /api/v1/projects/{project_id}/ingestions`
- `GET /api/v1/ingestions/{ingestion_id}`
- `POST /api/v1/ingestions/{ingestion_id}/cancel`
- `POST /api/v1/ingestions/{ingestion_id}/retry`

States are `queued`, `running`, `succeeded`, `partial`, `failed`, `cancelled`, and `dead_lettered`. Permanent invalid-input errors are not retried. Transient worker failures use bounded exponential delay and eventually dead-letter. A completed ingestion includes its `run_id`.

## Other API operations

- `GET /health/live`
- `GET /health/ready`
- `GET /api/v1/overview`
- `POST /api/v1/projects`
- `GET /api/v1/projects`
- `GET /api/v1/projects/{project_id}/runs`
- `GET /api/v1/runs/{run_id}`
- `GET /api/v1/runs/{run_id}/failures`
- `POST /api/v1/failures/{failure_id}/analyses` for explicit re-analysis
- `GET /api/v1/analyses/{analysis_id}`
- `POST /api/v1/analyses/{analysis_id}/reviews`
- `GET /api/v1/evidence/{evidence_id}`
- `GET /api/v1/evaluations/latest`
- `POST /api/v1/demo/seed` in demo mode

FastAPI generates the authoritative OpenAPI schema at runtime.

## ZIP bundle contract

A bundle may contain exactly one `.xml` or `.json` report, or a root `manifest.json`:

```json
{
  "schema_version": "1.0",
  "report": "reports/playwright-report.json"
}
```

Current M1 bundles index only the selected report. Archive entry count, total expanded bytes, per-entry compression ratio, traversal paths, case-folded collisions, symlinks, encrypted entries, nested archives, and report size are validated before parsing.

## CLI

```bash
failurelens doctor
failurelens ingest report.xml --project checkout --external-id gha-901
failurelens ingestion-status --ingestion <ingestion-id>
failurelens ingest report.json --project checkout --external-id gha-902 --process
failurelens report --run <run-id> --format markdown
```

Without `--process`, `ingest` queues work for `failurelens-worker`. `--process` claims one job using the same worker implementation and exits nonzero when no run is published. The complete differentiated quality-gate/operational exit-code contract remains future work.
