#!/usr/bin/env bash
# A/B the deletion ORDER (cost vs spectral leverage) across candidates, replicated.
#
# Ordering cannot change soundness -- every removal is accepted only after an exact
# collision test and the final cover re-verify is always full+exhaustive. So this
# measures only (a) the U it lands on and (b) how fast it gets there.
#
# Replicated because the host is shared: record the competing load with the result.
# Usage (clone root): bash research/triangle/deletion_order_ab.sh [reps]
set -euo pipefail

REPS="${1:-3}"
WORKERS="${CERTITHERM_LP_WORKERS:-16}"   # 16 is the swept optimum; 32/48 are slower

echo "### GIT: HEAD=$(git rev-parse HEAD) dirty=$(git status --porcelain | wc -l) ###"
echo "### CPUs=$(nproc) loadavg=$(cut -d' ' -f1-3 /proc/loadavg) WORKERS=$WORKERS ###"

for rep in $(seq 1 "$REPS"); do
  for ord in cost spectral; do
    while read -r wl cand; do
      [ -z "$wl" ] && continue
      echo "### rep=$rep order=$ord wl=$wl cand=$cand start $(date -u +%FT%TZ) ###"
      t0=$(date +%s)
      CERTITHERM_LP_WORKERS="$WORKERS" \
      CERTITHERM_DELETION_MODE=first \
      CERTITHERM_USE_KERNEL=1 \
      CERTITHERM_ORACLE_BACKEND=thread \
      CERTITHERM_DELETION_ORDER="$ord" \
        .venv/bin/python -u research/triangle/upper_bound.py \
          artifacts/diag150b 5400 "$wl" "$cand" 2>&1 \
        | grep -E "spectral deletion order|verified feasible|item-2 gate|UNSYNTHESIZABLE"
      echo "### rep=$rep RESULT order=$ord wl=$wl cand=$cand WALL=$(( $(date +%s) - t0 ))s ###"
    done <<'CANDS'
resnet50 1
transformer 0
resnet50 2
resnet50 0
CANDS
  done
done
echo "### AB DONE $(date -u +%FT%TZ) loadavg=$(cut -d' ' -f1-3 /proc/loadavg) ###"
