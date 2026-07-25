#!/usr/bin/env bash
# V6.1 causal isolation: which power component produces the one grid-max counterexample?
#
# The registered flip (docs/V6_PHYSICAL_TRACE_GATE.md): Transformer/arch_b under
# grid64-max is 329.904867 K time-mean steady and 330.19 K on periodic replay, both at
# mtxu_16, unchanged across 1.0/0.5/0.25 us and across grid64/grid128.
#
# THE GATE: the full-component replay must reproduce 330.19 K at mtxu_16. If it does not,
# component masking changed something it should not have and NO ablation row may be read.
#
# Attribution rule, fixed before running: attribute the flip to the smallest component
# addition whose PERIODIC peak crosses 330 K while its TIME-MEAN steady peak does not. If no
# single addition does, the mechanism is a superposition and must be reported as such --
# temperature superposes but max() does not, so component peaks are not additive.
#
# Reuses the verified engine throughout: complete_trace_probe.py for lowering (which
# enforces every route receipt against the full ledger even under a mask) and
# transient_trace_probe.py -> CertiTherm.transient.replay_periodic for replay.
#
# Usage (clone root): bash research/triangle/v61_causal_isolation.sh [out] [model] [step_us]
set -euo pipefail

OUT="${1:-artifacts/v61}"
MODEL="${2:-grid64-max}"
STEP="${3:-0.5}"
WL=transformer
ARCH=arch_b

echo "### GIT: HEAD=$(git rev-parse HEAD) dirty=$(git status --porcelain | wc -l) ###"
echo "### model=$MODEL step=${STEP}us candidate=$WL/$ARCH ###"

mkdir -p "$OUT"
FLP="$OUT/complete_floorplan_${WL}_${ARCH}.flp"
SIM="$OUT/work/capture--${WL}--${ARCH}"

# 1. lower the full trace (also materialises the floorplan and sim workspace), then the
#    four ablations. Masked emissions carry the mask in their filename so the full-trace
#    evidence cannot be overwritten.
for C in "" core core,noc core,nop core,dram; do
  echo "### lowering components=${C:-ALL} ###"
  .venv/bin/python -u research/triangle/complete_trace_probe.py \
      "$OUT" "$WL" "$ARCH" 1.0 "$C" 2>&1 | grep -E "wrote|source|FAIL" | tail -4
done

# 2. replay each, identical model / step / initial state
for T in "" _core _core-noc _core-nop _core-dram; do
  NPZ="$OUT/complete_trace_${WL}_${ARCH}${T}.npz"
  DEST="$OUT/replay${T:-_full}_${MODEL}_${STEP}us"
  echo "############ replay components=${T:-ALL} ############"
  if [ ! -f "$NPZ" ]; then echo "FAIL: missing $NPZ" >&2; exit 2; fi
  .venv/bin/python -u research/triangle/transient_trace_probe.py \
      "$NPZ" "$FLP" "$SIM" "$DEST" "$MODEL" "$STEP" 2>&1 | tail -16
done
echo "### V61 CAUSAL ISOLATION DONE $(date -u +%FT%TZ) ###"
