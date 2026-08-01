"""Judge `archive-census-v1` against its preregistered X and Y. Reads only built artifacts.

The certificate, the uncertainty set, the reference, the denominator and the thresholds are all
fixed by `docs/ARCHIVE_CENSUS_PREREGISTRATION.md`, frozen before any archive design was run. This
script computes them and prints PASS or FAIL. It introduces no choice that document does not make.

**Which EDYP.** The price `Y` is measured on the ARCHIVE's reported EDYP, not on this pipeline's
re-derived one. That is not a decision taken here: the preregistration fixed `Y = 30 %` by reference
to archive ranks ("rank 32 is +25.7 %, rank 48 is +32.9 %"), so the quantity was already pinned. The
re-derived EDYP is reported alongside as a secondary observation, because the two are on different
scales and reporting only one would invite them to be confused.

NON-CLAIM label does not apply: this is the census verdict for the frozen protocol.

Usage (on moe-server, from the repo root):
    .venv/bin/python research/triangle/robustness/census_certify.py <census-dir> <out.json>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, ".")

from CertiTherm.cross_grid_bound import one_sided_containment_bounds, peak_over_polytope
from CertiTherm.experiments import _power_space
from CertiTherm.frozen_limits import MODEL_ERROR_LIMIT_K, THERMAL_LIMIT_K
from CertiTherm.measurements import activity_bounded_power_space

MARGIN_K = 0.05
PRIMARY_SPAN = 0.30
CURVE_SPANS = (0.05, 0.10, 0.20, 0.30, 0.50, 0.80, 1.20)
X_THRESHOLD_PCT = 20.0
Y_THRESHOLD_PCT = 30.0
EDYP_INDISTINGUISHABLE_FRACTION = 0.05
# Fixed by the protocol. Asserted against the manifest rather than taken from it.
DECLARED_DENOMINATOR = 64
# The FEM mesh resolution is NOT fixed by the preregistration -- only the tolerances are -- so it was
# raised after a convergence check showed the band still climbing: on the smallest archive die the
# n=64 mesh gave 0.6093 K against 0.6673 K at n=128 and 0.6905 K at n=192. A coarse mesh UNDERstates
# the band, which makes certification easier, so the correction can only lower X and could never be a
# rescue. `fem192` is the refined build; the coarse one stays on disk as the convergence evidence.
_FEM_DIR = "fem192"
# Fixed by the protocol. Read from the ledger and enforced before an operator is used at all.
_FEM_TOLERANCES = {
    "energy_balance_worst_relative_residual": 1e-6,
    "worst_impulse_power_error_w": 1e-6,
    "zero_solve_offset_from_ambient_k": 1e-6,
}


def _assert_frozen_constants() -> None:
    """The protocol's numbers, checked against what the code actually imports.

    `THERMAL_LIMIT_K` and `MODEL_ERROR_LIMIT_K` were imported and used without ever being compared
    with the values the frozen document names. A later configuration change would then silently
    alter the test the verdict is judged by, and nothing would look wrong.
    """

    frozen = {
        "THERMAL_LIMIT_K": (THERMAL_LIMIT_K, 330.0),
        "MODEL_ERROR_LIMIT_K": (MODEL_ERROR_LIMIT_K, 0.01),
        "MARGIN_K": (MARGIN_K, 0.05),
        "PRIMARY_SPAN": (PRIMARY_SPAN, 0.30),
        "X_THRESHOLD_PCT": (X_THRESHOLD_PCT, 20.0),
        "Y_THRESHOLD_PCT": (Y_THRESHOLD_PCT, 30.0),
    }
    drifted = {k: v for k, (v, expected) in frozen.items() if v != expected}
    if drifted:
        raise SystemExit(
            f"these constants no longer match `archive-census-v1`: {drifted}; the verdict would be "
            "judged against a different test than the one that was frozen"
        )


def _operator(path: Path, model_id: str, blocks):
    with np.load(path, allow_pickle=False) as data:
        ids = [str(m) for m in data["model_ids"]]
        if model_id not in ids:
            raise KeyError(f"{path} has {ids}, not {model_id}")
        if tuple(str(b) for b in data["block_ids"]) != tuple(blocks):
            raise ValueError(f"{path} resolves a different block list than its capture")
        index = ids.index(model_id)
        return (
            np.asarray(data["response_k_per_w"], dtype=float)[index],
            np.asarray(data["ambient_k"], dtype=float)[index],
        )


def main() -> None:
    _assert_frozen_constants()
    census = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    manifest = json.loads((census / "work" / "candidate_set.json").read_text())
    designs = manifest["designs"]
    denominator = manifest["denominator"]
    # THE MANIFEST IS AUTHENTICATED, not just counted. `len(designs) == denominator` alone accepts a
    # truncated or duplicated list under the frozen protocol's name, which would put a verdict on a
    # population nobody declared. Peer review named this; every invariant the protocol fixes is
    # checked here.
    identifiers = [d["architecture_id"] for d in designs]
    problems = []
    if manifest.get("protocol") != "archive-census-v1":
        problems.append(f"protocol is {manifest.get('protocol')!r}")
    if denominator != DECLARED_DENOMINATOR or manifest.get("declared_count") != DECLARED_DENOMINATOR:
        problems.append(f"denominator {denominator} / declared {manifest.get('declared_count')}")
    if len(designs) != denominator:
        problems.append(f"{len(designs)} designs against a denominator of {denominator}")
    if len(set(identifiers)) != len(identifiers):
        problems.append("architecture ids are not unique")
    if len(set(d["sys_info"] for d in designs)) != len(designs):
        problems.append("sys_info values are not unique, so a design is counted twice")
    if identifiers != [f"arxv{i:03d}" for i in range(len(designs))]:
        problems.append("architecture ids are not the declared positional sequence")
    if problems:
        raise SystemExit(
            "the candidate manifest does not satisfy `archive-census-v1`: " + "; ".join(problems)
            + ". No verdict is issued for a population the protocol did not declare."
        )

    rows = []
    for design in designs:
        arch = design["architecture_id"]
        record = {
            "architecture_id": arch, "sys_info": design["sys_info"],
            "edyp_reported": design["edyp_reported"],
            "reported_peak_k": design["reported_peak_k"],
        }
        capture = census / "work" / "captures" / f"resnet50--{arch}.npz"
        try:
            _space, blocks, placed, _flp = _power_space(capture)
            power = np.asarray(placed, dtype=float)
            total = float(np.sum(power))
            reference, reference_ambient = _operator(
                census / "g512" / f"{arch}--default.npz", "grid512-avg", blocks
            )
            fem, fem_ambient = _operator(
                census / _FEM_DIR / f"{arch}--default.npz", "fem-dolfinx", blocks
            )
            # THE PREREGISTERED GATES, CHECKED. The protocol fixes energy balance, per-impulse
            # power error and zero-solve offset at <= 1e-6 each, and the earlier version of this
            # script never read them: a successful `np.load` was treated as compliance, so an
            # invalid operator could produce an ordinary-looking CERTIFIED. Missing diagnostics
            # are a breach, not a pass.
            ledger = json.loads(
                (census / _FEM_DIR / f"{arch}-ledger.json").read_text()
            )
            record["fem_diagnostics"] = {
                key: ledger[key] for key in _FEM_TOLERANCES if key in ledger
            }
            for key, limit in _FEM_TOLERANCES.items():
                if key not in ledger:
                    raise ValueError(f"the FEM ledger does not report {key}")
                value = float(ledger[key])
                # `isfinite` first and separately: `NaN > limit` is False, so one inequality would
                # let a NaN pass the guard and be recorded as compliant. And the lower end is
                # checked too: these are magnitudes, so a negative one means the producer computed
                # something other than what the name says, and `value > limit` would wave it through.
                if not np.isfinite(value) or not 0.0 <= value <= limit:
                    raise ValueError(
                        f"{key} is {value:.3e}, outside [0, {limit:.0e}]"
                    )
            # BIND THE LEDGER TO THIS DESIGN. The ledger sits beside the operator by filename alone,
            # so a stale one from a previous build would pass every tolerance while describing a
            # different solve. The capture name and block count are what it already records.
            if ledger.get("capture") != f"resnet50--{arch}.npz":
                raise ValueError(
                    f"the FEM ledger describes {ledger.get('capture')!r}, not this design's capture"
                )
            if int(ledger.get("blocks", -1)) != len(blocks):
                raise ValueError(
                    f"the FEM ledger reports {ledger.get('blocks')} blocks against {len(blocks)}"
                )
            with np.load(capture, allow_pickle=False) as data:
                record["edyp_rederived"] = (
                    float(data["latency_ms"]) * float(data["energy_mj"]) / float(data["die_yield"])
                )
            record["nominal_peak_k"] = float(np.max(reference @ power + reference_ambient))
            per_span = {}
            for span in CURVE_SPANS:
                space = activity_bounded_power_space(blocks, power, activity_span=span)
                lower = np.asarray(space.lower_w, dtype=float)
                upper = np.asarray(space.upper_w, dtype=float)
                # THE FULL POLYTOPE. The class-total inequalities are part of the declared set;
                # dropping them bounds a LARGER one, which is sound but depresses the certified
                # fraction and inflates the band. Peer review found this before the verdict ran.
                a_ub = np.asarray(space.a_ub, dtype=float)
                b_ub = np.asarray(space.b_ub, dtype=float)
                peak = peak_over_polytope(
                    reference, reference_ambient, lower, upper, total, a_ub, b_ub
                )
                hotter, _colder = one_sided_containment_bounds(
                    reference, fem, reference_ambient, fem_ambient, lower, upper, total, a_ub, b_ub
                )
                band = max(float(np.max(hotter)), 0.0)
                per_span["%.2f" % span] = {
                    "sup_peak_k": peak, "model_form_band_k": band,
                    "slack_k": THERMAL_LIMIT_K - MARGIN_K - MODEL_ERROR_LIMIT_K - peak - band,
                }
            record["per_span"] = per_span
            # `>= 0.0`, because the frozen rule is `<= limit - margin - linearisation`: zero slack
            # certifies. The earlier `> 0.0` was conservative but it was not the preregistered
            # comparison, and inventing an epsilon here would be a second unregistered choice.
            record["status"] = "CERTIFIED" if (
                per_span["%.2f" % PRIMARY_SPAN]["slack_k"] >= 0.0
            ) else "REFUSED"
        except Exception as error:  # noqa: BLE001
            # UNRESOLVED STAYS IN THE DENOMINATOR. A missing or broken operator is exactly a hard
            # case; dropping it would inflate X by removing the designs least likely to certify.
            record["status"] = "UNRESOLVED"
            record["error"] = f"{type(error).__name__}: {error}"[:300]
        rows.append(record)

    certified = [r for r in rows if r["status"] == "CERTIFIED"]
    unresolved = [r for r in rows if r["status"] == "UNRESOLVED"]
    x_pct = 100.0 * len(certified) / denominator

    best_reported = min(d["edyp_reported"] for d in designs)
    indistinguishable = [
        d for d in designs
        if d["edyp_reported"] <= best_reported * (1.0 + EDYP_INDISTINGUISHABLE_FRACTION)
    ]
    worst_indistinguishable = max(d["edyp_reported"] for d in indistinguishable)
    y_pct = (
        100.0 * (min(r["edyp_reported"] for r in certified) / best_reported - 1.0)
        if certified else None
    )
    y_pct_vs_set = (
        100.0 * (min(r["edyp_reported"] for r in certified) / worst_indistinguishable - 1.0)
        if certified else None
    )

    curve = {}
    for span in CURVE_SPANS:
        key = "%.2f" % span
        curve[key] = sum(
            1 for r in rows
            if r["status"] != "UNRESOLVED" and r["per_span"][key]["slack_k"] >= 0.0
        )

    verdict = {
        "protocol": "archive-census-v1",
        "fem_operator_dir": _FEM_DIR,
        "frozen_constants": {
            "thermal_limit_k": THERMAL_LIMIT_K, "linearisation_k": MODEL_ERROR_LIMIT_K,
            "margin_k": MARGIN_K, "primary_span": PRIMARY_SPAN,
        },
        "denominator": denominator,
        "certified": len(certified), "refused": len(rows) - len(certified) - len(unresolved),
        "unresolved": len(unresolved),
        "X_pct": x_pct, "X_threshold_pct": X_THRESHOLD_PCT, "X_passes": bool(x_pct >= X_THRESHOLD_PCT),
        "Y_pct_vs_best": y_pct, "Y_pct_vs_worst_indistinguishable": y_pct_vs_set,
        "Y_threshold_pct": Y_THRESHOLD_PCT,
        "Y_passes": bool(y_pct is not None and y_pct <= Y_THRESHOLD_PCT),
        "cheapest_certified": (
            min(certified, key=lambda r: r["edyp_reported"])["architecture_id"]
            if certified else None
        ),
        "frontier_size_vs_span": curve,
        "points": rows,
    }
    verdict["claim_holds"] = bool(verdict["X_passes"] and verdict["Y_passes"])

    print(
        "archive-census-v1: %d certified, %d refused, %d UNRESOLVED of %d\n"
        "  X = %.1f %% (threshold >= %.1f %%) -> %s\n"
        "  Y = %s (threshold <= %.1f %%) -> %s\n"
        "  frontier size vs span: %s\n"
        "  CLAIM %s"
        % (
            len(certified), verdict["refused"], len(unresolved), denominator,
            x_pct, X_THRESHOLD_PCT, "PASS" if verdict["X_passes"] else "FAIL",
            ("%+.1f %%" % y_pct) if y_pct is not None else "undefined (nothing certified)",
            Y_THRESHOLD_PCT, "PASS" if verdict["Y_passes"] else "FAIL",
            ", ".join(f"{k}:{v}" for k, v in curve.items()),
            "HOLDS" if verdict["claim_holds"] else "FAILS",
        ),
        flush=True,
    )
    out_path.write_text(json.dumps(verdict, indent=1))


if __name__ == "__main__":
    main()
