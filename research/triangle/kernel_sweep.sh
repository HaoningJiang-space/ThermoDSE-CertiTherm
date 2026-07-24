#!/usr/bin/env bash
# Push-to-the-limit sweep: kernelized thread backend, worker count x HiGHS inner
# threads. Records wall, kernel-build time and U for each config so deletion-only
# time (wall - build) and the parallel ceiling are both visible.
# Usage (clone root): bash research/triangle/kernel_sweep.sh <workload> <cand>
set -euo pipefail

WL="${1:-resnet50}"
CAND="${2:-1}"

echo "### GIT: HEAD=$(git rev-parse HEAD) dirty=$(git status --porcelain | wc -l) ###"
echo "### CPUs=$(nproc) ###"

run() {
  workers=$1
  inner=$2
  echo "### WORKERS=$workers HIGHS_INNER=$inner start $(date -u +%FT%TZ) ###"
  t0=$(date +%s)
  OMP_NUM_THREADS="$inner" OPENBLAS_NUM_THREADS="$inner" MKL_NUM_THREADS="$inner" \
  CERTITHERM_LP_WORKERS="$workers" CERTITHERM_DELETION_MODE=first \
  CERTITHERM_USE_KERNEL=1 CERTITHERM_ORACLE_BACKEND=thread \
    .venv/bin/python -u research/triangle/upper_bound.py artifacts/diag150b 5400 "$WL" "$CAND" \
    2>&1 | grep -E "kernel built|verified feasible|item-2 gate"
  t1=$(date +%s)
  echo "### w${workers}_i${inner}_WALL=$((t1 - t0))s ###"
}

for w in 8 16 32 48; do
  run "$w" 1
done
# check whether HiGHS inner threads matter at the best-ish outer count
run 32 2
echo "### SWEEP DONE $(date -u +%FT%TZ) ###"
