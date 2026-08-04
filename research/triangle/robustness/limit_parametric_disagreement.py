"""Remove the thermal limit from the premise: for WHICH limits do the two rules disagree?

## The attack this retires

`ADVERSARIAL_SELF_REVIEW.md` A1: `CertiTherm/frozen_limits.py` fixes `THERMAL_LIMIT_K = 330.0` and
gives no source, ThermoDSE's own `348 K` is documented as unsupported, and every verdict in this round
is relative to that number. Move the limit to 335 K and nothing fails.

**The dependence is removable.** For a design with nominal peak `T_nom` and certified peak `T_cert`
over the declared envelope, the incumbent's rule and this one disagree exactly on

    nominal ACCEPTS:   T_nom  <= L
    envelope REFUTES:  T_cert >  L - margin - linearisation
    both:              T_nom  <= L  <  T_cert + margin + linearisation

so the disagreement set is an **interval of limits**, and its width is

    W = (T_cert - T_nom) + margin + linearisation

which contains no `L` at all. The width is the envelope's uplift over the point evaluation plus the
decision margin — a property of the design and the declared envelope, and of nothing else.

So the claim stops being *"at 330 K the incumbent accepts a design we refute"* and becomes
*"**for every design measured there is a band of limits, W wide, on which the incumbent's rule accepts
a design the envelope refutes**"* — with no limit to defend, over every case this project has peaks
for rather than the handful near 330 K.

## Fail-closed

A design whose certified peak is BELOW its nominal peak would make `W` smaller than the margin and is
a contradiction — the envelope contains the nominal point, so the supremum cannot be lower. It is
refused rather than reported, because it would mean the two numbers came from different objects.

NON-CLAIM diagnostic; pure post-processing, no solver.

Usage (moe-server, repo root):
    .venv/bin/python research/triangle/robustness/limit_parametric_disagreement.py <out.json> <dir> ...
"""

from __future__ import annotations

import json
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, ".")

from CertiTherm.frozen_limits import MODEL_ERROR_LIMIT_K, THERMAL_LIMIT_K     # noqa: E402

MARGIN_K = 0.05
SLACK_OFFSET_K = MARGIN_K + MODEL_ERROR_LIMIT_K


def _harvest(root: Path):
    """Every `(case, nominal, certified)` triple this project has written, from any driver."""
    found = []
    for path in sorted(root.rglob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            continue
        records = payload if isinstance(payload, list) else [payload]
        if isinstance(payload, dict) and isinstance(payload.get("all"), list):
            records = payload["all"]
        if isinstance(payload, dict) and isinstance(payload.get("rows"), list):
            records = records + [r for r in payload["rows"] if isinstance(r, dict)]
        for record in records:
            if not isinstance(record, dict):
                continue
            nominal = record.get("nominal_peak_k")
            certified = (record.get("certified_peak_k")
                         or record.get("worst_case_max_cell_average_k")
                         or record.get("thermodse_mapping_certified_k"))
            if certified is None and isinstance(record.get("curve"), list):
                # The radius driver stores the certified peak per span rather than as one field, so
                # the sweep's own span-0.30 point is the comparable number. Reading a DIFFERENT span
                # here would silently mix envelopes across the population, which is why the span is
                # matched exactly rather than taken as "the nearest".
                for point in record["curve"]:
                    if isinstance(point, dict) and abs(float(point.get("span", -1)) - 0.30) < 1e-12:
                        certified = point.get("peak_k")
                        break
            if nominal is None or certified is None:
                continue
            nominal, certified = float(nominal), float(certified)
            if not (math.isfinite(nominal) and math.isfinite(certified)):
                continue
            label = str(record.get("architecture_id") or record.get("case")
                        or record.get("trace") or path.stem)
            found.append((f"{path.parent.name}/{label}", nominal, certified))
    return found


def main() -> None:
    out_path = Path(sys.argv[1])
    roots = [Path(p) for p in sys.argv[2:]]
    if not roots:
        raise SystemExit("no directories given")

    seen, rows = set(), []
    for root in roots:
        for case, nominal, certified in _harvest(root):
            key = (round(nominal, 9), round(certified, 9))
            if key in seen:
                continue
            seen.add(key)
            if certified < nominal - 1e-9:
                raise SystemExit(
                    f"{case}: certified peak {certified!r} is below the nominal {nominal!r}. The "
                    "envelope contains the nominal point, so its supremum cannot be lower; the two "
                    "numbers came from different objects and no width computed from them is valid."
                )
            rows.append({"case": case, "nominal_peak_k": nominal, "certified_peak_k": certified,
                         "uplift_k": certified - nominal,
                         "disagreement_width_k": (certified - nominal) + SLACK_OFFSET_K,
                         "interval_low_k": nominal,
                         "interval_high_k": certified + SLACK_OFFSET_K,
                         "contains_frozen_limit": nominal <= THERMAL_LIMIT_K < certified + SLACK_OFFSET_K})
    if not rows:
        raise SystemExit("no case carried both a nominal and a certified peak")

    widths = [r["disagreement_width_k"] for r in rows]
    uplifts = [r["uplift_k"] for r in rows]
    summary = {
        "cases": len(rows),
        "margin_plus_linearisation_k": SLACK_OFFSET_K,
        "width_min_k": min(widths), "width_median_k": statistics.median(widths),
        "width_max_k": max(widths), "width_mean_k": statistics.fmean(widths),
        "uplift_min_k": min(uplifts), "uplift_median_k": statistics.median(uplifts),
        "uplift_max_k": max(uplifts),
        "cases_with_non_empty_interval": sum(1 for w in widths if w > 0.0),
        "cases_whose_interval_contains_330K": sum(1 for r in rows if r["contains_frozen_limit"]),
        "frozen_limit_k": THERMAL_LIMIT_K,
    }
    print(json.dumps(summary, indent=1, sort_keys=True))
    print()
    print("widest ten:")
    for r in sorted(rows, key=lambda r: -r["disagreement_width_k"])[:10]:
        print("  %-42s W %7.4f K   L in [%9.4f, %9.4f)%s" % (
            r["case"][:42], r["disagreement_width_k"], r["interval_low_k"], r["interval_high_k"],
            "  <- contains 330" if r["contains_frozen_limit"] else ""))
    out_path.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, sort_keys=True),
                        encoding="utf-8")
    print(f"\n-> {out_path}")


if __name__ == "__main__":
    main()
