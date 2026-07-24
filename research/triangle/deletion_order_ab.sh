#!/usr/bin/env bash
# COUNTERBALANCED, PAIRED A/B of the deletion ORDER (cost vs spectral leverage).
#
# Ordering cannot change feasibility soundness -- every removal is accepted only after an
# exact collision test and the final cover re-verify is always full+exhaustive. It CAN
# change the final cover and U, so this measures both what it lands on and how fast.
#
# Design, fixing two defects in the first version:
#
#  1. COUNTERBALANCED. The first version ran every `cost` candidate and then every
#     `spectral` candidate, so `spectral` was always later in wall-clock time and was
#     confounded with drifting host load, thermal state and cache warmth. Here the two arms
#     for one candidate run BACK-TO-BACK as a pair, and the order WITHIN the pair alternates
#     with (rep + candidate index), so each arm goes first about half the time.
#
#  2. SEPARATE MANIFESTS. CERTITHERM_MANIFEST_TAG keeps each arm's cover_action_ids on disk,
#     so the two covers can actually be compared. Previously only the last arm survived.
#
# Reported per run: deterministic counters (oracle queries, POOL_REACHED, cover size, U) as
# the PRIMARY evidence -- they are exact and load-independent -- plus wall time and load /
# cache telemetry as paired secondary evidence.
#
# Usage (clone root): bash research/triangle/deletion_order_ab.sh [reps] [out]
set -euo pipefail

REPS="${1:-3}"
OUT="${2:-artifacts/diag150b}"
WORKERS="${CERTITHERM_LP_WORKERS:-16}"    # swept optimum for this candidate; 32/48 slower

CANDS=("resnet50 1" "transformer 0" "resnet50 2" "resnet50 0")

echo "### GIT: HEAD=$(git rev-parse HEAD) dirty=$(git status --porcelain | wc -l) ###"
echo "### HOST: cpus=$(nproc) workers=$WORKERS reps=$REPS ###"

telemetry() {
  # load average, cached pages (cache-warmth proxy), and UTC instant
  local phase=$1
  printf '###   %s t=%s load=%s cached_kB=%s ###\n' \
    "$phase" "$(date -u +%FT%T.%3NZ)" \
    "$(cut -d' ' -f1-3 /proc/loadavg)" \
    "$(awk '/^Cached:/{print $2}' /proc/meminfo)"
}

run_arm() {
  local rep=$1 ord=$2 wl=$3 cand=$4 slot=$5
  local tag="_${ord}_r${rep}"
  echo "### rep=$rep pair_slot=$slot order=$ord wl=$wl cand=$cand ###"
  telemetry "before"
  local t0 t1
  t0=$(date +%s.%N)
  CERTITHERM_LP_WORKERS="$WORKERS" \
  CERTITHERM_DELETION_MODE=first \
  CERTITHERM_USE_KERNEL=1 \
  CERTITHERM_ORACLE_BACKEND=thread \
  CERTITHERM_DELETION_ORDER="$ord" \
  CERTITHERM_MANIFEST_TAG="$tag" \
    .venv/bin/python -u research/triangle/upper_bound.py \
      "$OUT" 5400 "$wl" "$cand" 2>&1 \
    | grep -E "spectral deletion order|verified feasible|item-2 gate|UNSYNTHESIZABLE|UNRESOLVED"
  t1=$(date +%s.%N)
  telemetry "after"
  printf '### rep=%s RESULT order=%s wl=%s cand=%s slot=%s WALL=%.1fs manifest=%s ###\n' \
    "$rep" "$ord" "$wl" "$cand" "$slot" "$(echo "$t1 - $t0" | bc)" \
    "upper_bound_${wl}_c${cand}${tag}.json"
}

for rep in $(seq 1 "$REPS"); do
  ci=0
  for wc in "${CANDS[@]}"; do
    set -- $wc
    wl=$1; cand=$2
    # Alternate which arm runs first, by (rep + candidate index) parity.
    if (( (rep + ci) % 2 == 0 )); then
      first=cost;     second=spectral
    else
      first=spectral; second=cost
    fi
    run_arm "$rep" "$first"  "$wl" "$cand" 1
    run_arm "$rep" "$second" "$wl" "$cand" 2
    ci=$((ci + 1))
  done
done
echo "### AB DONE $(date -u +%FT%TZ) load=$(cut -d' ' -f1-3 /proc/loadavg) ###"
