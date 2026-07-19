"""
CertiTherm decision-flip audit (Stage 3 of plan)

Run the chiplet evaluator twice on each design:
  1) Uniform power (current default - chiplet_evaluator uses module-average ptrace)
  2) Spatial power (modified ptrace with hot/cold pattern)

Compare:
  - Peak temperature
  - Feasibility verdict (T <= 348K AND area <= 300mm²)
  - Relative EDYP ratio

For each design, classify:
  - SAFE_BOTH: feasible in both
  - INFEAS_BOTH: infeasible in both
  - UNIFORM_SAFE_SPATIAL_FAIL: feasible uniform, infeasible spatial (decision-flip!)
  - UNIFORM_FAIL_SPATIAL_SAFE: infeasible uniform, feasible spatial (decision-flip!)

A "decision-flip" is when spatial power flips the feasibility verdict vs uniform.
This is the kill gate for CertiTherm: if no decision-flip occurs across realistic
designs and workloads, then spatial power doesn't affect architectural decisions,
and the CertiTherm direction fails.
"""
import os
import sys
import json
import argparse
import subprocess
import tempfile
import csv
import shutil
import numpy as np

sys.path.insert(0, '/home/ynwang/jhn/DSE/ThermoDSE')
sys.path.insert(0, '/home/ynwang/jhn/DSE/CertiTherm/audit')

# Import the spatial power injector
from spatial_power_injection import inject_spatial_power, make_pattern


def parse_peak_temp(steady_file):
    """Parse gcc.steady file for peak temperature."""
    if not os.path.exists(steady_file):
        return None
    max_t = 0.0
    with open(steady_file) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2:
                try:
                    t = float(parts[1])
                    if t > max_t:
                        max_t = t
                except ValueError:
                    pass
    return max_t


def run_hotspot_for_design(sim_path, hotspot_path, run_sh_path):
    """Run HotSpot via the wrapper script, return peak temp from gcc.steady."""
    # Clear old outputs
    steady_file = os.path.join(sim_path, 'outputs', 'gcc.steady')
    if os.path.exists(steady_file):
        os.remove(steady_file)

    # Run the wrapper (matching core/gen_floorplan.py:451 command structure)
    # command list: [shell, config_file, flp_file, ptrace_file, side, path]
    try:
        result = subprocess.run(
            ['bash', run_sh_path,
             os.path.join(sim_path, 'example.config'),
             os.path.join(sim_path, 'floorplan', 'output_3D.flp'),
             os.path.join(sim_path, 'ptrace', 'cores_3D.ptrace'),
             '0.020',
             sim_path],
            check=False, capture_output=True, text=True, timeout=120
        )
        if result.returncode != 0:
            print(f'    HotSpot subprocess failed: returncode={result.returncode}')
            print(f'    stderr: {result.stderr[-200:]}')
    except subprocess.TimeoutExpired:
        return None

    return parse_peak_temp(steady_file)


# Representative sys_info designs to test
# Mix of paper-discovered, our-discovered, and diverse exploration
TEST_DESIGNS = [
    # Paper-discovered (from logs)
    [7, 3, 1, 1, 0.0014, 144, 128, 524288, 144, 128],     # SCBO single paper best
    [6, 2, 6, 2, 0.0005, 128, 256, 4194304, 128, 128],     # TESA non-ideal paper best
    [4, 4, 4, 4, 0.0005, 112, 128, 4194304, 64, 128],      # TESA ideal paper best
    # Our SCBO-discovered
    [5, 4, 1, 2, 0.0005, 208, 128, 1048576, 240, 128],     # Our SCBO 233.27
    [4, 5, 2, 1, 0.0017, 128, 128, 1048576, 112, 224],     # Our SCBO two-stage 195.18
    [6, 3, 6, 3, 0.0005, 112, 128, 4194304, 64, 128],      # Our TESA ideal 296.54
    # Diverse exploration: vary chip count, SA dims, bandwidth
    [8, 8, 1, 1, 0.003, 240, 240, 4194304, 256, 128],      # Max core count
    [2, 2, 1, 1, 0.0005, 64, 64, 524288, 64, 128],         # Min core count
    [3, 3, 3, 3, 0.001, 128, 128, 1048576, 128, 128],     # Square 3x3
    [4, 4, 2, 2, 0.001, 160, 160, 2097152, 128, 128],     # 2x2 cuts, larger SA
    [8, 2, 8, 2, 0.0008, 144, 80, 4194304, 64, 128],       # Wide and flat
    [6, 6, 6, 6, 0.002, 192, 192, 2097152, 192, 128],     # Heavily partitioned
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sim-path', default='/home/ynwang/jhn/DSE/ThermoDSE/tmp')
    ap.add_argument('--hotspot-path', default='/home/ynwang/jhn/DSE/HotSpot')
    ap.add_argument('--output', default='/home/ynwang/jhn/DSE/CertiTherm/results/decision_flip_audit_v1.csv')
    ap.add_argument('--spatial-strength', type=float, default=5.0, help='spatial power peak multiplier')
    ap.add_argument('--mode', default='centered', choices=['centered', 'corner', 'checker', 'random'])
    ap.add_argument('--temp-threshold', type=float, default=348.0)
    ap.add_argument('--area-threshold-m2', type=float, default=3e-4)
    ap.add_argument('--max-designs', type=int, default=len(TEST_DESIGNS))
    args = ap.parse_args()

    run_sh = os.path.join(args.sim_path, 'run.sh')

    designs = TEST_DESIGNS[:args.max_designs]
    print(f"Running CertiTherm decision-flip audit on {len(designs)} designs")
    print(f"  mode={args.mode}, strength={args.spatial_strength}, T<={args.temp_threshold}K")

    rows = []
    for i, sys_info in enumerate(designs):
        xx, yy, cx, cy, ci, hsa, wsa, ubf, nop, dram = sys_info
        print(f"\n[{i+1}/{len(designs)}] sys_info[:4]={sys_info[:4]}")

        # Step 1: Run chiplet_evaluator with this sys_info (uniform power)
        try:
            from core.chiplet_eva import chiplet_evaluator
            ev = chiplet_evaluator(
                hotspot_path=args.hotspot_path,
                sim_path=args.sim_path,
                sys_info=sys_info,
                thermal_map=False,
                baseline1=False, baseline2=False, baseline3=False,
                wkld_idpdt=False,
                clock_freq=1.8e9,
            )
            ev.generate_hardware()
            delay, energy, die_yield = ev.evaluate()
            ev_edyp = energy * delay / die_yield
            ev_area = ev.sys_h * ev.sys_w + ev.IO_die_area_each * 8  # m²
            # Get uniform peak temp from gcc.steady
            unif_peak_t = parse_peak_temp(os.path.join(args.sim_path, 'outputs', 'gcc.steady'))
            if unif_peak_t is None:
                # Run HotSpot manually if not done
                unif_peak_t = run_hotspot_for_design(args.sim_path, args.hotspot_path, run_sh)
            print(f"  uniform: EDYP={ev_edyp:.2f}, T={unif_peak_t:.1f}K, area={ev_area*1e6:.1f}mm²")
        except Exception as e:
            print(f"  uniform: FAILED {e}")
            rows.append({'design_idx': i, 'sys_info': str(sys_info), 'error_uniform': str(e)})
            continue

        # Step 2: Create spatial-power ptrace (backup the uniform one)
        unif_ptrace = os.path.join(args.sim_path, 'ptrace', 'cores_3D.ptrace')
        spatial_ptrace = os.path.join(args.sim_path, 'ptrace', 'cores_3D_spatial.ptrace')
        try:
            inject_spatial_power(
                unif_ptrace, spatial_ptrace,
                cxlen=xx, cylen=yy,
                mode=args.mode, strength=args.spatial_strength, seed=42,
            )
            # Replace uniform with spatial
            shutil.copy(spatial_ptrace, unif_ptrace)
            # Re-run HotSpot
            spatial_peak_t = run_hotspot_for_design(args.sim_path, args.hotspot_path, run_sh)
            # Restore uniform
            shutil.copy(spatial_ptrace + '.bak', unif_ptrace) if os.path.exists(unif_ptrace + '.bak') else None
            if spatial_peak_t is None:
                print(f"  spatial: HotSpot failed")
                rows.append({'design_idx': i, 'sys_info': str(sys_info), 'unif_t': unif_peak_t, 'spatial_t': None})
                continue
            print(f"  spatial: T={spatial_peak_t:.1f}K (delta={spatial_peak_t-unif_peak_t:+.1f}K)")
        except Exception as e:
            print(f"  spatial: FAILED {e}")
            rows.append({'design_idx': i, 'sys_info': str(sys_info), 'unif_t': unif_peak_t, 'error_spatial': str(e)})
            continue

        # Classify
        unif_feas = (ev_area <= args.area_threshold_m2) and (unif_peak_t <= args.temp_threshold)
        spatial_feas = (ev_area <= args.area_threshold_m2) and (spatial_peak_t <= args.temp_threshold)
        flipped = (unif_feas != spatial_feas)
        verdict = 'SAFE_BOTH'
        if flipped:
            verdict = 'UNIFORM_SAFE_SPATIAL_FAIL' if unif_feas else 'UNIFORM_FAIL_SPATIAL_SAFE'
        elif not unif_feas and not spatial_feas:
            verdict = 'INFEAS_BOTH'

        print(f"  verdict: {verdict}")

        rows.append({
            'design_idx': i,
            'sys_info': str(sys_info),
            'unif_edyp': ev_edyp,
            'unif_t_K': unif_peak_t,
            'spatial_t_K': spatial_peak_t,
            'delta_T_K': spatial_peak_t - unif_peak_t,
            'area_mm2': ev_area * 1e6,
            'unif_feasible': unif_feas,
            'spatial_feasible': spatial_feas,
            'flipped': flipped,
            'verdict': verdict,
        })

    # Save
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    keys = list({k for r in rows for k in r.keys()})
    with open(args.output, 'w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=sorted(keys))
        w.writeheader()
        w.writerows(rows)

    # Summary
    print(f"\n=== AUDIT SUMMARY ===")
    print(f"Total designs tested: {len(rows)}")
    print(f"Saved to {args.output}")

    if rows:
        n_flipped = sum(1 for r in rows if r.get('flipped', False))
        n_unif_safe_spatial_fail = sum(1 for r in rows if r.get('verdict') == 'UNIFORM_SAFE_SPATIAL_FAIL')
        n_unif_fail_spatial_safe = sum(1 for r in rows if r.get('verdict') == 'UNIFORM_FAIL_SPATIAL_SAFE')
        n_safe_both = sum(1 for r in rows if r.get('verdict') == 'SAFE_BOTH')
        n_infeas_both = sum(1 for r in rows if r.get('verdict') == 'INFEAS_BOTH')
        print(f"Verdicts:")
        print(f"  SAFE_BOTH:              {n_safe_both}")
        print(f"  INFEAS_BOTH:            {n_infeas_both}")
        print(f"  UNIFORM_SAFE_SPATIAL_FAIL (false-feasible!): {n_unif_safe_spatial_fail}")
        print(f"  UNIFORM_FAIL_SPATIAL_SAFE (false-infeas!): {n_unif_fail_spatial_safe}")
        print(f"  Total flipped:           {n_flipped}/{len(rows)}")

        # Temp delta stats
        deltas = [r.get('delta_T_K', 0) for r in rows if 'delta_T_K' in r]
        if deltas:
            print(f"\nPeak-T delta stats (spatial - uniform):")
            print(f"  Mean:  {np.mean(deltas):+.2f} K")
            print(f"  Max:   {np.max(deltas):+.2f} K")
            print(f"  Min:   {np.min(deltas):+.2f} K")
            print(f"  Std:   {np.std(deltas):.2f} K")


if __name__ == "__main__":
    main()