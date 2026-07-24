#!/usr/bin/env bash
# Claim-grade end-to-end deletion A/B: first-collision deletion, kernel OFF vs ON,
# same instance, same commit. Run from a CLEAN checkout at the pinned commit on
# moe-server. Fail-fast (set -e): if the kernel-off phase fails, the script stops
# and never prints DONE, so a half-run cannot masquerade as a result.
#
# Usage (from the clone root): bash research/triangle/kernel_ab.sh <workload> <cand>
set -euo pipefail

WL="${1:-resnet50}"
CAND="${2:-1}"
BUDGET=7200

echo "### GIT RECEIPT ###"
echo "HEAD=$(git rev-parse HEAD)"
DIRTY="$(git status --porcelain)"
if [ -n "$DIRTY" ]; then
  echo "WARNING: worktree is DIRTY -- this run is NOT claim-grade:"; echo "$DIRTY"
else
  echo "worktree: clean"
fi
echo "### ENV ###"
.venv/bin/python -c "import sys,numpy,scipy; print('python', sys.version.split()[0], \
  'numpy', numpy.__version__, 'scipy', scipy.__version__)"

run() {
  mode=$1
  echo "### USE_KERNEL=$mode start $(date -u +%FT%TZ) ###"
  t0=$(date +%s)
  CERTITHERM_LP_WORKERS=16 CERTITHERM_DELETION_MODE=first CERTITHERM_USE_KERNEL="$mode" \
    .venv/bin/python -u research/triangle/upper_bound.py artifacts/diag150b "$BUDGET" "$WL" "$CAND"
  t1=$(date +%s)
  echo "### kernel${mode}_WALL=$((t1 - t0))s ###"
  echo "### kernel${mode}_MANIFEST ###"
  cat "artifacts/diag150b/upper_bound_${WL}_c${CAND}.json"
  cp "artifacts/diag150b/upper_bound_${WL}_c${CAND}.json" \
     "artifacts/diag150b/upper_bound_${WL}_c${CAND}_kernel${mode}.json"
}

run 0
run 1
echo "### KERNEL AB DONE $(date -u +%FT%TZ) ###"
echo "### soundness check: the two final U/cover must be identical ###"
