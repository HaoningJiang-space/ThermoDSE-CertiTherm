"""Place the central interposer/DRAM share where its area says it goes, and price it exactly.

`docs/CENTRAL_SHARE_IS_THE_DECISIVE_UNPLACED_HEAT.md` established the problem: `gen_cover_flp` emits
a **central** block at `coreWidth x coreHeight` — the sys area itself — and
`THERMODSE_ENDPOINT_AUDIT.md:138` records that `interposer` carries all of `sum(nop)/latency` while
`interposer_e0..e3` are **zero**. So the favourable `eblk`-only placement puts the missing heat on
the four frame strips, which is exactly where the trace puts none of it.

That document priced the central share with a **greedy** bound — all of it on the single worst-coupled
block — and found three of four cases vacuous. This computes the physical placement instead.

## Why no Tier-2 change is needed, which was not obvious

The central block cannot be added to `output_3D.flp` because **its area is already occupied**:
`gen_sys_floorplan` writes `eblk0..3` and then tiles the whole sys area with compute blocks, NoC
fillers (`blockX/blockY/blockXY`) and IO. There is no hole to put it in.

But that is the answer, not the obstacle. A source covering the sys area, reduced to this planar
block model, **is** its power distributed over the blocks that tile that area, weighted by their
area. So the placement is

    q_i = dP_central * area_i / sum_{i in sys} area_i        for blocks in the sys area
    q_i = 0                                                  for eblk0..3

and the uplift is `max_j (R q)_j` — one matrix-vector product against an operator already built. No
new floorplan, no new solve, no frozen input changed.

**What this is NOT.** It is a planar reduction, not a stacked model: the interposer physically sits
below the die, and this puts its heat into the die blocks above it. That is the same abstraction the
executed HotSpot model already makes (block mode, one layer, no `-model_3D`), so it is consistent
with the pipeline rather than an improvement on it. A stacked model would be a different study.

## Two brackets, because only one destination is established

* **NoP only** — `1.0052e9 / (3.7405e9 + 1.0052e9) = 21.18 %` of the missing energy. Its destination
  is fixed by the generator, so this bracket is established.
* **all missing** — the upper bracket, assuming the DRAM share also lands centrally. DRAM's own
  placing code is commented out (`statistic.py:359-363`) and would have written `dram` plus four edge
  strips, so its split is **not** established and this bracket is an assumption.

NON-CLAIM diagnostic. Reads committed operators and captures; writes nothing.

Usage (moe-server):

    python research/triangle/robustness/central_share_uplift.py \\
        --operators /data/ziheng/certicheck/cellcert \\
        --captures  /data/ziheng/experiments/certitherm-v3-dev-final-c9c42ec/output/captures
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

# Audit ledger, docs/THERMODSE_ENDPOINT_AUDIT.md section 3, in pJ. The ledger closes to zero residual.
DRAM_PJ = 3.7405e9
NOP_PJ = 1.0052e9
NOP_SHARE = NOP_PJ / (DRAM_PJ + NOP_PJ)
# The audit's closure: dissipated 9.2218 mJ against 4.6118 mJ arriving, so the missing energy is
# 0.9996x the arriving energy. Recomputed from the capture rather than hard-coded per case.
MISSING_OVER_ARRIVING = 9.2218e9 / 4.6118e9 - 1.0

FRAME = ("eblk0", "eblk1", "eblk2", "eblk3")
LIMIT_K = 330.0
MARGIN_K = 0.05
LINEARISATION_K = 0.01


def _option(argv, name, default):
    return argv[argv.index(name) + 1] if name in argv else default


def _areas(floorplan_text: str):
    """`{block_id: area_m2}` from a HotSpot floorplan. Columns are name, width, height, x, y."""

    areas = {}
    for line in floorplan_text.splitlines():
        parts = line.split()
        if len(parts) < 3 or line.lstrip().startswith("#"):
            continue
        try:
            areas[parts[0]] = float(parts[1]) * float(parts[2])
        except ValueError:
            continue
    return areas


def main() -> None:
    argv = sys.argv[1:]
    operators = Path(_option(argv, "--operators", "/data/ziheng/certicheck/cellcert"))
    captures = Path(_option(argv, "--captures",
                            "/data/ziheng/experiments/certitherm-v3-dev-final-c9c42ec/output/captures"))

    ceiling = LIMIT_K - MARGIN_K - LINEARISATION_K
    print(f"NoP share of the missing energy = {NOP_SHARE:.4f}   "
          f"missing/arriving = {MISSING_OVER_ARRIVING:.4f}")
    print(f"certifying ceiling = {LIMIT_K} - {MARGIN_K} - {LINEARISATION_K} = {ceiling:.2f} K\n")
    print(f"{'case':22s} {'peak':>9s} {'slack':>8s} {'dP':>7s} "
          f"{'NoP@area':>9s} {'verdict':>8s} {'all@area':>9s} {'verdict':>8s}")

    rows = []
    for arch in ("arch_a", "arch_b", "arch_c"):
        for workload in ("resnet50", "transformer"):
            op_path = operators / f"{arch}-{workload}.npz"
            cap_path = captures / f"{workload}--{arch}.npz"
            if not op_path.exists() or not cap_path.exists():
                print(f"{arch}/{workload:12s} MISSING {op_path.name} or {cap_path.name}")
                continue

            op = np.load(op_path, allow_pickle=True)
            cap = np.load(cap_path, allow_pickle=True)
            response = np.asarray(op["response_k_per_w"])[0]          # (cells, blocks)
            ambient = np.asarray(op["ambient_k"])[0]                  # (cells,)
            block_ids = [str(b) for b in np.asarray(op["block_ids"])]
            placed = np.asarray(cap["placed_power_w"], dtype=float)
            cap_ids = [str(b) for b in np.asarray(cap["block_ids"])]
            areas = _areas(str(cap["floorplan_text"]))

            if cap_ids != block_ids:
                raise SystemExit(
                    f"{arch}/{workload}: capture and operator disagree on block order; a power vector "
                    "aligned to one and multiplied by the other is silently wrong"
                )
            unknown = [b for b in block_ids if b not in areas]
            if unknown:
                raise SystemExit(
                    f"{arch}/{workload}: {len(unknown)} operator blocks have no floorplan entry "
                    f"(first: {unknown[:3]}); an area weighting over them would be arbitrary"
                )

            # The support: every block in the sys area, i.e. everything except the four frame strips.
            in_sys = np.array([b not in FRAME for b in block_ids])
            area = np.array([areas[b] for b in block_ids])
            if not in_sys.any() or area[in_sys].sum() <= 0.0:
                raise SystemExit(f"{arch}/{workload}: empty sys-area support")

            weight = np.where(in_sys, area, 0.0)
            weight = weight / weight.sum()

            dP = float(placed.sum()) * MISSING_OVER_ARRIVING
            peak = float(np.max(ambient + response @ placed))
            slack = ceiling - peak

            uplift_nop = float(np.max(response @ (weight * dP * NOP_SHARE)))
            uplift_all = float(np.max(response @ (weight * dP)))
            ok = lambda u: "OK" if u < slack else "VACUOUS"
            print(f"{arch}/{workload:12s} {peak:9.3f} {slack:8.3f} {dP:7.2f} "
                  f"{uplift_nop:9.3f} {ok(uplift_nop):>8s} {uplift_all:9.3f} {ok(uplift_all):>8s}")
            rows.append((f"{arch}/{workload}", slack, uplift_nop, uplift_all))

    if rows:
        print()
        n_nop = sum(1 for _, s, u, _ in rows if u < s)
        n_all = sum(1 for _, s, _, u in rows if u < s)
        print(f"survive with the ESTABLISHED NoP share placed by area: {n_nop} of {len(rows)}")
        print(f"survive with ALL missing power placed by area:         {n_all} of {len(rows)}")
        print()
        print("The NoP column is the established destination. The all-missing column assumes the")
        print("DRAM share also lands centrally, which its commented-out placing code does not say.")


if __name__ == "__main__":
    main()
