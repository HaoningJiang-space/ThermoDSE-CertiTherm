"""`e_total` at the cell endpoint: the model-form band where the certificate is actually evaluated.

## Why this number and not the one already measured

`docs/MODEL_FORM_AGAINST_AN_INDEPENDENT_SOLVER.md` measures the HotSpot-versus-FEM band at **block**
rows: `0.251 - 1.4332 K` across three packages. `docs/CELL_ENDPOINT_RESULT.md` moved the certificate
to **`grid128` cell** rows and records the cell-level band as not measured, and
`docs/G2_REPAIR_THE_WINDOW_IS_ONE_DIMENSIONAL.md` names that missing number, `e_total`, as an edge of
the separator window that *"exists in no source file in this repository"*.

They are different functionals. A max over 181 block averages and a max over 16 384 cell averages
observe the same field through different projections, and the cell endpoint sits **0.58-0.87 K above**
the exact block projection on the routed traces. Quoting a band measured at one granularity for a
certificate evaluated at the other is the kind of substitution this project has already been wrong
about three times this round.

## What is compared

The **same** `one_sided_containment_bounds` the block-row band uses, so the definition is inherited
rather than re-invented: for every row `j`,

    u_j = sup_{p in P} [ (R_fem - R_hotspot) p + (a_fem - a_hotspot) ]_j

and the band is `max_j u_j`. It is one-sided by construction — it answers *"how much hotter can the
reference be than the tool, anywhere in the envelope"* — which is the direction a fail-closed
certificate has to fold in.

## Fail-closed

Refuses unless both operators resolve the same block list in the same order and the same cell count.
A band computed across a permuted block list is a number about nothing.

NON-CLAIM diagnostic. Usage (moe-server, repo root):
    .venv/bin/python research/triangle/robustness/cell_model_form_band.py \\
        <hotspot-cell.npz> <fem-cell.npz> <capture.npz> [span]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.cross_grid_bound import one_sided_containment_bounds          # noqa: E402
from CertiTherm.experiments import _power_space                               # noqa: E402
from CertiTherm.measurements import activity_bounded_power_space              # noqa: E402


def _operator(path: Path):
    with np.load(path, allow_pickle=False) as data:
        rows = np.asarray(data["response_k_per_w"], dtype=float)[0]
        ambient = np.asarray(data["ambient_k"], dtype=float)[0]
        blocks = [str(b) for b in data["block_ids"]]
    if not (np.all(np.isfinite(rows)) and np.all(np.isfinite(ambient))):
        raise SystemExit(f"{path.name} carries a non-finite entry")
    return rows, ambient, blocks


def main() -> None:
    hotspot_path, fem_path, capture = (Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]))
    span = float(sys.argv[4]) if len(sys.argv) > 4 else 0.30

    hs_rows, hs_ambient, hs_blocks = _operator(hotspot_path)
    fem_rows, fem_ambient, fem_blocks = _operator(fem_path)
    if hs_blocks != fem_blocks:
        raise SystemExit(
            f"the two operators resolve different block lists ({len(hs_blocks)} vs "
            f"{len(fem_blocks)}, or a different order); a band across them is a number about nothing"
        )
    if hs_rows.shape != fem_rows.shape:
        raise SystemExit(
            f"row counts differ: HotSpot {hs_rows.shape}, FEM {fem_rows.shape}. Both must be at the "
            "SAME granularity or the band is a granularity difference wearing a model-form label."
        )

    _space, capture_blocks, placed, _flp = _power_space(capture)
    if list(capture_blocks) != hs_blocks:
        raise SystemExit("the capture and the operators disagree on the block list")
    power = np.asarray(placed, dtype=float)

    polytope = activity_bounded_power_space(capture_blocks, power, activity_span=span)
    b_eq = np.asarray(polytope.b_eq, dtype=float).ravel()
    if b_eq.size != 1:
        raise SystemExit(f"the polytope has {b_eq.size} total-power rows, expected exactly one")

    hotter, colder = one_sided_containment_bounds(
        hs_rows, fem_rows, hs_ambient, fem_ambient,
        np.asarray(polytope.lower_w, dtype=float),
        np.asarray(polytope.upper_w, dtype=float),
        float(b_eq[0]),
        np.asarray(polytope.a_ub, dtype=float),
        np.asarray(polytope.b_ub, dtype=float),
    )
    nominal = (fem_rows - hs_rows) @ power + (fem_ambient - hs_ambient)

    # TWO DIFFERENT QUANTITIES, AND THE PAPER MUST NOT CONFLATE THEM.
    #
    # `e_total = max_j sup_p (T_fem - T_hs)_j` is the ROW-WISE band -- the largest disagreement at
    # any cell, under the worst power map for that cell. It is the quantity the block-row band used
    # and it is what a certificate folds in if it wants `T_fem_j <= T_hs_j + e` for every row.
    #
    # `delta_certified = max_j sup_p T_fem_j - max_j sup_p T_hs_j` is the difference in the
    # CERTIFIED QUANTITY itself. It is what actually moves a verdict, and it is far smaller whenever
    # the two solvers disagree most on cells that are not the hottest -- which is exactly what the
    # nominal peaks agreeing to 0.07 K while `at_nominal_max` reaches 2.6 K says is happening here.
    #
    # Both are reported. `e_total` is the sound thing to fold in row-wise; `delta_certified` is the
    # honest measure of how much the choice of solver moves the answer. Quoting either alone
    # misleads in a different direction.
    from CertiTherm.cross_grid_bound import _extreme_rows
    lower = np.asarray(polytope.lower_w, dtype=float)
    upper = np.asarray(polytope.upper_w, dtype=float)
    hs_per_row = _extreme_rows(hs_rows, lower, upper, float(b_eq[0])) + hs_ambient
    fem_per_row = _extreme_rows(fem_rows, lower, upper, float(b_eq[0])) + fem_ambient
    hs_sup = float(np.max(hs_per_row))
    fem_sup = float(np.max(fem_per_row))

    # THE TIGHT SOUND BOUND, AND IT IS THE ONE THE CERTIFICATE SHOULD USE.
    #
    # `hs_sup + e_total` takes two maxima INDEPENDENTLY: the hottest cell's supremum plus the worst
    # cell's error, even when those are different cells. Here they are -- the peak cells agree to
    # 0.018-0.068 K while the row-wise error reaches 2.63 K on cells that are cold.
    #
    # For any admissible `p` and any row `j`,   T_fem,j(p) <= T_hs,j(p) + u_j <= sup_p T_hs,j + u_j,
    # so                                        max_j T_fem,j(p) <= max_j ( sup_p T_hs,j + u_j ).
    #
    # That is sound for the same reason and strictly tighter whenever the two argmaxes differ, and it
    # needs NO new solve: both terms are already computed per row. The effective band a verdict must
    # absorb is therefore `tight_bound - hs_sup`, not `e_total`.
    tight_bound = float(np.max(hs_per_row + hotter))
    band = float(np.max(hotter))
    if not math.isfinite(band) or not math.isfinite(tight_bound):
        raise SystemExit("the band is not finite; UNRESOLVED rather than a number")
    # Soundness and tightness, both checked rather than argued: the tight bound must dominate the
    # FEM's own certified peak, and must not exceed the loose one.
    if tight_bound < fem_sup - 1e-9:
        raise SystemExit(
            f"the tight bound {tight_bound!r} is below the FEM's certified peak {fem_sup!r}; it is "
            "not a bound and no verdict computed from it means anything"
        )
    if tight_bound > hs_sup + band + 1e-9:
        raise SystemExit(
            f"the tight bound {tight_bound!r} exceeds the loose one {hs_sup + band!r}; the "
            "derivation says it cannot, so one of them is computed wrongly"
        )

    payload = {
        "hotspot_operator": hotspot_path.name, "fem_operator": fem_path.name,
        "capture": capture.name, "span": span,
        "rows": int(hs_rows.shape[0]), "blocks": len(hs_blocks),
        "e_total_k": band,
        "min_u_j_k": float(np.min(hotter)),
        "rows_with_negative_u_j": int(np.count_nonzero(hotter < 0.0)),
        "colder_band_k": float(np.max(colder)),
        "at_nominal_max_k": float(np.max(nominal)),
        "at_nominal_min_k": float(np.min(nominal)),
        "hotspot_nominal_peak_k": float(np.max(hs_rows @ power + hs_ambient)),
        "fem_nominal_peak_k": float(np.max(fem_rows @ power + fem_ambient)),
        "hotspot_certified_peak_k": hs_sup,
        "fem_certified_peak_k": fem_sup,
        "delta_certified_k": fem_sup - hs_sup,
        "loose_bound_k": hs_sup + band,
        "tight_bound_k": tight_bound,
        "effective_band_k": tight_bound - hs_sup,
        "looseness_factor": band / max(tight_bound - hs_sup, 1e-12),
    }
    print(json.dumps(payload, indent=1, sort_keys=True))
    Path(str(fem_path).replace("-cell.npz", "-band.json")).write_text(
        json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")


if __name__ == "__main__":
    main()
