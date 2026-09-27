#!/usr/bin/env bash
set -euo pipefail
python - <<'PY'
import psycopg
with psycopg.connect(
    'postgresql://failurelens:failurelens@127.0.0.1:5432/postgres',
    autocommit=True,
) as connection:
    with connection.cursor() as cursor:
        cursor.execute('DROP DATABASE IF EXISTS failurelens_browser')
        cursor.execute('CREATE DATABASE failurelens_browser')
PY
export FAILURELENS_DATABASE_URL='postgresql+psycopg://failurelens:failurelens@127.0.0.1:5432/failurelens_browser'
(cd backend && alembic upgrade head)
nohup uvicorn failurelens.api:app --host 127.0.0.1 --port 8000 >/tmp/failurelens-api.log 2>&1 &
nohup failurelens-worker --poll-seconds 0.2 >/tmp/failurelens-worker.log 2>&1 &
(cd frontend && nohup npm run dev -- --host 127.0.0.1 --port 5173 >/tmp/failurelens-vite.log 2>&1 &)
for attempt in {1..60}; do
  if curl --fail --silent http://127.0.0.1:8000/health/ready >/dev/null && curl --fail --silent http://127.0.0.1:5173/ >/dev/null; then
    cd frontend
    npm run test:e2e
    exit 0
  fi
  sleep 1
done
cat /tmp/failurelens-api.log /tmp/failurelens-worker.log /tmp/failurelens-vite.log
exit 1
