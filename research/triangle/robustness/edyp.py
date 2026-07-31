import sys, json
sys.path.insert(0, ".")
from pathlib import Path
import numpy as np
A = Path("/data/ziheng/experiments/certitherm-v3-dev-final-c9c42ec/output")
STAR = json.load(open("/data/ziheng/certicheck/sstar.json"))
print("%-8s %-12s %10s %10s %8s %12s %8s %9s" % (
    "arch","workload","latency","energy","yield","EDYP","margin","leverage"))
for wl in ("resnet50","transformer"):
    rows=[]
    for arch in ("arch_a","arch_b","arch_c"):
        with np.load(A/"captures"/("%s--%s.npz"%(wl,arch)), allow_pickle=False) as d:
            lat=float(d["latency_ms"]); en=float(d["energy_mj"]); y=float(d["die_yield"])
        r=[x for x in STAR if x["arch"]==arch and x["workload"]==wl and x["package"]=="default"][0]
        m=330.05-r["nominal_peak_k"]; lev=m/r["s_star"]
        edyp=lat*en/y
        rows.append((arch,lat,en,y,edyp,m,lev))
        print("%-8s %-12s %10.4f %10.4f %8.4f %12.4f %8.3f %9.3f"%(arch,wl,lat,en,y,edyp,m,lev))
    rows.sort(key=lambda r:r[4])
    print("   EDYP order: " + " < ".join(r[0] for r in rows))
    # domination on the (yield, margin, robustness) plane
    for i,a in enumerate(rows):
        for b in rows[i+1:]:
            if b[3]>a[3] and b[5]>a[5] and b[6]<a[6]:
                print("   !! %s is EDYP-preferred over %s, yet %s dominates it on yield (%.4f>%.4f),"
                      " margin (%.3f>%.3f) and leverage (%.3f<%.3f)"%(
                      a[0],b[0],b[0],b[3],a[3],b[5],a[5],b[6],a[6]))
    print()
