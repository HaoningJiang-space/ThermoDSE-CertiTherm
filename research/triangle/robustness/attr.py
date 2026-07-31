import sys, numpy as np
sys.path.insert(0, ".")
from pathlib import Path
from scipy.optimize import linprog
from CertiTherm.experiments import _power_space
from CertiTherm.hotspot import load_family
from CertiTherm.measurements import activity_bounded_power_space, coarse_power_space, content_upper_bounds
from CertiTherm.thermal_constraints import reject_cell_rows

A = Path("/data/ziheng/experiments/certitherm-v3-dev-final-c9c42ec/output")
pol0, blocks, placed, _ = _power_space(A / "captures" / "resnet50--arch_a.npz")
fam, _ = load_family(A / "operators" / "arch_a--default.npz")
rows, floors = reject_cell_rows(fam, 0.05)

def worst(pol):
    best = -1e9
    for i in range(rows.shape[0]):
        r = linprog(-rows[i], A_ub=pol.a_ub if pol.a_ub.size else None,
                    b_ub=pol.b_ub if pol.b_ub.size else None,
                    A_eq=pol.a_eq, b_eq=pol.b_eq,
                    bounds=tuple(zip(pol.lower_w, pol.upper_w)), method="highs")
        if r.status == 0:
            best = max(best, -r.fun - float(floors[i]))
    return best

print("  %-52s %10s" % ("uncertainty set", "max(T)-floor"))
print("  %-52s %+10.3f" % ("registered coarse (no class rows, box=content bound)", worst(pol0)))
for sp, cls in ((1.0, False), (1.0, True), (0.5, False), (0.5, True), (0.25, False), (0.25, True)):
    p = activity_bounded_power_space(blocks, placed, activity_span=sp, constrain_class_totals=cls)
    print("  %-52s %+10.3f" % ("span %.2f, class rows %s" % (sp, "ON " if cls else "OFF"), worst(p)))
