"""tau*: the uniform total-power under-prediction that makes a design thermally infeasible.

Peer review: the activity-bounded set fixes the workload total exactly, so it excludes systematic
power under-prediction -- the most thermally dangerous direction and the commonest DSE-stage model
error. This is that direction on its own, with no redistribution at all.
"""
import sys, json
sys.path.insert(0, ".")
from pathlib import Path
import numpy as np
from CertiTherm.experiments import _power_space
from CertiTherm.hotspot import load_family
from CertiTherm.thermal_constraints import reject_cell_rows

A = Path("/data/ziheng/experiments/certitherm-v3-dev-final-c9c42ec/output")
STAR = json.load(open("/data/ziheng/certicheck/sstar.json"))
print("%-8s %-12s %8s %9s %8s %9s %9s" % (
    "arch","workload","peak K","rise K","raw hdrm","tau*","S*"))
out=[]
for wl in ("resnet50","transformer"):
    for arch in ("arch_a","arch_b","arch_c"):
        _p, blocks, placed, _f = _power_space(A/"captures"/("%s--%s.npz"%(wl,arch)))
        fam,_ = load_family(A/"operators"/("%s--default.npz"%arch))
        rows, floors = reject_cell_rows(fam, 0.05)
        temps = fam.response_k_per_w @ placed + fam.ambient_k[:, :, None][:, :, 0]
        # tau* per cell, minimised: the first cell to reach its floor under uniform scaling
        amb = fam.ambient_k
        best = None
        for m in range(rows.shape[0]):
            mm, qq = divmod(m, fam.response_k_per_w.shape[1])
            rise = float(fam.response_k_per_w[mm, qq] @ placed)
            if rise <= 0: continue
            t = (float(floors[m]) - rise) / rise
            best = t if best is None else min(best, t)
        r=[x for x in STAR if x["arch"]==arch and x["workload"]==wl and x["package"]=="default"][0]
        peak=float(temps.max()); raw=(330.0-peak)/(peak-float(amb.min()))
        print("%-8s %-12s %8.3f %9.3f %8.1f%% %8.1f%% %9.3f" % (
            arch, wl, peak, peak-float(amb.min()), raw*100, best*100, r["s_star"]))
        out.append((arch,wl,peak,best,r["s_star"]))
print()
for wl in ("resnet50","transformer"):
    g=sorted([o for o in out if o[1]==wl], key=lambda o:o[3])
    print("  %-12s tau* order (worst first): %s" % (wl, " < ".join("%s(%.1f%%)"%(o[0],o[3]*100) for o in g)))
