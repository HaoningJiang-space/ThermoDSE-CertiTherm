import sys, numpy as np
sys.path.insert(0, ".")
from pathlib import Path
from scipy.optimize import linprog
from CertiTherm.experiments import _power_space
from CertiTherm.hotspot import load_family
from CertiTherm.measurements import activity_bounded_power_space
from CertiTherm.thermal_constraints import reject_cell_rows, robust_safe_cell_rows

A = Path("/data/ziheng/experiments/certitherm-v3-dev-final-c9c42ec/output")
pol0, blocks, placed, _ = _power_space(A / "captures" / "resnet50--arch_a.npz")
fam, _ = load_family(A / "operators" / "arch_a--default.npz")
rows, floors = reject_cell_rows(fam, 0.05)
srows, srhs = robust_safe_cell_rows(fam, 0.05)

def peak_over(pol, label):
    best, cell = -1e9, None
    for i in range(rows.shape[0]):
        r = linprog(-rows[i], A_ub=pol.a_ub if pol.a_ub.size else None,
                    b_ub=pol.b_ub if pol.b_ub.size else None,
                    A_eq=pol.a_eq, b_eq=pol.b_eq,
                    bounds=tuple(zip(pol.lower_w, pol.upper_w)), method="highs")
        if r.status == 0 and -r.fun - float(floors[i]) > best:
            best, cell = -r.fun - float(floors[i]), i
    print("  %-34s  max(T) - reject_floor = %+8.3f K   (cell %s)" % (label, best, cell))
    return best

print("placed map peak margin to limit:")
t = fam.response_k_per_w @ placed + fam.ambient_k[..., None][:, :, 0]
print("  placed peak = %.3f K, limit = %.1f K" % (float(t.max()), fam.limit_k))
peak_over(pol0, "registered (coarse) set")
for sp in (1.0, 0.5, 0.25, 0.1):
    peak_over(activity_bounded_power_space(blocks, placed, activity_span=sp), "activity span %.2f" % sp)
print("\n  >0 means some admissible map REJECTS; <0 means the limit is unreachable and")
print("  no SAFE/REJECT collision can exist at all, so a bound of 0 is correct but trivial.")
