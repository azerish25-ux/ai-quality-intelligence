#!/usr/bin/env bash
set -euo pipefail
cp .delivery/browser.sh /tmp/browser.sh
cp .delivery/publish.sh /tmp/publish.sh
chmod +x /tmp/browser.sh /tmp/publish.sh
cat .delivery/patch.part* | base64 --decode > /tmp/failurelens-m4.patch.xz
echo "${PATCH_SHA256}  /tmp/failurelens-m4.patch.xz" | sha256sum --check --strict
remote_main="$(git ls-remote origin refs/heads/main | cut -f1)"
test "$remote_main" = "$BASE_SHA"
cat > /tmp/expected-files <<'EOF'
.github/workflows/ci.yml
Makefile
README.md
backend/migrations/versions/f2a8d4c6e710_explainable_change_impact.py
backend/pyproject.toml
backend/src/failurelens/__init__.py
backend/src/failurelens/api.py
backend/src/failurelens/cli.py
backend/src/failurelens/demo.py
backend/src/failurelens/impact.py
backend/src/failurelens/ingestion.py
backend/src/failurelens/models.py
backend/src/failurelens/schemas.py
backend/tests/test_api.py
backend/tests/test_evaluation.py
backend/tests/test_impact.py
backend/tests/test_ingestion_m2_adapters.py
docs/PROGRESS.md
docs/api-and-cli.md
docs/architecture.md
docs/evaluation.md
docs/history.md
docs/impact.md
docs/input-compatibility.md
docs/requirements-matrix.md
evaluation/corpus/impact-cases.json
evaluation/corpus/impact-manifest.json
evaluation/generate_impact_corpus.py
evaluation/impact_harness.py
evaluation/reports/latest/impact-metrics.json
evaluation/reports/latest/impact-predictions.jsonl
evaluation/reports/latest/impact-report.md
frontend/e2e/durable-ingestion.spec.ts
frontend/package-lock.json
frontend/package.json
frontend/src/App.tsx
frontend/src/ImpactWorkspace.tsx
frontend/src/api.test.ts
frontend/src/api.ts
frontend/src/styles.css
scripts/verify.sh
EOF
sort -o /tmp/expected-files /tmp/expected-files
test "$(wc -l < /tmp/expected-files)" -eq 41
git checkout --detach "$BASE_SHA"
xz --decompress --stdout /tmp/failurelens-m4.patch.xz | git apply --index --whitespace=nowarn
git diff --cached --name-only | sort > /tmp/actual-files
diff -u /tmp/expected-files /tmp/actual-files
test "$(wc -l < /tmp/actual-files)" -eq 41
git config user.name 'github-actions[bot]'
git config user.email '41898282+github-actions[bot]@users.noreply.github.com'
git commit \
  -m 'feat(m4): deliver explainable change-impact selection' \
  -m 'Add deterministic graph-backed focused test recommendations, conservative full-suite fallbacks, append-only audited overrides, typed API/CLI/dashboard workflows, migration coverage, controlled evaluation, and truthful documentation.'
final_sha="$(git rev-parse HEAD)"
test "$(git rev-parse HEAD^)" = "$BASE_SHA"
printf '%s\n' "$final_sha" > /tmp/final-sha.txt
git diff --exit-code HEAD
