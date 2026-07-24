#!/usr/bin/env bash
# item-2 A/B: kernelized deletion, process vs thread oracle backend, same instance.
set -euo pipefail
echo "### GIT: HEAD=$(git rev-parse HEAD) dirty=$(git status --porcelain | wc -l) ###"
run() {
  be=$1
  echo "### BACKEND=$be start $(date -u +%FT%TZ) ###"
  t0=$(date +%s)
  CERTITHERM_LP_WORKERS=16 CERTITHERM_DELETION_MODE=first CERTITHERM_USE_KERNEL=1 \
    CERTITHERM_ORACLE_BACKEND="$be" \
    .venv/bin/python -u research/triangle/upper_bound.py artifacts/diag150b 5400 resnet50 1 \
    2>&1 | grep -E "verified feasible|item-2 gate|kernel built"
  t1=$(date +%s)
  echo "### ${be}_WALL=$((t1 - t0))s ###"
}
run process
run thread
echo "### BACKEND AB DONE $(date -u +%FT%TZ) ###"
