"""Is the robust-feasible frontier non-empty? Answered on built operators, before spending weeks.

The proposal (T3) is to replace the frozen `0.01 K` band with the MEASURED cross-model discrepancy,
re-run certification, and publish the architectures that stay feasible across the whole band together
with the EDYP price of choosing one. That is the right shape -- a positive deliverable rather than
"everything is uncertain" -- and it eliminates the pipeline's largest correctness risk whether or not
it is published.

**But its premise is testable in minutes and has already failed once.** Budgeting a five-vector
estimate and re-running the registry left 4 of 18 architectures refused and every transformer point
at `beta* = 0` (`docs/BUDGETED_REGISTRY_DOES_NOT_CERTIFY.md`). Since then the honest bound has been
measured at 2.5-5.3x that estimate. So the frontier may be empty, and finding that out costs a few
minutes of arithmetic on operators that already exist rather than 6-8 weeks.

This probe computes, per architecture and workload, on already-built operators:

* the **cross-grid** band -- `sup_p [T_grid64(p) - T_grid128(p)]` over the power polytope, per row;
* the **cross-model** band -- the same between `block` and `grid128`, which is the family's internal
  disagreement and is equally invisible to a linearity contract;
* whether the design is still certifiable with that band folded in one-sidedly;
* the frontier: architectures feasible under EVERY band tried;
* the EDYP price of the cheapest robust architecture against the EDYP-optimal one.

No HotSpot runs. Everything below reads saved operators and captures.

NON-CLAIM diagnostic. Writes one JSON.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/robustness/robust_frontier.py <artifact-root> <out.json> \\
        [package]
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.cross_grid_bound import one_sided_containment_bounds, peak_over_polytope
from CertiTherm.experiments import _power_space, _rows, ROOT
from CertiTherm.frozen_limits import MODEL_ERROR_LIMIT_K, THERMAL_LIMIT_K
from CertiTherm.hotspot import load_family
from CertiTherm.measurements import activity_bounded_power_space, content_upper_bounds

MARGIN_K = 0.05
# The EDYP spread inside which two archived designs are not distinguishable by the evaluator.
# Measured, not assumed: `k0_ranking_margin.py` puts the top of ThermoDSE's space at a 0.5-5 %
# plateau, and the rank-2 gaps in the submitted archive are 2.5-6.2 %.
EDYP_INDISTINGUISHABLE_FRACTION = 0.05


BACKEND_PARITY_TOL_K_PER_W = 1e-6


class _Operator:
    """Model ids, response rows and ambients, without claiming certified-family membership.

    `load_family` builds a `ThermalFamily`, whose `__post_init__` requires a finite non-negative
    `error_k` per model. The FEM reference deliberately carries NaN there -- its discretisation,
    source placement and boundary realisation are all unmeasured, and a zero would let the
    containment machinery treat an unconverged operator as a certified reference. That refusal is
    correct and is left in place; what changes is that the FEM is not pushed through the certified
    schema at all. It is a reference for MEASURING a band, not a member of the family being
    certified, and loading it as one would assert a membership it does not have.
    """

    __slots__ = ("model_ids", "response_k_per_w", "ambient_k")

    def __init__(self, model_ids, response_k_per_w, ambient_k):
        self.model_ids = tuple(model_ids)
        self.response_k_per_w = response_k_per_w
        self.ambient_k = ambient_k


def _load_operator(path: Path):
    """Either a certified family NPZ or a bare reference operator, as ids/rows/ambients/blocks."""

    with np.load(path, allow_pickle=False) as data:
        return (
            _Operator(
                [str(m) for m in data["model_ids"]],
                np.asarray(data["response_k_per_w"], dtype=float),
                np.asarray(data["ambient_k"], dtype=float),
            ),
            tuple(str(b) for b in data["block_ids"]),
        )


def _merged_models(families):
    """`model_id -> (response rows, ambient)` across several families over the SAME block list.

    The finer operators are built separately (`fine_operator.py`, on GPU) because `grid256` and
    `grid512` are far too slow to sit in the pipeline's registry. Merging them here is only sound if
    every family resolves the same blocks in the same ORDER -- a band between two response matrices
    whose columns mean different blocks is a difference between different quantities and would look
    entirely plausible. The caller checks the block tuples; this function assumes it.

    **A model present in two families is a free cross-backend check, so it is not silently
    deduplicated.** The registry's `grid128` was built on the CPU and the fine operator's `grid128`
    on the GPU, from the same config and floorplan. If they disagree, then every band computed
    against `grid128` is partly measuring the backend rather than the grid -- which is exactly the
    false-hit direction `GpuSelection` exists to prevent, and it would be invisible if the first
    entry simply won. Returns the merged mapping and the observed disagreements.
    """

    merged, parity = {}, {}
    for family in families:
        for index, model_id in enumerate(family.model_ids):
            rows = family.response_k_per_w[index]
            ambient = family.ambient_k[index]
            if model_id in merged:
                previous_rows, previous_ambient = merged[model_id]
                gap = max(
                    float(np.max(np.abs(previous_rows - rows))),
                    float(np.max(np.abs(previous_ambient - ambient))),
                )
                parity[model_id] = max(parity.get(model_id, 0.0), gap)
                if not math.isfinite(gap) or gap > BACKEND_PARITY_TOL_K_PER_W:
                    raise SystemExit(
                        f"{model_id} differs by {gap:.3e} between the operators supplied for it; "
                        "a band computed against it would be measuring the backend, not the grid"
                    )
                continue
            merged[model_id] = (rows, ambient)
    return merged, parity


def main() -> None:
    artifacts = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    package = sys.argv[3] if len(sys.argv) > 3 else "default"
    # Several directories, because the fine operators are built in overlapping pairs -- `128,256`
    # and `256,512` -- so that each build re-measures the grid the previous one ended on. The
    # overlap is deliberate: it is a second independent run of the same model, and `_merged_models`
    # turns it into a parity check instead of a silent preference for whichever loaded first.
    fine_dirs = [Path(p) for p in sys.argv[5].split(",")] if len(sys.argv) > 5 else []

    # RESTRICTED TO ONE SPLIT, because a held-out architecture that was deliberately not run is not
    # an unresolved one. Counting the nine frozen architectures as UNRESOLVED reported a protocol
    # boundary as a failure, and would have made every certified fraction here look like 3 of 12.
    split = sys.argv[6] if len(sys.argv) > 6 else "dev"
    registry = _rows(ROOT / "experiments" / "architectures.tsv")
    if split not in {row["split"] for row in registry}:
        raise SystemExit(f"unknown split {split!r}")
    architectures = [row["architecture_id"] for row in registry if row["split"] == split]
    # Missing inputs are counted, never silently dropped: skipping a candidate whose operator
    # failed to build removes exactly the hard cases from the denominator and inflates the
    # certified fraction. They are UNRESOLVED, which is a verdict this project already has.
    rows, skipped = [], []
    for arch in architectures:
        operator = artifacts / "operators" / f"{arch}--{package}.npz"
        if not operator.exists():
            skipped.append(f"{arch}: no operator")
            continue
        family, blocks = load_family(operator)
        extra = []
        for fine_dir in fine_dirs:
            fine_path = fine_dir / f"{arch}--{package}.npz"
            if not fine_path.exists():
                continue
            fine_family, fine_blocks = _load_operator(fine_path)
            if tuple(fine_blocks) != tuple(blocks):
                raise SystemExit(
                    f"{arch}: the fine operator in {fine_dir} resolves a different block list than "
                    "the registry operator, so no band between them is a grid difference"
                )
            extra.append(fine_family)
        models, backend_parity = _merged_models([family] + extra)
        ids = list(models)
        for workload in ("resnet50", "transformer"):
            capture = artifacts / "captures" / f"{workload}--{arch}.npz"
            if not capture.exists():
                skipped.append(f"{arch}/{workload}: no capture")
                continue
            _space, capture_blocks, placed, _flp = _power_space(capture)
            if capture_blocks != blocks:
                raise SystemExit(f"{arch}/{workload}: block identity mismatch")
            power = np.asarray(placed, dtype=float)
            total = float(np.sum(power))
            # THE UNCERTAINTY SET IS THE DOMINANT TERM, not the models. Measured: the polytope
            # supremum runs 4-133x the value at the nominal map, because `content_upper_bounds`
            # hands every block its whole content class's power -- a deliberately permissive set
            # whose adversarial vertices no workload phase produces. So the frontier is computed
            # under BOTH: the registered coarse set, and the activity-bounded set the project
            # already provides for exactly this objection.
            sets = {"coarse_content_bound": (np.zeros(len(blocks)), content_upper_bounds(blocks, power))}
            for span in (float(sys.argv[4]) if len(sys.argv) > 4 else 0.30,):
                space = activity_bounded_power_space(blocks, power, activity_span=span)
                sets["activity_span_%.2f" % span] = (
                    np.asarray(space.lower_w, dtype=float), np.asarray(space.upper_w, dtype=float)
                )

            with np.load(capture, allow_pickle=False) as data:
                edyp = (
                    float(data["latency_ms"]) * float(data["energy_mj"]) / float(data["die_yield"])
                )

            bands, nominal_bands = {}, {}
            for (set_name, (lower, upper)), (name, coarse_id, fine_id) in [
                (s_item, p_item)
                for s_item in sets.items()
                for p_item in (
                    ("cross_grid_64_128", "grid64-avg", "grid128-avg"),
                    ("cross_model_block_128", "block", "grid128-avg"),
                    # The refinement tail. `docs/ROBUST_FEASIBLE_FRONTIER.md` listed this as not
                    # included and noted it would ADD to the bands: `grid128` is treated as the
                    # reference and is not itself converged, so every band measured against it was a
                    # lower bound. Present only when a fine operator directory is supplied.
                    ("cross_grid_128_256", "grid128-avg", "grid256-avg"),
                    ("cross_grid_256_512", "grid256-avg", "grid512-avg"),
                    # The COMPOSED tail, measured directly rather than summed: the
                    # sum of successive one-sided suprema is attained at possibly
                    # different vertices and is therefore loose.
                    ("refinement_tail_128_512", "grid128-avg", "grid512-avg"),
                    # MODEL FORM, at last. Every pair above is within HotSpot and therefore
                    # bounds only its discretisation; the whole family can agree while being
                    # wrong together. `fem-dolfinx` solves the same PDE with an independent 3-D
                    # discretisation, and because steady conduction is linear in the power
                    # vector its operator is affine too -- so the SAME bound applies unchanged.
                    ("model_form_block_fem", "block", "fem-dolfinx"),
                    ("model_form_grid512_fem", "grid512-avg", "fem-dolfinx"),
                )
            ]:
                if coarse_id not in ids or fine_id not in ids:
                    continue
                key = f"{set_name}|{name}"
                coarse_rows, coarse_ambient = models[coarse_id]
                fine_rows, fine_ambient = models[fine_id]
                hotter, _colder = one_sided_containment_bounds(
                    coarse_rows, fine_rows, coarse_ambient, fine_ambient, lower, upper, total,
                )
                # The supremum is attained at an adversarial vertex of a deliberately permissive
                # set -- `content_upper_bounds` gives every block its whole content class's power.
                # Reporting it alone would pass off a worst case as a typical disagreement, so the
                # value AT THE NOMINAL MAP is reported beside it and the gap between them is the
                # honest measure of how much of the band is the uncertainty set rather than the
                # models.
                # SAME DIRECTION AS THE POLYTOPE BOUND. `one_sided_containment_bounds` returns
                # `sup(T_fine - T_coarse)`; this column used to compute `coarse - fine`, so the two
                # numbers reported side by side were opposite containment directions and their ratio
                # compared different quantities. Peer review caught it; the ratio quoted in
                # `docs/ROBUST_FEASIBLE_FRONTIER.md` was derived from the wrong sign.
                at_nominal = float(np.max(
                    (fine_rows - coarse_rows) @ power + (fine_ambient - coarse_ambient)
                ))
                bands[key] = float(np.max(hotter))
                nominal_bands[key] = at_nominal

            # THE CERTIFICATE IS OVER THE POLYTOPE, not at the nominal map. The earlier version
            # evaluated the peak at `power` and then subtracted a polytope-wide DISCREPANCY
            # supremum from the resulting headroom, which certifies nothing: a different admissible
            # map can be hotter under the very same reference operator, and the two maxima are taken
            # over different things. Peer review named this as the largest logical gap. The fix is
            # the same greedy fill, so it is exact and costs one pass per row.
            reference_id = next(
                (m for m in ("grid512-avg", "grid256-avg", "grid128-avg") if m in ids), ids[0]
            )
            reference_rows, reference_ambient = models[reference_id]
            nominal_peak = float(np.max(reference_rows @ power + reference_ambient))
            worst_peaks = {
                set_name: peak_over_polytope(
                    reference_rows, reference_ambient, lower, upper, total
                )
                for set_name, (lower, upper) in sets.items()
            }
            # Headroom is reported against the nominal map for continuity with the earlier tables,
            # but FEASIBILITY below is decided on `worst_peaks`, which is the certifying quantity.
            headroom = THERMAL_LIMIT_K - MARGIN_K - nominal_peak
            # THE ERROR LEDGER, kept as separate terms rather than one replacing another. The frozen
            # 0.01 K measures direct HotSpot replay against impulse superposition -- a linearisation
            # residual of ONE operator. The cross-grid and cross-model bands measure differences
            # BETWEEN affine operators. Re-anchoring by deleting the first would leave superposition
            # unbudgeted, so the certificate keeps it and adds nothing else: the reference operator
            # is what is being certified, so there is no source-to-reference correction to make.
            certified_slack = {
                set_name: THERMAL_LIMIT_K - MARGIN_K - MODEL_ERROR_LIMIT_K - peak
                for set_name, peak in worst_peaks.items()
            }
            # What certifying from a COARSE model instead would have cost. This is a different
            # question from the one above -- it is the price of a cheap thermal surrogate, not the
            # feasibility of the design -- and it is reported as such rather than folded in.
            surrogate_slack = {
                set_name: certified_slack[set_name]
                - max(b for k, b in bands.items() if k.startswith(set_name + "|"))
                for set_name in sets
                if any(k.startswith(set_name + "|") for k in bands)
            }
            rows.append({
                "architecture": arch, "workload": workload,
                "reference_model_id": reference_id,
                "backend_parity_k_per_w": backend_parity,
                "nominal_peak_k": nominal_peak,
                "worst_peak_over_polytope_k": worst_peaks,
                "headroom_to_limit_at_nominal_map_k": headroom,
                "linearisation_band_k": MODEL_ERROR_LIMIT_K,
                "bands_k": bands,
                "bands_at_nominal_map_k": nominal_bands,
                "certified_slack_k": certified_slack,
                "certified": {n: bool(s > 0.0) for n, s in certified_slack.items()},
                "surrogate_slack_k": surrogate_slack,
                "certified_from_coarse_model": {n: bool(s > 0.0) for n, s in surrogate_slack.items()},
                "edyp": edyp,
            })
            print(
                "%-8s %-12s nominal %7.3f K  %s"
                % (
                    arch, workload, nominal_peak,
                    "  ".join(
                        "%s: sup_P %7.3f K -> %s" % (
                            name.replace("coarse_content_bound", "content").replace("activity_span_", "act"),
                            worst_peaks[name],
                            "CERTIFIED" if certified_slack[name] > 0 else "refused",
                        )
                        for name in sorted(sets)
                    ),
                ),
                flush=True,
            )

    by_workload = {}
    for row in rows:
        by_workload.setdefault(row["workload"], []).append(row)
    prices = {}
    for workload, group in sorted(by_workload.items()):
        # THE NOMINAL OPTIMUM IS A SET, not a point. `k0_ranking_margin` measures the top of
        # ThermoDSE's space as a 0.5-5 % EDYP plateau, inside the evaluator's own error band, so a
        # price quoted against a single argmin can move because of evaluator noise rather than
        # robustness. The denominator is therefore the whole indistinguishable set, which turns the
        # price into a RANGE: cheapest-robust against the best and against the worst member.
        best_value = min(r["edyp"] for r in group)
        indistinguishable = [
            r for r in group if r["edyp"] <= best_value * (1.0 + EDYP_INDISTINGUISHABLE_FRACTION)
        ]
        worst_indistinguishable = max(r["edyp"] for r in indistinguishable)
        per_set = {}
        for set_name in sorted(group[0]["certified_slack_k"]):
            certified = [r for r in group if r["certified_slack_k"][set_name] > 0.0]
            entry = {
                "certified_count": len(certified), "point_count": len(group),
                "unresolved_count": len(skipped),
                "cheapest_certified": (
                    min(certified, key=lambda r: r["edyp"])["architecture"] if certified else None
                ),
                "price_vs_best_pct": (
                    100.0 * (min(r["edyp"] for r in certified) / best_value - 1.0)
                    if certified else None
                ),
                "price_vs_worst_indistinguishable_pct": (
                    100.0 * (min(r["edyp"] for r in certified) / worst_indistinguishable - 1.0)
                    if certified else None
                ),
            }
            per_set[set_name] = entry
            print(
                "  %-12s under %-22s: %d of %d certified%s"
                % (
                    workload, set_name, len(certified), len(group),
                    (
                        ", cheapest %s at %+.1f%% to %+.1f%% EDYP"
                        % (
                            entry["cheapest_certified"],
                            entry["price_vs_worst_indistinguishable_pct"],
                            entry["price_vs_best_pct"],
                        )
                        if certified else "  -- EMPTY"
                    ),
                ),
                flush=True,
            )
        prices[workload] = {
            "edyp_best": best_value,
            "edyp_indistinguishable_set": [r["architecture"] for r in indistinguishable],
            "edyp_indistinguishable_fraction": EDYP_INDISTINGUISHABLE_FRACTION,
            "per_uncertainty_set": per_set,
        }

    if skipped:
        print(
            "\nUNRESOLVED (missing operator or capture, counted, not silently dropped): %s"
            % ", ".join(skipped),
            flush=True,
        )
    out_path.write_text(json.dumps(
        {"points": rows, "unresolved": skipped, "price_of_robustness": prices}, indent=1
    ))


if __name__ == "__main__":
    main()
