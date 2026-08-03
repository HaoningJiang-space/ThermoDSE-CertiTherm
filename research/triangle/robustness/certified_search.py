"""Certificate-constrained architecture search: minimise EDYP subject to certifying over an envelope.

## What this is for

`docs/THREE_LEGS_STATUS.md` records that ThermoDSE's own registry designs, certified on the routed
trace over a declared activity envelope, include one that is **refused at its own nominal point**
(`arch_b`/transformer, 329.973 K against a 329.94 K ceiling) and five whose robustness radius is
**0.49 to 1.16** -- they stop certifying once block activity can vary by that fraction. That is half
of the evidence the project needs. The other half is a design that DOES certify at a declared
envelope without paying for it in EDYP, and producing one requires a search whose feasibility test is
the certificate rather than a nominal thermal simulation.

## Why the loop is affordable, and where it is not

Per candidate: one ThermoDSE evaluation (~7 s, unavoidable -- it produces the power vector and the
EDYP terms), one operator (0 s on a library hit, 30-90 s on a miss), one certificate (**12 ms**,
`docs/CERTIFICATE_IN_THE_LOOP.md`). So the certificate is free and the *operator* is the cost, which
is why the library is content-addressed and why the neighbourhood ordering below prefers moves that
are known to leave the floorplan invariant.

**Measured, not assumed, and the first measurement was wrong.** On `arch_a` exactly one field
(`interval`) left the floorplan invariant; on `arch_b` **all ten move it**, `interval` included --
`arch_a` has `cut_x = cut_y = 1`, so it has no inter-chiplet gaps for the interval to space, and the
invariance was that design's artefact. So **no coordinate of this design vector is
geometry-invariant**, the space does not factor, and the library's hit rate on a search over it is
~0. The search reports its measured hit rate rather than claiming one.

## The comparison, and the two ways it could be dishonest

**EDYP is recomputed on both sides from this run's own outputs.** The archive's stored EDYP is a
different quantity -- its ratio to `E*D/Y` over the declared designs is 0.0172-0.0204 and **not
constant**, so it aggregates something this run does not (the search's full workload suite). Mixing
the two would be comparing a number against a different number with the same name.

**The baseline is not re-tuned.** It is ThermoDSE's own design row, evaluated through exactly the
same pipeline as every candidate -- same trace lowering, same operator builder, same certificate.
The only asymmetry permitted is the one under test: the search knows the certificate and ThermoDSE
did not.

## Fail-closed

A candidate is `CERTIFIED`, `REFUTED`, or `UNRESOLVED` (ThermoDSE refused it, the lowering did not
reconcile, the operator would not build). An `UNRESOLVED` candidate is archived with its error and
never treated as either feasible or infeasible, and the count is reported so a search that quietly
lost half its neighbourhood cannot look like a complete one.

NON-CLAIM diagnostic. Usage (moe-server, repo root):
    .venv/bin/python research/triangle/robustness/certified_search.py <outdir> <workload> <seed_arch>
        [span] [budget] [workers]
"""

from __future__ import annotations

import json
import math
import sys
import time
import traceback
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.cell_certificate import certify_cells                        # noqa: E402
from CertiTherm.experiments import ROOT, _rows                               # noqa: E402
from CertiTherm.frozen_limits import MODEL_ERROR_LIMIT_K, THERMAL_LIMIT_K     # noqa: E402
from CertiTherm.measurements import activity_bounded_power_space             # noqa: E402
from CertiTherm.operator_library import OperatorLibrary                      # noqa: E402
from CertiTherm.paths import TEMPLATE                                        # noqa: E402
from CertiTherm.routed_trace import lower_routed_trace                       # noqa: E402
from research.triangle.complete_trace_probe import capture_frozen_inputs      # noqa: E402
from research.triangle.robustness.archive_census import (                     # noqa: E402
    DECLARED_COUNT, FIELDS, architecture_row, candidate_set,
)
from research.triangle.robustness.cell_certificate_run import (               # noqa: E402
    _configure, cell_operator,
)

MARGIN_K = 0.05
CEILING_K = THERMAL_LIMIT_K - MARGIN_K - MODEL_ERROR_LIMIT_K
# NO field leaves the floorplan invariant in general (`geometry_factorisation.py` on `arch_b`), so
# this order buys no library hits and is kept only because it tries the fields that move the power
# map most directly, before those that restructure the chiplet grid.
FIELD_ORDER = ("interval", "ubuf", "nop_bw", "dram_bw", "mtxu_h", "mtxu_w",
               "cut_x", "cut_y", "chiplet_x", "chiplet_y")


def _admissible_values():
    """Per-field value sets drawn from the archive ThermoDSE itself produced.

    The neighbourhood is therefore exactly the space ThermoDSE's own search explored, which is the
    defensible choice: a search allowed to leave that space would be compared against a baseline that
    was never allowed to enter it.
    """
    _distinct, _pool, declared = candidate_set(DECLARED_COUNT)
    values = {name: set() for name in FIELDS}
    for index, (sys_info, record) in enumerate(declared):
        row = architecture_row(index, sys_info, record)
        for name in FIELDS:
            values[name].add(row[name])
    out = {}
    for name, seen in values.items():
        out[name] = sorted(seen, key=lambda v: float(v))
        if not out[name]:
            raise SystemExit(f"{name}: the archive supplies no admissible value")
    return out


def _edyp(energy_mj: float, latency_ms: float, die_yield: float) -> float:
    """`E * D / Y`, ThermoDSE's own objective (`core/chiplet_eva.py:234`), recomputed here."""
    if not all(map(math.isfinite, (energy_mj, latency_ms, die_yield))) or die_yield <= 0.0:
        raise ValueError(f"EDYP undefined for E={energy_mj!r} D={latency_ms!r} Y={die_yield!r}")
    return energy_mj * latency_ms / die_yield


def coordinate_descent(seed, baseline, admissible, score, field_order, budget):
    """First-improvement coordinate descent under a HARD feasibility constraint.

    Separated from the ThermoDSE plumbing so the loop's one load-bearing invariant is testable
    without a simulator: **an uncertified candidate is never carried forward**. A penalised search
    would let an infeasible design become the incumbent whenever its objective was good enough, and
    then report the best objective it saw -- which is how a constrained problem silently turns into
    an unconstrained one. Here `incumbent` starts as the baseline only if the baseline certifies, and
    a trial replaces it only when it both certifies AND strictly improves EDYP.

    `score(arch, tag)` returns a result dict or `None` for UNRESOLVED. Returns
    `(incumbent, current, evaluated)`.
    """

    incumbent = baseline if baseline["status"] == "CERTIFIED" else None
    current = dict(seed)
    spent = 1
    improved = True
    while improved and spent < budget:
        improved = False
        for name in field_order:
            for value in admissible[name]:
                if spent >= budget:
                    break
                if str(current[name]) == str(value):
                    continue
                trial = dict(current)
                trial[name] = value
                spent += 1
                result = score(trial, f"{name}={value}")
                if result is None or result["status"] != "CERTIFIED":
                    continue
                if incumbent is None or result["edyp"] < incumbent["edyp"] - 1e-12:
                    incumbent = result
                    current = trial
                    improved = True
                    break
            if improved:
                break
    return incumbent, current, spent


class Evaluator:
    """One ThermoDSE evaluation, one operator (cached), one certificate."""

    def __init__(self, output: Path, workload_id: str, library: OperatorLibrary,
                 span: float, workers: int):
        self.output = output
        self.workload_id = workload_id
        self.library = library
        self.span = span
        self.workers = workers
        self.packages = {row["package_id"]: row
                         for row in _rows(ROOT / "experiments" / "packages.tsv")}
        self.thermodse_seconds = 0.0
        self.certificate_seconds = 0.0

    def __call__(self, arch: dict, tag: str) -> dict:
        started = time.monotonic()
        frozen = capture_frozen_inputs(self.output / "work" / tag, self.workload_id,
                                       arch["architecture_id"], arch_row=arch)
        routed = lower_routed_trace(
            frozen["core"], floorplan=frozen["augmented"], events=frozen["events"],
            compute_shape=frozen["shape"], chiplet_cuts=frozen["cuts"],
            noc_hop_cost_pj=frozen["noc_hop_cost_pj"], nop_hop_cost_pj=frozen["nop_hop_cost_pj"],
            batch_factor=frozen["batch_factor"],
        )
        self.thermodse_seconds += time.monotonic() - started

        augmented = frozen["augmented"]
        blocks = [str(b) for b in augmented.block_ids]
        durations = np.asarray(routed.trace.durations_s, dtype=float)
        powers = np.asarray(routed.trace.powers_w, dtype=float)
        placed = (powers * durations[:, None]).sum(axis=0) / float(durations.sum())

        work = self.output / "work" / tag
        work.mkdir(parents=True, exist_ok=True)
        floorplan = work / "floorplan.flp"
        floorplan.write_text(augmented.text, encoding="utf-8")
        config = work / "package.config"
        _configure(TEMPLATE / "example.config", config, self.packages[self.library.package_id])

        rows, ambient, hit = self.library.get_or_build(
            augmented.text, blocks,
            lambda: cell_operator(config, floorplan, blocks, self.library.model_id, work,
                                  self.workers),
        )

        started = time.monotonic()
        total = float(placed.sum())
        space = activity_bounded_power_space(blocks, placed, activity_span=self.span)
        cell = certify_cells(
            rows, ambient, ["tool_compatible"] * rows.shape[0], space, total,
            endpoint="tool_compatible", limit_k=THERMAL_LIMIT_K, margin_k=MARGIN_K,
            linearisation_k=MODEL_ERROR_LIMIT_K,
        )
        nominal = float(np.max(rows @ placed + ambient))
        self.certificate_seconds += time.monotonic() - started

        peak = float(cell.worst_case_max_cell_average_k)
        if not (math.isfinite(peak) and math.isfinite(nominal)):
            raise ValueError("the certified or nominal peak is not finite")
        return {
            "architecture_id": arch["architecture_id"], "design": {k: arch[k] for k in FIELDS},
            "blocks": len(blocks), "mean_power_w": total,
            "energy_mj": float(frozen["endpoint_energy_mj"]),
            "latency_ms": float(frozen["endpoint_latency_ms"]),
            "die_yield": float(frozen["die_yield"]),
            "edyp": _edyp(float(frozen["endpoint_energy_mj"]),
                          float(frozen["endpoint_latency_ms"]), float(frozen["die_yield"])),
            "nominal_peak_k": nominal, "certified_peak_k": peak,
            "slack_k": CEILING_K - peak,
            "status": "CERTIFIED" if peak <= CEILING_K else "REFUTED",
            "operator_hit": hit, "span": self.span,
        }


def main() -> None:
    output = Path(sys.argv[1])
    workload_id = sys.argv[2]
    seed_id = sys.argv[3]
    span = float(sys.argv[4]) if len(sys.argv) > 4 else 0.30
    budget = int(sys.argv[5]) if len(sys.argv) > 5 else 40
    workers = int(sys.argv[6]) if len(sys.argv) > 6 else 10
    output.mkdir(parents=True, exist_ok=True)

    seed = dict(next(row for row in _rows(ROOT / "experiments" / "architectures.tsv")
                     if row["architecture_id"] == seed_id))
    library = OperatorLibrary(output / "operators")
    evaluate = Evaluator(output, workload_id, library, span, workers)
    admissible = _admissible_values()

    print(f"seed {seed_id} on {workload_id}, envelope span {span}, budget {budget} candidates, "
          f"ceiling {CEILING_K} K", flush=True)

    evaluated, unresolved = {}, []

    def score(arch: dict, tag: str):
        signature = tuple(arch[name] for name in FIELDS)
        if signature in evaluated:
            return evaluated[signature]
        try:
            result = evaluate(arch, tag)
        except Exception as error:                     # noqa: BLE001 - archived, not swallowed
            unresolved.append({"design": {k: arch[k] for k in FIELDS},
                               "error": f"{type(error).__name__}: {error}",
                               "traceback": traceback.format_exc()[-1200:]})
            print(f"  {tag}: UNRESOLVED {type(error).__name__}: {error}", flush=True)
            evaluated[signature] = None
            return None
        evaluated[signature] = result
        print(f"  {tag}: EDYP {result['edyp']:9.4f}  peak {result['certified_peak_k']:8.3f} "
              f"({result['status']:9s}) nominal {result['nominal_peak_k']:8.3f}  "
              f"{'HIT ' if result['operator_hit'] else 'miss'}", flush=True)
        return result

    baseline = score(seed, "baseline")
    if baseline is None:
        raise SystemExit("the baseline could not be evaluated; there is nothing to compare against")

    incumbent, current, spent = coordinate_descent(
        seed, baseline, admissible, score, FIELD_ORDER, budget)

    library.write_manifest(output / "operator_manifest.json")
    payload = {
        "workload": workload_id, "seed": seed_id, "span": span,
        "ceiling_k": CEILING_K, "budget": budget, "evaluated": spent,
        "unresolved": len(unresolved),
        "baseline": baseline,
        "incumbent": incumbent,
        "edyp_ratio": (incumbent["edyp"] / baseline["edyp"]) if incumbent else None,
        "library": library.stats.as_dict(),
        "thermodse_seconds": evaluate.thermodse_seconds,
        "certificate_seconds": evaluate.certificate_seconds,
        "all": [r for r in evaluated.values() if r is not None],
        "unresolved_detail": unresolved,
    }
    (output / f"certified_search_{workload_id}_{seed_id}.json").write_text(
        json.dumps(payload, indent=1, sort_keys=True), encoding="utf-8")

    print()
    print(f"baseline  {seed_id:<10} EDYP {baseline['edyp']:9.4f}  peak "
          f"{baseline['certified_peak_k']:8.3f}  {baseline['status']}")
    if incumbent is None:
        print("NO CERTIFIED DESIGN FOUND in the neighbourhood searched. That is a refusal, not a "
              "failure to improve: reported so the search cannot pass as having explored a space "
              "that contains one.")
    else:
        print(f"incumbent            EDYP {incumbent['edyp']:9.4f}  peak "
              f"{incumbent['certified_peak_k']:8.3f}  {incumbent['status']}  "
              f"EDYP ratio {incumbent['edyp'] / baseline['edyp']:.4f}")
    print(f"library hits {library.stats.hits}/{library.stats.hits + library.stats.misses} "
          f"({100 * library.stats.hit_rate:.1f} %), certificate {evaluate.certificate_seconds:.3f} s "
          f"total against {evaluate.thermodse_seconds:.0f} s of ThermoDSE and "
          f"{library.stats.build_seconds:.0f} s of operator builds")


if __name__ == "__main__":
    main()
