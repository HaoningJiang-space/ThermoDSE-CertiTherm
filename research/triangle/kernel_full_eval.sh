#!/usr/bin/env bash
# Comprehensive REAL-WORKLOAD evaluation: every dev candidate, baseline vs
# kernel+thread, both to completion. Produces the per-candidate end-to-end table
# (wall + U + cover) that generalises the arch_c 21x beyond a single instance.
# U/cover MUST be identical between the two modes for every candidate (soundness).
# Usage (clone root): bash research/triangle/kernel_full_eval.sh [workers]
set -euo pipefail

WORKERS="${1:-16}"
echo "### GIT: HEAD=$(git rev-parse HEAD) dirty=$(git status --porcelain | wc -l) ###"
echo "### CPUs=$(nproc) WORKERS=$WORKERS ###"
.venv/bin/python -c "import sys,numpy,scipy; print('python',sys.version.split()[0],'numpy',numpy.__version__,'scipy',scipy.__version__)"

run() {
  wl=$1; cand=$2; mode=$3            # mode: base | kernel
  if [ "$mode" = base ]; then K=0; BE=process; else K=1; BE=thread; fi
  echo "### $wl c$cand $mode start $(date -u +%FT%TZ) ###"
  t0=$(date +%s)
  OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  CERTITHERM_LP_WORKERS="$WORKERS" CERTITHERM_DELETION_MODE=first \
  CERTITHERM_USE_KERNEL="$K" CERTITHERM_ORACLE_BACKEND="$BE" \
    .venv/bin/python -u research/triangle/upper_bound.py artifacts/diag150b 10800 "$wl" "$cand" \
    2>&1 | grep -E "kernel built|verified feasible|item-2 gate"
  t1=$(date +%s)
  echo "### ${wl}_c${cand}_${mode}_WALL=$((t1 - t0))s ###"
}

for spec in "resnet50 1" "resnet50 2" "resnet50 0" "transformer 0"; do
  set -- $spec
  run "$1" "$2" base
  run "$1" "$2" kernel
done
echo "### FULL EVAL DONE $(date -u +%FT%TZ) ###"
