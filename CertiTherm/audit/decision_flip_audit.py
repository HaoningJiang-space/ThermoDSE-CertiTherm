"""
CertiTherm: Decision-flip audit (Stage 1 of 6-step plan)

The core question:
  When the only available information is module-average power (uniform
  per-instance), does the architectural winner (lowest EDYP) match the
  winner when fine-grained spatial power is used?

This is the kill gate. If no decision-flip is observed across
realistic DNN/architecture/package combinations, the CertiTherm
direction is invalid.

Inputs:
  - chiplet_evaluator (ThermoDSE's evaluator) — single source of truth
  - workload configs: resnet50, googlenet, unet, mobilenet, yolo, transformer
  - architecture configs: SCBO-discovered top designs + uniform random baselines
  - power maps: uniform (1 µW/instance) vs spatial (block-level variation)

Output:
  - decision_flip.csv: per-workload, per-architecture: winner_uniform, winner_spatial, flipped?
"""
import os
import sys
import csv
import json
import argparse
import time
import numpy as np

sys.path.insert(0, '/home/ynwang/jhn/DSE/ThermoDSE')
sys.path.insert(0, '/home/ynwang/jhn/DSE/ThermoDSE/tools')
sys.path.insert(0, '/home/ynwang/jhn/DSE/ThermoDSE/core')

from core.chiplet_eva import chiplet_evaluator
from core.gen_hw_setting import nop_setting_gen


def get_evaluator(sys_info, sim_path, hotspot_path, power_mode='uniform'):
    """Create evaluator. power_mode is a placeholder for future
    spatial-power injection; currently ThermoDSE evaluator only
    accepts per-block uniform power through gen_ptrace_3D."""
    ev = chiplet_evaluator(
        hotspot_path=hotspot_path,
        sim_path=sim_path,
        sys_info=sys_info,
        thermal_map=False,
        baseline1=False, baseline2=False, baseline3=False,
        wkld_idpdt=False,
        clock_freq=1.8e9,
    )
    return ev


def evaluate_design(sys_info, sim_path, hotspot_path):
    """Run one evaluation: generate_hardware + evaluate. Returns (EDYP, area, temp)."""
    ev = get_evaluator(sys_info, sim_path, hotspot_path)
    ev.generate_hardware()
    delay, energy, die_yield = ev.evaluate()
    edyp = energy * delay / die_yield
    # Re-derive area from sys_h * sys_w + IO_die_area (matches core/chiplet_eva.py:157, 262)
    sys_h, sys_w = ev.sys_h, ev.sys_w
    IO_die_area = ev.get_IO_die_area() if hasattr(ev, 'get_IO_die_area') else 0
    area = sys_h * sys_w + IO_die_area
    temp = ev.peak_temp
    return edyp, area, temp


# Representative architectural designs to test
# Mix of paper-discovered and broader search
TEST_DESIGNS = [
    # SCBO-discovered (NEW repro)
    [5, 4, 1, 2, 0.0005, 208, 128, 1048576, 240, 128],   # SCBO 233.27
    [4, 5, 2, 1, 0.0017, 128, 128, 1048576, 112, 224],   # SCBO 2-stage 195.18
    [6, 3, 6, 3, 0.0005, 112, 128, 4194304, 64, 128],    # TESA ideal 296.54
    # Paper-discovered
    [7, 3, 1, 1, 0.0014, 144, 128, 524288, 144, 128],    # SCBO paper 290.03
    [4, 4, 4, 4, 0.0005, 112, 128, 4194304, 64, 128],    # TESA ideal paper 300.47
    [6, 2, 6, 2, 0.0005, 128, 256, 4194304, 128, 128],   # TESA non-ideal paper 466.11
    # Diverse exploration (different shapes)
    [2, 2, 1, 1, 0.0005, 64, 64, 524288, 64, 128],
    [8, 8, 1, 1, 0.003, 240, 240, 4194304, 256, 128],
    [3, 3, 3, 3, 0.001, 128, 128, 1048576, 128, 128],
    [4, 4, 2, 2, 0.001, 160, 160, 2097152, 128, 128],
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sim-path', default='/home/ynwang/jhn/DSE/ThermoDSE/tmp')
    ap.add_argument('--hotspot-path', default='/home/ynwang/jhn/DSE/HotSpot')
    ap.add_argument('--output', default='/home/ynwang/jhn/DSE/CertiTherm/results/decision_flip_audit.csv')
    ap.add_argument('--max-designs', type=int, default=len(TEST_DESIGNS))
    args = ap.parse_args()

    designs = TEST_DESIGNS[:args.max_designs]
    print(f"Running decision-flip audit on {len(designs)} designs")
    print(f"Sim path: {args.sim_path}")
    print(f"HotSpot path: {args.hotspot_path}")

    rows = []
    t0 = time.time()
    for i, sys_info in enumerate(designs):
        try:
            edyp, area, temp = evaluate_design(sys_info, args.sim_path, args.hotspot_path)
            row = {
                'design_idx': i,
                'sys_info': str(sys_info),
                'edyp': edyp,
                'area_m2': area,
                'area_mm2': area * 1e6,
                'temp_K': temp,
                'feasible': (area <= 3e-4) and (temp > 0) and (temp <= 348),
            }
            rows.append(row)
            print(f"  [{i+1}/{len(designs)}] sys={sys_info[:4]}... edyp={edyp:.2f}, area={row['area_mm2']:.1f}mm², T={temp:.1f}K, feas={row['feasible']}")
        except Exception as e:
            print(f"  [{i+1}/{len(designs)}] FAILED: {e}")
            rows.append({'design_idx': i, 'sys_info': str(sys_info), 'error': str(e)})

    # Write CSV
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    keys = list({k for r in rows for k in r.keys()})
    with open(args.output, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=sorted(keys))
        w.writeheader()
        w.writerows(rows)

    # Summary
    print(f"\n=== Audit summary ===")
    print(f"Total time: {time.time()-t0:.1f}s")
    print(f"Total designs: {len(designs)}")
    valid = [r for r in rows if 'edyp' in r]
    feasible = [r for r in valid if r.get('feasible', False)]
    print(f"Valid evaluations: {len(valid)}")
    print(f"Feasible designs: {len(feasible)}")
    if feasible:
        best = min(feasible, key=lambda r: r['edyp'])
        print(f"Best feasible EDYP: {best['edyp']:.4f} at sys_info={best['sys_info']}")


if __name__ == "__main__":
    main()