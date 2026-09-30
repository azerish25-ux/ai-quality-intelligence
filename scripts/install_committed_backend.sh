#!/usr/bin/env bash
# Install committed source without setuptools metadata dirtying the measured tree.
set -euo pipefail
ROOT=$(git -C "$(dirname "${BASH_SOURCE[0]}")/.." rev-parse --show-toplevel)
cd "$ROOT"

require_clean() {
  local status
  status=$(git status --porcelain --untracked-files=normal)
  if [[ -n "$status" ]]; then
    printf 'Refusing an uncommitted source measurement:\n%s\n' "$status" >&2
    return 1
  fi
}

require_clean
SOURCE_REVISION=$(git rev-parse HEAD)
BUILD_ROOT=$(mktemp -d /tmp/failurelens-build.XXXXXXXX)
trap 'rm -rf -- "$BUILD_ROOT"' EXIT
# No worktree copy or ignored-file overlay: only the recorded commit is built.
git archive --format=tar "$SOURCE_REVISION" backend | tar -x -C "$BUILD_ROOT"
if [[ -f "$BUILD_ROOT/backend/requirements.lock" ]]; then
  "${PYTHON:-python}" -m pip install --require-hashes -r "$BUILD_ROOT/backend/requirements.lock" "$@"
  "${PYTHON:-python}" -m pip install --no-deps "$BUILD_ROOT/backend[dev]" "$@"
else
  # Small package-build fixtures and pre-lock historical source remain supported.
  "${PYTHON:-python}" -m pip install "$BUILD_ROOT/backend[dev]" "$@"
fi
require_clean
if [[ "$(git rev-parse HEAD)" != "$SOURCE_REVISION" ]]; then
  echo 'Source revision changed while building the backend.' >&2
  exit 1
fi
printf 'Installed committed backend; source remains clean: %s\n' "$SOURCE_REVISION"
