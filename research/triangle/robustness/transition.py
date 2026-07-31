import sys, numpy as np
sys.path.insert(0, ".")
from pathlib import Path
from scipy.optimize import linprog
from CertiTherm.experiments import _power_space
from CertiTherm.hotspot import load_family
from CertiTherm.measurements import activity_bounded_power_space
from CertiTherm.thermal_constraints import reject_cell_rows

A = Path("/data/ziheng/experiments/certitherm-v3-dev-final-c9c42ec/output")
CASES = [("arch_a", "default", "resnet50"), ("arch_b", "default", "resnet50"),
         ("arch_c", "default", "resnet50"), ("arch_a", "default", "transformer")]
SPANS = [0.25, 0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 6.0, 9.0, 14.0]

for arch, pkg, wl in CASES:
    pol0, blocks, placed, _ = _power_space(A / "captures" / ("%s--%s.npz" % (wl, arch)))
    fam, _ = load_family(A / "operators" / ("%s--%s.npz" % (arch, pkg)))
    rows, floors = reject_cell_rows(fam, 0.05)
    peak = float((fam.response_k_per_w @ placed + fam.ambient_k[:, :, None][:, :, 0]).max())
    out = []
    for sp in SPANS:
        p = activity_bounded_power_space(blocks, placed, activity_span=sp)
        best = -1e9
        for i in range(rows.shape[0]):
            r = linprog(-rows[i], A_ub=p.a_ub if p.a_ub.size else None,
                        b_ub=p.b_ub if p.b_ub.size else None, A_eq=p.a_eq, b_eq=p.b_eq,
                        bounds=tuple(zip(p.lower_w, p.upper_w)), method="highs")
            if r.status == 0:
                best = max(best, -r.fun - float(floors[i]))
        out.append((sp, best))
    cross = next((s for s, v in out if v > 0), None)
    print("%s/%s/%s  placed peak %.1f K" % (arch, pkg, wl, peak))
    print("   " + "  ".join("%.2f:%+.1f" % (s, v) for s, v in out))
    print("   REJECT first reachable at span = %s" % (cross if cross else ">14"))
