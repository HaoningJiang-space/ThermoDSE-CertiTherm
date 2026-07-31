"""Robust-selection regret: does a declared total-power uncertainty change the DSE choice?

Peer review's falsification gate: a ranking flip is not required. A robust-FEASIBILITY disagreement
is enough, and it is what a designer acts on -- the nominal test says PASS, the robust test says
FAIL, and the objective still selects the failing design.
"""
import sys, json
sys.path.insert(0, ".")
from pathlib import Path
import numpy as np
from CertiTherm.experiments import _power_space
from CertiTherm.hotspot import load_family
from CertiTherm.thermal_constraints import reject_cell_rows

A = Path("/data/ziheng/experiments/certitherm-v3-dev-final-c9c42ec/output")
REQS = (0.05, 0.10, 0.20, 0.30)

data = {}
for wl in ("resnet50", "transformer"):
    for arch in ("arch_a", "arch_b", "arch_c"):
        _p, blocks, placed, _f = _power_space(A / "captures" / ("%s--%s.npz" % (wl, arch)))
        fam, _ = load_family(A / "operators" / ("%s--default.npz" % arch))
        rows, floors = reject_cell_rows(fam, 0.05)
        pts = fam.response_k_per_w.shape[1]
        rise = np.array([float(fam.response_k_per_w[m // pts, m % pts] @ placed)
                         for m in range(rows.shape[0])])
        amb = np.array([float(fam.ambient_k[m // pts, m % pts]) for m in range(rows.shape[0])])
        tau = np.where(rise > 0, (np.asarray(floors, float) - rise) / np.where(rise > 0, rise, 1), np.inf)
        with np.load(A / "captures" / ("%s--%s.npz" % (wl, arch)), allow_pickle=False) as d:
            edyp = float(d["latency_ms"]) * float(d["energy_mj"]) / float(d["die_yield"])
        data[(wl, arch)] = {"tau_star": float(tau.min()), "edyp": edyp,
                            "peak": float((rise + amb).max()), "rise": rise, "amb": amb}

for wl in ("resnet50", "transformer"):
    print("== %s ==" % wl)
    g = {a: data[(wl, a)] for a in ("arch_a", "arch_b", "arch_c")}
    nominal = min(g, key=lambda a: g[a]["edyp"])
    print("   nominal (EDYP) choice: %s   tau* %.1f%%   EDYP %.3f" % (
        nominal, g[nominal]["tau_star"] * 100, g[nominal]["edyp"]))
    for req in REQS:
        feasible = [a for a in g if g[a]["tau_star"] >= req]
        robust = min(feasible, key=lambda a: g[a]["edyp"]) if feasible else None
        # worst-case peak at the requirement, per architecture
        wc = {a: float((g[a]["rise"] * (1 + req) + g[a]["amb"]).max()) for a in g}
        tag = "SAME" if robust == nominal else ("CHANGES -> %s" % robust if robust else "NONE FEASIBLE")
        extra = ""
        if robust and robust != nominal:
            extra = "   EDYP cost of robustness %+.1f%%   worst-case regret %+.2f K" % (
                (g[robust]["edyp"] / g[nominal]["edyp"] - 1) * 100, wc[nominal] - wc[robust])
        print("   tau_req %4.0f%%: robustly feasible %-28s selection %s%s" % (
            req * 100, ",".join(sorted(feasible)) or "-", tag, extra))
    print()
