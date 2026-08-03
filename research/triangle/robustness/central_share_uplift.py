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

**The uplift is compared against the POLYTOPE slack, not the nominal one.** The certified quantity is
`max_j sup_p T_j(p)` over the declared activity span, not the peak at the placed map; an earlier
version of this script compared against the nominal peak and read `arch_b/transformer` as `+1.164 K`
of slack where the certificate has `-0.3618`. Adding a fixed `q` shifts every row, so
`max_j [sup_p T_j(p) + (Rq)_j] <= max_j sup_p T_j(p) + max_j (Rq)_j` and the comparison is
conservative in the right direction.

**What this is NOT.** It is a planar reduction, not a stacked model: the interposer physically sits
below the die, and this puts its heat into the die blocks above it. That is the same abstraction the
executed HotSpot model already makes (block mode, one layer, no `-model_3D`), so it is consistent
with the pipeline rather than an improvement on it. A stacked model would be a different study.

## Both columns are established; neither is an assumption

`gen_all_ptrace_3D` writes its header **central first** —
`'interposer\tinterposer_e0\t...'` — and then `p_itp, 0, 0, 0, 0`, so NoP goes wholly to the central
block and the frame strips get zero. The commented-out DRAM block repeats the pattern with its own
header line (`# str_ += 'dram\tdram_e0\t...'`) and `p_itp` accumulated from `dram_dict`, so **its
intended placement is 100 % central too**.

* **NoP only** — `21.18 %` of the missing energy. What the uncommented code places today.
* **both** — the placement the generator states once the commented DRAM write is restored.

An earlier version of this file called the second column an assumption, on a reading that had the
column order backwards (`_e0` first). The header line is one line above the write and settles it.

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

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from CertiTherm.cross_grid_bound import _extreme_rows          # noqa: E402
from CertiTherm.measurements import activity_bounded_power_space  # noqa: E402

# Audit ledger, docs/THERMODSE_ENDPOINT_AUDIT.md section 3, in pJ. The ledger closes to zero residual.
DRAM_PJ = 3.7405e9
NOP_PJ = 1.0052e9
NOP_SHARE = NOP_PJ / (DRAM_PJ + NOP_PJ)
# The audit's closure: dissipated 9.2218 mJ against 4.6118 mJ arriving, so the missing energy is
# 0.9996x the arriving energy. Recomputed from the capture rather than hard-coded per case.
MISSING_OVER_ARRIVING = 9.2218e9 / 4.6118e9 - 1.0

FRAME = ("eblk0", "eblk1", "eblk2", "eblk3")


def _core_grid(block_ids):
    """`(cxlen, cylen)` recovered from the block census, refusing if it is not consistent.

    `gen_all_ptrace_3D` names per-core blocks `<name>_<j*cxlen + i>`, and `gen_sys_floorplan` emits
    `blockX` only when `i < cxlen-1`, `blockY` only when `j < cylen-1`, `blockXY` when both. So

        |io_0| = cx*cy,   |blockX| = (cx-1)*cy,   |blockY| = cx*(cy-1),   |blockXY| = (cx-1)*(cy-1)

    which is over-determined -- four counts for two unknowns. Solving from two and CHECKING the other
    two is the point: the NoC over-count factor is `4*cx*cy / ((cy-1)*2*cx + (cx-1)*2*cy)`, it differs
    per architecture (1.3333 at 4x4, 1.2903 at 4x5), and a silently wrong grid would scale every
    corrected number by an unnoticed factor.
    """

    import re
    from collections import Counter

    kinds = Counter(re.sub(r"_\d+$", "", b) for b in block_ids)
    cores, bxy = kinds.get("io_0", 0), kinds.get("blockXY", 0)
    if cores <= 0:
        raise SystemExit("no io_0 blocks: cannot recover the core grid")
    # (cx-1)(cy-1) = cx*cy - (cx+cy) + 1
    total = cores + 1 - bxy
    disc = total * total - 4 * cores
    if disc < 0:
        raise SystemExit(f"core-grid census is inconsistent: |io_0|={cores}, |blockXY|={bxy}")
    root = int(round(disc ** 0.5))
    if root * root != disc:
        raise SystemExit(f"core grid is not integral: |io_0|={cores}, |blockXY|={bxy}")
    cx, cy = (total + root) // 2, (total - root) // 2
    for name, expected in (("blockX", (cx - 1) * cy), ("blockY", cx * (cy - 1))):
        if kinds.get(name, 0) != expected:
            cx, cy = cy, cx                       # the census does not say which axis is which
            break
    if kinds.get("blockX", 0) != (cx - 1) * cy or kinds.get("blockY", 0) != cx * (cy - 1):
        raise SystemExit(
            f"core grid {cx}x{cy} contradicts the census "
            f"(blockX={kinds.get('blockX')}, blockY={kinds.get('blockY')})"
        )
    return cx, cy
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



def noc_spreading_bracket(response, placed, block_ids, slack):
    """How much the UNIFORM NoC spread can be hiding, bracketed rather than assumed.

    `gen_all_ptrace_3D` gives every `io_*` column `p_noc / divisor` — identical for all of them — so
    the trace carries the right total (after the over-count is removed) and **none** of the spatial
    structure. `THERMODSE_ENDPOINT_AUDIT.md` calls the direction of that bias indeterminate: extra
    power raises temperature, while uniform spreading suppresses local hotspots and may hide a flip.

    The magnitude is not indeterminate. Redistributing a fixed budget over a fixed support is bounded
    below by the uniform spread (what the trace does, up to the over-count) and above by putting all
    of it on the single worst-coupled member — a greedy fill, exact and free, since the uplift is
    linear. The bracket width is what the spreading defect can be worth, without needing to know the
    true distribution.

    Returns `(uniform_peak_uplift, adversarial_peak_uplift)` relative to the placed map.
    """

    import numpy as np

    is_io = np.array([b.startswith("io_") for b in block_ids])
    if not is_io.any():
        raise SystemExit("no io_* blocks: the NoC support does not exist in this floorplan")
    budget = float(placed[is_io].sum())

    base = np.max(response @ placed)
    uniform = float(np.max(response @ placed) - base)          # zero by construction, kept explicit
    # Move the whole io budget onto whichever single io block couples hardest into any row. The
    # support is restricted to io_* because that is where the generator put NoC; a wider support
    # would be bounding a different defect.
    without_io = np.where(is_io, 0.0, placed)
    worst = float(np.max([np.max(response @ (without_io + budget * unit))
                          for unit in np.eye(len(block_ids))[is_io]]))
    return uniform, worst - base


def main() -> None:
    argv = sys.argv[1:]
    operators = Path(_option(argv, "--operators", "/data/ziheng/certicheck/cellcert"))
    captures = Path(_option(argv, "--captures",
                            "/data/ziheng/experiments/certitherm-v3-dev-final-c9c42ec/output/captures"))
    span = float(_option(argv, "--span", "0.30"))

    ceiling = LIMIT_K - MARGIN_K - LINEARISATION_K
    print(f"NoP share of the missing energy = {NOP_SHARE:.4f}   "
          f"missing/arriving = {MISSING_OVER_ARRIVING:.4f}   activity span = {span}")
    print(f"certifying ceiling = {LIMIT_K} - {MARGIN_K} - {LINEARISATION_K} = {ceiling:.2f} K\n")
    print(f"{'case':22s} {'sup_p peak':>10s} {'slack':>8s} {'dP':>7s} "
          f"{'NoP@area':>9s} {'verdict':>8s} {'all@area':>9s} {'verdict':>8s} "
          f"{'grid':>5s} {'overcnt':>7s} {'dNoC':>8s} {'NET':>8s} {'verdict':>8s} {'spreadHi':>9s}")

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
            # The CERTIFIED quantity: max over rows of the supremum over the polytope, which is what
            # CELL_ENDPOINT_RESULT.md reports. The nominal peak is 1.5 K lower on the tightest point.
            space = activity_bounded_power_space(block_ids, placed, activity_span=span)
            sup_rows = _extreme_rows(response, np.asarray(space.lower_w, dtype=float),
                                     np.asarray(space.upper_w, dtype=float), float(placed.sum()))
            peak = float(np.max(ambient + sup_rows))
            slack = ceiling - peak

            uplift_nop = float(np.max(response @ (weight * dP * NOP_SHARE)))
            uplift_all = float(np.max(response @ (weight * dP)))

            # NoC over-count: every io_* column got p_noc/divisor, and there are 4*cx*cy of them, so
            # the trace carries columns/divisor times the source. Correcting it REMOVES heat, so its
            # contribution to the uplift is negative. It does NOT repair the uniform spreading, which
            # destroys the spatial information and whose sign the audit calls indeterminate.
            cx, cy = _core_grid(block_ids)
            divisor = (cy - 1) * 2 * cx + (cx - 1) * 2 * cy
            columns = 4 * cx * cy
            overcount = columns / divisor
            is_io = np.array([b.startswith("io_") for b in block_ids])
            noc_fix = np.where(is_io, placed * (1.0 / overcount - 1.0), 0.0)
            delta_noc = float(np.max(response @ (placed + noc_fix)) - np.max(response @ placed))
            net = uplift_all + delta_noc

            # The uniform spread carries the right total and none of the structure. Its cost is
            # bracketed, not assumed: uniform below, all-on-the-worst-io-block above.
            _, noc_hi = noc_spreading_bracket(response, placed, block_ids, slack)

            ok = lambda u: "OK" if u < slack else "VACUOUS"
            print(f"{arch}/{workload:12s} {peak:10.4f} {slack:8.4f} {dP:7.2f} "
                  f"{uplift_nop:9.3f} {ok(uplift_nop):>8s} {uplift_all:9.3f} {ok(uplift_all):>8s} "
                  f"{cx}x{cy} {overcount:7.4f} {delta_noc:8.3f} {net:8.3f} {ok(net):>8s} "
                  f"{noc_hi:9.3f}")
            rows.append((f"{arch}/{workload}", slack, uplift_nop, uplift_all, net))

    if rows:
        print()
        n_nop = sum(1 for _, s, u, _, _ in rows if u < s)
        n_all = sum(1 for _, s, _, u, _ in rows if u < s)
        n_net = sum(1 for _, s, _, _, u in rows if u < s)
        print(f"survive with the NoP share alone placed by area:        {n_nop} of {len(rows)}")
        print(f"survive with BOTH missing sources placed by area:       {n_all} of {len(rows)}")
        print(f"survive NET, i.e. both placed AND the NoC over-count removed: {n_net} of {len(rows)}")
        print()
        print("The NoP column is the established destination. The all-missing column assumes the")
        print("DRAM share also lands centrally, which its commented-out placing code does not say.")


if __name__ == "__main__":
    main()

