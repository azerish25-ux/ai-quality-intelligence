#!/usr/bin/env bash
set -euo pipefail
final_sha="$(cat /tmp/final-sha.txt)"
test "$(git rev-parse HEAD)" = "$final_sha"
git diff --exit-code HEAD
test -z "$(git status --porcelain --untracked-files=no)"
remote_main="$(git ls-remote origin refs/heads/main | cut -f1)"
test "$remote_main" = "$BASE_SHA"
git push origin "$final_sha:refs/heads/main"
test "$(git ls-remote origin refs/heads/main | cut -f1)" = "$final_sha"
for workflow in ci.yml source-export.yml; do
  curl --fail --silent --show-error \
    --request POST \
    --header "Authorization: Bearer ${GH_TOKEN}" \
    --header 'Accept: application/vnd.github+json' \
    --header 'X-GitHub-Api-Version: 2022-11-28' \
    "https://api.github.com/repos/${GITHUB_REPOSITORY}/actions/workflows/${workflow}/dispatches" \
    --data '{"ref":"main"}'
done
git push origin --delete delivery/m4-impact
