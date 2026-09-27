#!/usr/bin/env bash
set -euo pipefail

case "${FAILURELENS_COMPARISON_TRUST:-self_reported}" in
  self_reported|authenticated_lookup|trusted_workflow) ;;
  *) echo "invalid comparison-trust input" >&2; exit 2 ;;
esac
case "${FAILURELENS_RUN_SCOPE:-unknown}" in
  full_suite|impact_selected|unknown) ;;
  *) echo "invalid run-scope input" >&2; exit 2 ;;
esac

INGEST_ARGS=(
  "$FAILURELENS_REPORT"
  --project "$FAILURELENS_PROJECT"
  --external-id "$FAILURELENS_EXTERNAL_ID"
  --run-scope "${FAILURELENS_RUN_SCOPE:-unknown}"
  --comparison-trust "${FAILURELENS_COMPARISON_TRUST:-self_reported}"
  --process
)
[[ -n "${FAILURELENS_REPOSITORY:-}" ]] && INGEST_ARGS+=(--repository "$FAILURELENS_REPOSITORY")
[[ -n "${FAILURELENS_BASE_SHA:-}" ]] && INGEST_ARGS+=(--base-sha "$FAILURELENS_BASE_SHA")
[[ -n "${FAILURELENS_HEAD_SHA:-}" ]] && INGEST_ARGS+=(--commit-sha "$FAILURELENS_HEAD_SHA")
[[ -n "${FAILURELENS_BRANCH:-}" ]] && INGEST_ARGS+=(--branch "$FAILURELENS_BRANCH")

INGEST_JSON="$(failurelens ingest "${INGEST_ARGS[@]}")"
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
