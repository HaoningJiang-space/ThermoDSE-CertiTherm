"""The yield price of thermal robustness, from the floorplan and the registered yield model."""
import sys, json
sys.path.insert(0, ".")
from pathlib import Path
import numpy as np
from CertiTherm.experiments import _power_space

A = Path("/data/ziheng/experiments/certitherm-v3-dev-final-c9c42ec/output")
D0, ALPHA = 0.08, 10          # ThermoDSE/core/gen_hw_setting.py, 14 nm node

def yield_of(area_cm2):
    return (1.0 + area_cm2 * D0 / ALPHA) ** (-ALPHA)

CUTS = {"arch_a": 1, "arch_b": 2, "arch_c": 4}     # cut_x * cut_y from architectures.tsv
STAR = json.load(open("/data/ziheng/certicheck/sstar.json"))

print("%-8s %6s %11s %11s %8s %8s %9s %11s" % (
    "arch", "dies", "total cm2", "per-die cm2", "yield", "margin", "leverage", "dY per K"))
for arch in ("arch_a", "arch_b", "arch_c"):
    _pol, blocks, _placed, flp = _power_space(A / "captures" / ("resnet50--%s.npz" % arch))
    total_m2 = 0.0
    for line in str(flp).splitlines():
        f = line.split()
        if len(f) < 5 or f[0].startswith("#"):
            continue
        total_m2 += float(f[1]) * float(f[2])          # width * height, metres
    total_cm2 = total_m2 * 1e4
    k = CUTS[arch]
    per_die = total_cm2 / k
    y = yield_of(per_die)
    rec = [r for r in STAR if r["arch"] == arch and r["workload"] == "resnet50"
           and r["package"] == "default"][0]
    margin = 330.05 - rec["nominal_peak_k"]
    lev = margin / rec["s_star"]
    # marginal yield lost per extra cm2, converted to "per Kelvin of margin" using the
    # first-order thermal-area relation dT/dA ~= -T_rise/A (power density scales as 1/A)
    dY_dA = -ALPHA * (D0 / ALPHA) * (1.0 + per_die * D0 / ALPHA) ** (-ALPHA - 1)
    rise = rec["nominal_peak_k"] - 300.0
    dT_dA = -rise / total_cm2
    print("%-8s %6d %11.3f %11.3f %8.4f %8.3f %9.3f %11.5f" % (
        arch, k, total_cm2, per_die, y, margin, lev, dY_dA / dT_dA))
print()
print("  dY per K = yield given up per Kelvin of nominal thermal margin bought by area.")
print("  Positive means margin costs yield; the exchange rate is what DSE trades at.")
