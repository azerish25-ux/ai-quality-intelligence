#!/usr/bin/env bash
set -euo pipefail

INGEST_JSON="$(failurelens ingest "$FAILURELENS_REPORT" --project "$FAILURELENS_PROJECT" --external-id "$FAILURELENS_EXTERNAL_ID")"
RUN_ID="$(python -c 'import json,sys; print(json.load(sys.stdin)["run_id"])' <<<"$INGEST_JSON")"
failurelens analyze --run "$RUN_ID" >/tmp/failurelens-analysis.json
REPORT_PATH="${RUNNER_TEMP:-/tmp}/failurelens-report.md"
failurelens report --run "$RUN_ID" --format markdown >"$REPORT_PATH"
{
  echo "run-id=$RUN_ID"
  echo "report-path=$REPORT_PATH"
} >>"$GITHUB_OUTPUT"
cat "$REPORT_PATH" >>"$GITHUB_STEP_SUMMARY"
