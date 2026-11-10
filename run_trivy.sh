#!/bin/bash

# Trivy vulnerability scan of this repo's Python dependencies.
# requirements.txt uses version ranges (>=), which Trivy can't resolve, so this
# scans a pinned `pip freeze` of the installed .venv instead (includes transitive deps).
# Trivy doesn't support a dependency tree for pip, so --dependency-tree is a no-op here.
# Extra args are passed through, e.g. ./run_trivy.sh --severity HIGH,CRITICAL

cd "$(dirname "$0")" || exit 1

if ! command -v trivy >/dev/null 2>&1; then
  echo "trivy not found. Install with: brew install trivy" >&2
  exit 1
fi

if [ ! -x .venv/bin/pip ]; then
  echo ".venv not found. Create it with: python -m venv .venv && .venv/bin/pip install -r requirements-dev.txt" >&2
  exit 1
fi

scan_dir=$(mktemp -d)
trap 'rm -rf "$scan_dir"' EXIT

.venv/bin/pip freeze --exclude-editable > "$scan_dir/requirements.txt"

trivy fs --scanners vuln --dependency-tree "$@" "$scan_dir"
