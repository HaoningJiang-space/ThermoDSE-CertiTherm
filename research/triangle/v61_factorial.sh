#!/usr/bin/env bash
# V6.1 FULL FACTORIAL over the four power sources, on the registered counterexample.
#
# Why the full factorial and not the core-anchored ablation it replaces. The first design
# ran core, core+noc, core+nop, core+dram, full. Review showed two defects:
#
#  * those are core-PLUS-ONE runs, not single-component runs, so "no single component
#    crosses" was misnamed; and
#  * every one of them sat >=1.8 K below the limit while core alone already supplies 69% of
#    the required rise, so the design was structurally near-guaranteed to answer
#    "superposition" regardless of the physics.
#
# Worse, it could not support the claim that ALL FOUR sources are needed: unmeasured
# coalitions such as core+noc+dram might already cross. The factorial removes that gap --
# every one of the 15 non-empty subsets is measured, so minimal crossing coalitions are read
# off directly rather than inferred.
#
# Leave-one-out is included by construction (each triple is full-minus-one), which answers
# the sharper conditional question: is this source NECESSARY given the others are present?
#
# Falsifiable prediction registered before running, from the measured marginal steady rises
# (noc +1.5312 K, nop +0.4998 K, dram +1.7063 K on top of core, FULL margin ~0.095 K):
# every leave-one-out case should fall BELOW 330 K, the closest being full-minus-nop at
# ~329.69 K. If any leave-one-out case stays ABOVE 330 K, the necessity claim is refuted.
#
# Reuses complete_trace_probe.py for masked lowering and transient_trace_probe.py ->
# replay_periodic for replay. No new engine.
#
# Usage (clone root): bash research/triangle/v61_factorial.sh [out] [model] [step_us]
set -euo pipefail

OUT="${1:-artifacts/v61}"
MODEL="${2:-grid64-max}"
STEP="${3:-0.5}"
WL=transformer
ARCH=arch_b

echo "### GIT: HEAD=$(git rev-parse HEAD) dirty=$(git status --porcelain | wc -l) ###"
echo "### FULL FACTORIAL model=$MODEL step=${STEP}us candidate=$WL/$ARCH ###"

mkdir -p "$OUT"
FLP="$OUT/complete_floorplan_${WL}_${ARCH}.flp"
SIM="$OUT/work/capture--${WL}--${ARCH}"

# all 15 non-empty subsets of {core,noc,nop,dram}; "" means the full set
SUBSETS=(
  core noc nop dram
  core,noc core,nop core,dram noc,nop noc,dram nop,dram
  core,noc,nop core,noc,dram core,nop,dram noc,nop,dram
  ""
)

for C in "${SUBSETS[@]}"; do
  echo "### lowering components=${C:-ALL} ###"
  .venv/bin/python -u research/triangle/complete_trace_probe.py \
      "$OUT" "$WL" "$ARCH" 1.0 "$C" 2>&1 | grep -E "wrote|FAIL" | tail -2
done

for C in "${SUBSETS[@]}"; do
  if [ -z "$C" ]; then T=""; else T="_$(echo "$C" | tr ',' '\n' | sort | paste -sd-)"; fi
  NPZ="$OUT/complete_trace_${WL}_${ARCH}${T}.npz"
  DEST="$OUT/fact${T:-_full}_${MODEL}_${STEP}us"
  echo "############ replay components=${C:-ALL} ############"
  if [ ! -f "$NPZ" ]; then echo "FAIL: missing $NPZ" >&2; exit 2; fi
  if [ -d "$DEST" ]; then echo "  reusing $DEST"; continue; fi
  .venv/bin/python -u research/triangle/transient_trace_probe.py \
      "$NPZ" "$FLP" "$SIM" "$DEST" "$MODEL" "$STEP" 2>&1 | tail -6
done
echo "### V61 FACTORIAL DONE $(date -u +%FT%TZ) ###"
