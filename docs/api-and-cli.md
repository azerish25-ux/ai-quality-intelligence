# API and CLI

## Main API operations

- `GET /health/live`
- `GET /health/ready`
- `GET /api/v1/overview`
- `POST /api/v1/projects`
- `GET /api/v1/projects`
- `POST /api/v1/projects/{project_id}/ingestions`
- `GET /api/v1/projects/{project_id}/runs`
- `GET /api/v1/runs/{run_id}`
- `GET /api/v1/runs/{run_id}/failures`
- `POST /api/v1/failures/{failure_id}/analyses`
- `GET /api/v1/analyses/{analysis_id}`
- `POST /api/v1/analyses/{analysis_id}/reviews`
- `GET /api/v1/evidence/{evidence_id}`
- `GET /api/v1/evaluations/latest`
- `POST /api/v1/demo/seed` in demo mode

FastAPI generates the authoritative OpenAPI schema at runtime.

## Normalized ingestion example

```json
{
  "schema_version": "1.0",
  "external_id": "workflow-123",
  "attempt": 1,
  "repository": "owner/repository",
  "commit_sha": "abcdef0",
  "branch": "main",
  "framework": "normalized",
  "expected_inputs": 1,
  "observations": [
    {
      "test_identity": "payments::duplicate-idempotency",
      "outcome": "failed",
      "message": "ledger balance invariant violated after duplicate committed transfer",
      "exception_type": "LedgerInvariantError",
      "details": {"data_integrity_violation": true}
    }
  ]
}
```

## CLI exit behavior

The initial CLI returns zero for successful commands and nonzero for invalid/failed operations through standard Python process behavior. The full requested differentiated exit-code contract is not yet implemented.
