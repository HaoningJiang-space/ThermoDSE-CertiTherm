"""
CertiTherm Phase A Test: Clean isolated test of sample-based robust DSE.

Avoids state pollution by:
1. Using a fresh tmp directory per test
2. Backing up & restoring the original tmp between designs
3. Waiting for HotSpot subprocess to fully complete before reading steady file
"""
import os
import sys
import json
import shutil
import subprocess
import tempfile
import numpy as np

sys.path.insert(0, '/home/ynwang/jhn/DSE/ThermoDSE')
sys.path.insert(0, '/home/ynwang/jhn/DSE/CertiTherm/audit')

from spatial_power_injection import inject_spatial_power


def setup_test_dir(base_src, dst):
    """Copy base_src to dst for isolated testing, symlink HotSpot in parent dir."""
    if os.path.exists(dst):
        shutil.rmtree(dst)
    shutil.copytree(base_src, dst)
    # The test dir is something like /tmp/certithem_test_xxx
    # The run.sh expects ../../HotSpot/hotspot (from /tmp/certithem_test_xxx)
    # So we need /tmp/HotSpot symlink
    hotspot_link = '/tmp/HotSpot'
    if not os.path.exists(hotspot_link):
        os.symlink('/home/ynwang/jhn/EDA/Open3DBench/OpenROAD-3D/flow/HotSpot', hotspot_link)


def run_hotspot_for_ptrace(sim_path, run_sh_path, ptrace_file):
    """Run HotSpot via run.sh, return peak T or None."""
    steady = os.path.join(sim_path, 'outputs', 'gcc.steady')
    if os.path.exists(steady):
        os.remove(steady)
    try:
        result = subprocess.run(
            ['bash', run_sh_path,
             os.path.join(sim_path, 'example.config'),
             os.path.join(sim_path, 'floorplan', 'output_3D.flp'),
             ptrace_file, '0.020', sim_path],
            check=False, capture_output=True, text=True, timeout=120
        )
    except subprocess.TimeoutExpired:
        return None
    if not os.path.exists(steady):
        return None
    max_t = 0.0
    with open(steady) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2:
                try:
                    t = float(parts[1])
                    if t > max_t:
                        max_t = t
                except ValueError:
                    pass
    return max_t if max_t > 0 else None


def evaluate_robust(sys_info, K, mode, max_strength, base_src):
    """Run one design with K samples, return (T_uniform, T_robust, area)."""
    from core.chiplet_eva import chiplet_evaluator

    # Use a fresh tmp dir for each design
    test_dir = f'/tmp/certithem_test_{os.getpid()}'
    setup_test_dir(base_src, test_dir)
    sim_path = test_dir
    run_sh = os.path.join(sim_path, 'run.sh')

    try:
        # Generate the design
        ev = chiplet_evaluator(
            hotspot_path='/home/ynwang/jhn/DSE/HotSpot',
            sim_path=sim_path,
            sys_info=sys_info,
            thermal_map=False,
            baseline1=False, baseline2=False, baseline3=False,
            wkld_idpdt=False, clock_freq=1.8e9,
        )
        ev.generate_hardware()
        delay, energy, die_yield = ev.evaluate()  # writes aggregated ptrace
        area = ev.sys_h * ev.sys_w + ev.IO_die_area_each * 8

        # Run uniform power
        ptrace = os.path.join(sim_path, 'ptrace', 'cores_3D.ptrace')
        T_uniform = run_hotspot_for_ptrace(sim_path, run_sh, ptrace)

        # Sample K spatial patterns
        xx, yy = sys_info[0], sys_info[1]
        sampled_T = []
        for k in range(K):
            strength = np.random.uniform(0.5 * max_strength, max_strength)
            seed = 42 + k * 17
            spatial_ptrace = os.path.join(sim_path, 'ptrace', f'cores_3D_spatial_k{k}.ptrace')
            inject_spatial_power(
                ptrace, spatial_ptrace,
                cxlen=xx, cylen=yy, mode=mode,
                strength=strength, seed=seed,
            )
            t = run_hotspot_for_ptrace(sim_path, run_sh, spatial_ptrace)
            if t is not None:
                sampled_T.append(t)
        T_robust = max([T_uniform] + sampled_T) if T_uniform else None
        return T_uniform, T_robust, area * 1e6, sampled_T
    finally:
        if os.path.exists(test_dir):
            shutil.rmtree(test_dir)


def main():
    test_designs = [
        [7, 3, 1, 1, 0.0014, 144, 128, 524288, 144, 128],
        [6, 2, 6, 2, 0.0005, 128, 256, 4194304, 128, 128],
        [4, 4, 4, 4, 0.0005, 112, 128, 4194304, 64, 128],  # paper best
        [5, 4, 1, 2, 0.0005, 208, 128, 1048576, 240, 128],
        [4, 5, 2, 1, 0.0017, 128, 128, 1048576, 112, 224],  # our SCBO two-stage best
        [6, 3, 6, 3, 0.0005, 112, 128, 4194304, 64, 128],  # TESA ideal best
        [2, 2, 1, 1, 0.0005, 64, 64, 524288, 64, 128],
        [3, 3, 3, 3, 0.001, 128, 128, 1048576, 128, 128],
    ]
    K = 10
    mode = 'centered'
    max_strength = 5.0
    base_src = '/home/ynwang/jhn/DSE/ThermoDSE/tmp'

    print(f"CertiTherm robust DSE evaluation (K={K}, mode={mode})")
    results = []
    for i, sys_info in enumerate(test_designs):
        import time
        t0 = time.time()
        T_u, T_r, area, samples = evaluate_robust(sys_info, K, mode, max_strength, base_src)
        dt = time.time() - t0
        if T_u is None or T_r is None:
            print(f"[{i+1}/{len(test_designs)}] {sys_info[:4]} FAILED ({dt:.0f}s)")
            continue
        u_f = (T_u <= 348) and (area <= 300)
        r_f = (T_r <= 348) and (area <= 300)
        flip = u_f and not r_f
        print(f"[{i+1}/{len(test_designs)}] {sys_info[:4]} T_unif={T_u:.1f} T_robust={T_r:.1f} "
              f"({T_r-T_u:+.1f}K) area={area:.0f}mm² flip={flip} ({dt:.0f}s)")
        results.append({
            'sys_info': sys_info,
            'T_uniform': T_u,
            'T_robust': T_r,
            'T_samples': samples,
            'area_mm2': area,
            'uniform_feasible': u_f,
            'robust_feasible': r_f,
            'flip_with_robust': flip,
        })

    # Summary
    n = len(results)
    n_unif = sum(1 for r in results if r['uniform_feasible'])
    n_robust = sum(1 for r in results if r['robust_feasible'])
    n_flips = sum(1 for r in results if r['flip_with_robust'])
    print(f"\n=== SUMMARY (n={n}, K={K}, mode={mode}) ===")
    print(f"Uniform-feasible: {n_unif}/{n}")
    print(f"Robust-feasible:  {n_robust}/{n}")
    print(f"Flips:            {n_flips}/{n}")
    if results:
        deltas = [r['T_robust'] - r['T_uniform'] for r in results]
        print(f"\nT_robust - T_uniform stats:")
        print(f"  Mean:  {np.mean(deltas):+.2f} K")
        print(f"  Max:   {np.max(deltas):+.2f} K")
        print(f"  Min:   {np.min(deltas):+.2f} K")

    out = '/home/ynwang/jhn/DSE/CertiTherm/results/robust_dse_eval_clean.json'
    with open(out, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved to {out}")


if __name__ == "__main__":
    main()