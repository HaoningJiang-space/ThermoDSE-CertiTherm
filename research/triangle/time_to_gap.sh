#!/usr/bin/env bash
# Clean, pinned TIME-TO-GAP ablation across all real dev candidates.
# Measures the acceptance gate directly: time until L >= U/1.2 using the verified U
# from the comprehensive deletion eval. Three arms isolate each lever:
#   seq    = original MaxHS      (VERIFY_WORKERS=1,  no kernel)
#   thread = thread only         (VERIFY_WORKERS=16, no kernel)
#   kernel = kernel-first+thread (VERIFY_WORKERS=16, kernel)
# A run that never reaches the gap inside BUDGET is recorded as "budget hit".
# Usage (clone root): bash research/triangle/time_to_gap.sh [budget]
set -euo pipefail

BUDGET="${1:-1800}"
echo "### GIT: HEAD=$(git rev-parse HEAD) dirty=$(git status --porcelain | wc -l) ###"
echo "### CPUs=$(nproc) BUDGET=${BUDGET}s TARGET_GAP=1.2 ###"

# verified U per candidate (from the comprehensive deletion eval, identical in both modes)
u_for() {
  case "$1 $2" in
    "resnet50 1") echo 1091 ;;
    "resnet50 2") echo 1457 ;;
    "resnet50 0") echo 1383 ;;
    "transformer 0") echo 1383 ;;
    *) echo 0 ;;
  esac
}

run() {
  wl=$1; c=$2; cfg=$3; u=$4
  case "$cfg" in
    seq)    W=1;  K=0 ;;
    thread) W=16; K=0 ;;
    kernel) W=16; K=1 ;;
  esac
  echo "### $wl c$c $cfg (U=$u target L>=$(( u * 10 / 12 ))) start $(date -u +%FT%TZ) ###"
  t0=$(date +%s)
  OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1 MKL_NUM_THREADS=1 \
  CERTITHERM_VERIFY_WORKERS="$W" CERTITHERM_USE_KERNEL="$K" \
  CERTITHERM_TARGET_U="$u" CERTITHERM_TARGET_GAP=1.2 \
    .venv/bin/python -u research/triangle/maxhs.py artifacts/diag150b "$BUDGET" "$wl" "$c" \
    2>&1 | grep -E "TIME-TO-GAP|budget hit|lower bound|kernel built|UNRESOLVED|UNSYNTH"
  t1=$(date +%s)
  echo "### ${wl}_c${c}_${cfg}_WALL=$((t1 - t0))s ###"
}

for spec in "resnet50 1" "resnet50 2" "resnet50 0" "transformer 0"; do
  set -- $spec
  U=$(u_for "$1" "$2")
  for cfg in seq thread kernel; do
    run "$1" "$2" "$cfg" "$U"
  done
done
echo "### TIME-TO-GAP DONE $(date -u +%FT%TZ) ###"
