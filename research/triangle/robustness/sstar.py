"""Critical activity span S*: how much per-block power-model uncertainty a thermal
feasibility decision tolerates before the limit becomes reachable at all."""
import sys, json, itertools
sys.path.insert(0, ".")
from pathlib import Path
import numpy as np
from scipy.optimize import linprog
from CertiTherm.experiments import _power_space
from CertiTherm.hotspot import load_family
from CertiTherm.measurements import activity_bounded_power_space
from CertiTherm.thermal_constraints import reject_cell_rows

A = Path("/data/ziheng/experiments/certitherm-v3-dev-final-c9c42ec/output")

def margin(blocks, placed, rows, floors, span):
    p = activity_bounded_power_space(blocks, placed, activity_span=span)
    best = -1e9
    for i in range(rows.shape[0]):
        r = linprog(-rows[i], A_ub=p.a_ub if p.a_ub.size else None,
                    b_ub=p.b_ub if p.b_ub.size else None, A_eq=p.a_eq, b_eq=p.b_eq,
                    bounds=tuple(zip(p.lower_w, p.upper_w)), method="highs")
        if r.status == 0:
            best = max(best, -r.fun - float(floors[i]))
    return best

out = []
for arch, pkg, wl in itertools.product(("arch_a","arch_b","arch_c"),
                                       ("default","standard","enhanced"),
                                       ("resnet50","transformer")):
    pol0, blocks, placed, _ = _power_space(A / "captures" / ("%s--%s.npz" % (wl, arch)))
    fam, _ = load_family(A / "operators" / ("%s--%s.npz" % (arch, pkg)))
    rows, floors = reject_cell_rows(fam, 0.05)
    peak = float((fam.response_k_per_w @ placed + fam.ambient_k[:, :, None][:, :, 0]).max())
    lo, hi = 0.05, 40.0
    if margin(blocks, placed, rows, floors, hi) < 0:
        star = float("inf")
    else:
        for _ in range(18):                      # bisection to ~1e-4 relative
            mid = 0.5 * (lo + hi)
            if margin(blocks, placed, rows, floors, mid) > 0: hi = mid
            else: lo = mid
        star = hi
    out.append({"arch": arch, "package": pkg, "workload": wl,
                "nominal_peak_k": peak, "s_star": star})
    print("%-9s %-9s %-12s peak %7.3f K   S* %8.3f" % (arch, pkg, wl, peak, star), flush=True)

json.dump(out, open("/data/ziheng/certicheck/sstar.json", "w"), indent=1)

print("\n=== ranking inversions: lower nominal peak but LOWER S* (worse robustness) ===")
flips = 0
for a, b in itertools.combinations(out, 2):
    if a["workload"] != b["workload"] or a["package"] != b["package"]:
        continue
    if (a["nominal_peak_k"] < b["nominal_peak_k"]) != (a["s_star"] > b["s_star"]):
        flips += 1
        print("  %s vs %s  (%s/%s): peak %.3f vs %.3f  |  S* %.3f vs %.3f" % (
            a["arch"], b["arch"], a["package"], a["workload"],
            a["nominal_peak_k"], b["nominal_peak_k"], a["s_star"], b["s_star"]))
print("  inversions: %d" % flips)
