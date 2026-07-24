#!/usr/bin/env bash
# Non-incremental lever A/B: MaxHS kernel-first verify OFF vs ON, same budget.
# Metric is rounds completed + L reached in a fixed wall budget (LP-count driven,
# so robust to mild machine contention). Usage: bash maxhs_ab.sh <wl> <cand> <budget>
set -euo pipefail
WL="${1:-resnet50}"; CAND="${2:-1}"; BUDGET="${3:-600}"
echo "### GIT: HEAD=$(git rev-parse HEAD) dirty=$(git status --porcelain | wc -l) ###"
run() {
  k=$1
  echo "### MAXHS USE_KERNEL=$k start $(date -u +%FT%TZ) ###"
  t0=$(date +%s)
  OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  CERTITHERM_VERIFY_WORKERS=8 CERTITHERM_USE_KERNEL="$k" \
    .venv/bin/python -u research/triangle/maxhs.py artifacts/diag150b "$BUDGET" "$WL" "$CAND" \
    2>&1 | grep -E "kernel built|^round |budget hit|CONVERGED|lower bound|interval"
  t1=$(date +%s)
  echo "### maxhs_k${k}_WALL=$((t1 - t0))s ###"
}
run 0
run 1
echo "### MAXHS AB DONE $(date -u +%FT%TZ) ###"
