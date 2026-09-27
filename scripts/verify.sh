#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

printf '\n== backend tests and branch coverage ==\n'
(
  cd backend
  PYTHONPATH=src pytest --cov=failurelens --cov-branch --cov-report=term-missing --cov-fail-under=75
)

printf '\n== migration upgrade from empty database ==\n'
MIGRATION_DB="$ROOT/backend/verify-migration.db"
rm -f "$MIGRATION_DB"
(
  cd backend
  PYTHONPATH=src FAILURELENS_DATABASE_URL="sqlite+pysqlite:///$MIGRATION_DB" alembic upgrade head
  PYTHONPATH=src FAILURELENS_DATABASE_URL="sqlite+pysqlite:///$MIGRATION_DB" alembic downgrade f1a9d4c7e620
  PYTHONPATH=src FAILURELENS_DATABASE_URL="sqlite+pysqlite:///$MIGRATION_DB" alembic upgrade head
)
rm -f "$MIGRATION_DB"

printf '\n== deterministic evaluation ==\n'
python evaluation/generate_corpus.py >/tmp/failurelens-corpus.json
python evaluation/generate_clustering_corpus.py >/tmp/failurelens-clustering-corpus.json
python evaluation/generate_impact_corpus.py >/tmp/failurelens-impact-corpus.json
python evaluation/generate_performance_corpus.py >/tmp/failurelens-performance-corpus.json
PYTHONPATH=backend/src python evaluation/harness.py --split test --output evaluation/reports/latest >/tmp/failurelens-evaluation.json
PYTHONPATH=backend/src python evaluation/clustering_harness.py --output evaluation/reports/latest >/tmp/failurelens-clustering-evaluation.json
PYTHONPATH=backend/src python evaluation/impact_harness.py --output evaluation/reports/latest >/tmp/failurelens-impact-evaluation.json
PYTHONPATH=backend/src python evaluation/performance_harness.py --output evaluation/reports/latest >/tmp/failurelens-performance-evaluation.json
cat /tmp/failurelens-evaluation.json
cat /tmp/failurelens-clustering-evaluation.json
cat /tmp/failurelens-impact-evaluation.json
cat /tmp/failurelens-performance-evaluation.json

printf '\n== tracked-source secret/canary scan ==\n'
if grep -RInE --exclude-dir=.git --exclude='cases.jsonl' --exclude='predictions.jsonl' '(-----BEGIN (RSA |EC |OPENSSH )?PRIVATE KEY-----|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})' .; then
  echo 'Potential credential material found.' >&2
  exit 1
fi

printf '\nVerification passed. Frontend dependency installation/build is performed in CI; this offline container cannot resolve the npm registry.\n'
