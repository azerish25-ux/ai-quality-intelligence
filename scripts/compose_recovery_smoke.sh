#!/usr/bin/env bash
# Disposable synthetic stack only. Never operates on the normal Compose project.
set -euo pipefail
[[ "${1:-}" == "--confirm-disposable-stack" ]] || { echo 'Require --confirm-disposable-stack' >&2; exit 2; }
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
PROJECT="loose_thread_smoke_${GITHUB_RUN_ID:-local}_$$"
OUT="$(mktemp -d "${TMPDIR:-/tmp}/loose-thread-recovery.XXXXXXXX")"
chmod 700 "$OUT"
compose() { docker compose -p "$PROJECT" "$@"; }
cleanup() {
  local result=$?
  compose logs --no-color > "$OUT/compose.log" 2>&1 || true
  if [[ "$result" != 0 ]]; then tail -200 "$OUT/compose.log" >&2; fi
  compose down --volumes --remove-orphans >/dev/null 2>&1 || true
}
trap cleanup EXIT
compose up --build --wait --wait-timeout 180
# The API and durable worker share only an internal network with PostgreSQL.
compose exec -T api python - <<'PY'
import socket
try:
    socket.create_connection(('1.1.1.1', 443), timeout=2)
except OSError:
    print('Runtime external-network probe blocked as expected')
else:
    raise SystemExit('Runtime external-network isolation failed')
PY
curl --fail --silent http://127.0.0.1:8080/ > "$OUT/dashboard.html"
curl --fail --silent -X POST http://127.0.0.1:8000/api/v1/demo/seed > "$OUT/seed.json"
curl --fail --silent http://127.0.0.1:8000/api/v1/overview > "$OUT/before.json"
python - "$OUT/before.json" <<'PY'
import json,sys
r=json.load(open(sys.argv[1])); assert r['projects']==1 and r['runs']==1 and r['analyses']==3,r
PY
compose restart api worker
for attempt in {1..60}; do
  if curl --fail --silent http://127.0.0.1:8000/health/ready >/dev/null; then break; fi
  sleep 1
done
curl --fail --silent http://127.0.0.1:8000/api/v1/overview > "$OUT/after.json"
python - "$OUT/before.json" "$OUT/after.json" <<'PY'
import json,sys
assert json.load(open(sys.argv[1]))==json.load(open(sys.argv[2])), 'restart lost persisted data'
PY
# Quiesce writers, then back up DB and private artifact volume as one snapshot.
compose stop api worker
compose exec -T db pg_dump -U failurelens --format=custom failurelens > "$OUT/database.dump"
compose run --rm --no-deps --entrypoint tar api -C /var/lib/failurelens/artifacts -cf - . > "$OUT/artifacts.tar"
chmod 600 "$OUT/database.dump" "$OUT/artifacts.tar"
compose exec -T db createdb -U failurelens failurelens_restore
compose exec -T db pg_restore -U failurelens --dbname=failurelens_restore --single-transaction --exit-on-error --no-owner --no-privileges < "$OUT/database.dump"
SOURCE="$(compose exec -T db psql -U failurelens -d failurelens -Atc 'SELECT (SELECT count(*) FROM runs), (SELECT count(*) FROM analyses), (SELECT count(*) FROM evidence);')"
RESTORED="$(compose exec -T db psql -U failurelens -d failurelens_restore -Atc 'SELECT (SELECT count(*) FROM runs), (SELECT count(*) FROM analyses), (SELECT count(*) FROM evidence);')"
[[ "$SOURCE" == "$RESTORED" && -n "$SOURCE" ]] || { echo 'Restored database counts differ' >&2; exit 1; }
# Restore artifacts into a fresh container directory and verify restored DB citations.
compose run --rm --no-deps \
  -e FAILURELENS_DATABASE_URL=postgresql+psycopg://failurelens:failurelens@db:5432/failurelens_restore \
  -e FAILURELENS_ARTIFACT_ROOT=/tmp/restored-artifacts \
  --entrypoint python api -c '
import io,sys,tarfile
from pathlib import Path
from sqlalchemy import select
from failurelens.db import SessionLocal
from failurelens.models import Analysis,Run
from failurelens.github_snapshot import report_snapshot
raw=sys.stdin.buffer.read(50_000_001)
assert len(raw)<=50_000_000
root=Path("/tmp/restored-artifacts");root.mkdir()
with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
    entries=archive.getmembers()
    assert entries and sum(x.size for x in entries)<50_000_000
    assert all(not x.name.startswith("/") and ".." not in x.name.split("/") and not x.issym() and not x.islnk() for x in entries)
    archive.extractall(root,filter="data")
with SessionLocal() as session:
    runs=session.scalars(select(Run)).all()
    assert len(runs)==1
    report=report_snapshot(session,runs[0])
    assert report["analysis_count"]==3
    assert sum(x["category"]=="product_defect" for x in report["analyses"])==2,report
    assert all(x["supporting_evidence_ids"] for x in report["analyses"] if x["category"]=="product_defect")
print("Restored database and artifact bodies pass the real publication evidence validator")
' < "$OUT/artifacts.tar"
printf 'PASS: isolated runtime, synthetic seed, restart persistence, transactional DB/artifact restore with evidence validation\nEvidence directory: %s\n' "$OUT"
