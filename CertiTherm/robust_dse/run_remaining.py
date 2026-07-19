#!/usr/bin/env python
"""Run remaining 4 designs for K=8 sample-based robust DSE test."""
import sys, os, json, time
sys.path.insert(0, '/home/ynwang/jhn/DSE/CertiTherm/robust_dse')
sys.path.insert(0, '/home/ynwang/jhn/DSE/ThermoDSE')
sys.path.insert(0, '/home/ynwang/jhn/DSE/CertiTherm/audit')
from sample_worst_case import sample_worst_case_T

sim_path = '/home/ynwang/jhn/DSE/ThermoDSE/tmp'
run_sh = sim_path + '/run.sh'

remaining = [
    [4, 5, 2, 1, 0.0017, 128, 128, 1048576, 112, 224],
    [6, 3, 6, 3, 0.0005, 112, 128, 4194304, 64, 128],
    [2, 2, 1, 1, 0.0005, 64, 64, 524288, 64, 128],
    [3, 3, 3, 3, 0.001, 128, 128, 1048576, 128, 128],
]
results = []
for sys_info in remaining:
    t0 = time.time()
    r = sample_worst_case_T(sys_info, sim_path, '/home/ynwang/jhn/DSE/HotSpot', run_sh, K=8, mode='centered')
    dt = time.time() - t0
    if r['T_robust'] is None:
        print(f'sys_info={sys_info[:4]} FAILED ({dt:.0f}s)', flush=True)
        results.append({'sys_info': sys_info, 'T_uniform': None, 'T_robust': None})
        continue
    u_f = (r['T_uniform'] <= 348) and (r['area_mm2'] <= 300)
    r_f = (r['T_robust'] <= 348) and (r['area_mm2'] <= 300)
    flip = u_f and not r_f
    delta = r['T_robust'] - r['T_uniform']
    print(f'sys_info={sys_info[:4]} T_unif={r["T_uniform"]:.1f}K T_robust={r["T_robust"]:.1f}K delta={delta:+.1f}K flip={flip} ({dt:.0f}s)', flush=True)
    results.append(r)
with open('/home/ynwang/jhn/DSE/CertiTherm/results/robust_dse_K8_remaining.json', 'w') as f:
    json.dump(results, f, indent=2)
print('DONE', flush=True)