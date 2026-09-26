#!/usr/bin/env bash
set -euo pipefail

INGEST_JSON="$(failurelens ingest "$FAILURELENS_REPORT" --project "$FAILURELENS_PROJECT" --external-id "$FAILURELENS_EXTERNAL_ID" --process)"
INGESTION_ID="$(python -c 'import json,sys; print(json.load(sys.stdin)["ingestion_id"])' <<<"$INGEST_JSON")"
RUN_ID="$(python -c 'import json,sys; value=json.load(sys.stdin).get("run_id"); assert value, "ingestion did not publish a run"; print(value)' <<<"$INGEST_JSON")"
REPORT_PATH="${RUNNER_TEMP:-/tmp}/failurelens-report.md"
failurelens report --run "$RUN_ID" --format markdown >"$REPORT_PATH"
{
  echo "ingestion-id=$INGESTION_ID"
  echo "run-id=$RUN_ID"
  echo "report-path=$REPORT_PATH"
} >>"$GITHUB_OUTPUT"
cat "$REPORT_PATH" >>"$GITHUB_STEP_SUMMARY"
