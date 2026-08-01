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
    census = Path(sys.argv[1])
    out_path = Path(sys.argv[2])
    manifest = json.loads((census / "work" / "candidate_set.json").read_text())
    designs = manifest["designs"]
    denominator = manifest["denominator"]
    if len(designs) != denominator:
        raise SystemExit("the manifest's design list does not match its declared denominator")

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
                census / "fem" / f"{arch}--default.npz", "fem-dolfinx", blocks
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
                peak = peak_over_polytope(reference, reference_ambient, lower, upper, total)
                hotter, _colder = one_sided_containment_bounds(
                    reference, fem, reference_ambient, fem_ambient, lower, upper, total
                )
                band = max(float(np.max(hotter)), 0.0)
                per_span["%.2f" % span] = {
                    "sup_peak_k": peak, "model_form_band_k": band,
                    "slack_k": THERMAL_LIMIT_K - MARGIN_K - MODEL_ERROR_LIMIT_K - peak - band,
                }
            record["per_span"] = per_span
            record["status"] = "CERTIFIED" if (
                per_span["%.2f" % PRIMARY_SPAN]["slack_k"] > 0.0
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
            if r["status"] != "UNRESOLVED" and r["per_span"][key]["slack_k"] > 0.0
        )

    verdict = {
        "protocol": "archive-census-v1",
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
