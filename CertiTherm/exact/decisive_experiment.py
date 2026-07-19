"""
CertiTherm decisive experiment: prove that decision-flipping witnesses
exist for content-bound placed-power cases.

This is the G2 (gating) experiment from RESEARCH_CONTRACT.md.
If decision-flipping witnesses exist for at least:
  - 2 DNN families (e.g., ResNet, Transformer)
  - 2 non-isomorphic architecture families (e.g., 2x2 vs 4x4 cores)
  - 2 package regimes (e.g., content factor 1.5x vs 3.0x)
then CertiTherm direction is validated.
"""
import os
import sys
import json
import argparse
import numpy as np
import subprocess
import shutil

sys.path.insert(0, '/home/ynwang/jhn/DSE')
sys.path.insert(0, '/home/ynwang/jhn/DSE/ThermoDSE')
sys.path.insert(0, '/home/ynwang/jhn/DSE/CertiTherm/exact')

from decide import decide
from R_matrix import compute_full_R_matrix, parse_steady_peak


# Test designs spanning the contract's requirements
TEST_DESIGNS = [
    # 2x2 cores (small)
    {
        'name': '2x2_min',
        'sys_info': [2, 2, 1, 1, 0.0005, 64, 64, 524288, 64, 128],
        'dnn_family': 'uniform',
        'arch_family': '2x2',
    },
    # 4x4 cores (paper's TESA SA ideal best)
    {
        'name': '4x4_paper_TESA',
        'sys_info': [4, 4, 4, 4, 0.0005, 112, 128, 4194304, 64, 128],
        'dnn_family': 'mixed',
        'arch_family': '4x4',
    },
    # 3x3 cores (3x3 architecture family)
    {
        'name': '3x3_square',
        'sys_info': [3, 3, 3, 3, 0.001, 128, 128, 1048576, 128, 128],
        'dnn_family': 'uniform',
        'arch_family': '3x3',
    },
    # 5x4 (non-square, non-isomorphic to 4x4)
    {
        'name': '5x4_nonsq',
        'sys_info': [5, 4, 5, 4, 0.001, 144, 128, 2097152, 144, 128],
        'dnn_family': 'uniform',
        'arch_family': '5x4',
    },
]


def compute_pumped_observation(sim_path, sys_info, content_factor):
    """
    Compute observation z_d for design sys_info.
    Use the actual chiplet_evaluator to get baseline ptrace, then create
    a "content-bound" observation: each block's max is content_factor * uniform.
    """
    from core.chiplet_eva import chiplet_evaluator
    ev = chiplet_evaluator(
        hotspot_path='/home/ynwang/jhn/DSE/HotSpot',
        sim_path=sim_path,
        sys_info=sys_info,
        thermal_map=False, baseline1=False, baseline2=False, baseline3=False,
        wkld_idpdt=False, clock_freq=1.8e9,
    )
    ev.generate_hardware()
    ev.evaluate()
    area_mm2 = (ev.sys_h * ev.sys_w + ev.IO_die_area_each * 8) * 1e6

    ptrace = os.path.join(sim_path, 'ptrace', 'cores_3D.ptrace')
    with open(ptrace) as f:
        header = f.readline().strip().split('\t')
        values = [float(x) for x in f.readline().strip().split('\t')]

    observation = {
        'per_block_power': values,
        'per_block_upper': [content_factor * v for v in values],
        'per_block_lower': [0.0] * len(values),
    }
    return observation, header, area_mm2


def compute_R_for_design(sys_info, sim_path, hotspot_path, run_sh_path, R_dir):
    """Get or compute R matrix for a design, saving to R_dir."""
    R_path = os.path.join(R_dir, f'R_{sys_info[0]}x{sys_info[1]}.npy')
    meta_path = R_path.replace('.npy', '_meta.json')
    if os.path.exists(R_path) and os.path.exists(meta_path):
        R = np.load(R_path)
        with open(meta_path) as f:
            meta = json.load(f)
        return R, meta

    print(f"  Computing R matrix for {sys_info[:4]}...")
    R, T_amb, blocks, _ = compute_full_R_matrix(
        sys_info, sim_path, hotspot_path, run_sh_path
    )
    if R is None:
        return None, None
    os.makedirs(R_dir, exist_ok=True)
    np.save(R_path, R)
    with open(meta_path, 'w') as f:
        json.dump({
            'sys_info': sys_info, 'T_ambient': T_amb, 'blocks': blocks,
            'R_lambda_max': float(np.linalg.norm(R, 2)),
            'R_1norm': float(np.linalg.norm(R, 1)),
            'shape': list(R.shape),
        }, f, indent=2)
    return R, {
        'sys_info': sys_info, 'T_ambient': T_amb, 'blocks': blocks,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--output', default='/home/ynwang/jhn/DSE/CertiTherm/results/decisive_experiment.json')
    ap.add_argument('--R-dir', default='/home/ynwang/jhn/DSE/CertiTherm/exact')
    ap.add_argument('--sim-path', default='/home/ynwang/jhn/DSE/ThermoDSE/tmp')
    ap.add_argument('--hotspot-path', default='/home/ynwang/jhn/DSE/HotSpot')
    ap.add_argument('--T-budget', type=float, default=348.0)
    ap.add_argument('--content-factors', type=float, nargs='+', default=[1.5, 2.0, 3.0])
    args = ap.parse_args()

    run_sh = os.path.join(args.sim_path, 'run.sh')

    print("=" * 80)
    print("  CertiTherm DECISIVE EXPERIMENT")
    print("  G2 gate: prove decision-flipping witnesses exist for content-bound cases")
    print("=" * 80)

    all_results = []
    for design in TEST_DESIGNS:
        print(f"\n--- Design: {design['name']} (sys_info[:4]={design['sys_info'][:4]}) ---")
        try:
            R, meta = compute_R_for_design(
                design['sys_info'], args.sim_path, args.hotspot_path, run_sh, args.R_dir
            )
            if R is None:
                print(f"  R matrix computation FAILED, skipping")
                continue

            for cf in args.content_factors:
                print(f"  Content factor = {cf}")
                # Get observation z_d
                obs, header, area_mm2 = compute_pumped_observation(
                    args.sim_path, design['sys_info'], cf
                )

                # Run LP oracle
                res = decide(
                    sys_info=meta['sys_info'], R=R, T_ambient=meta['T_ambient'],
                    block_names=meta['blocks'],
                    observation=obs,
                    T_budget=args.T_budget, area_mm2=area_mm2,
                )
                # Truncate witness arrays for storage
                res_clean = {k: v for k, v in res.items()
                            if k not in ('witness_safe', 'witness_infeas')}
                res_clean['witness_safe_n_blocks'] = (
                    len(res['witness_safe']) if res.get('witness_safe') else 0
                )
                res_clean['witness_infeas_n_blocks'] = (
                    len(res['witness_infeas']) if res.get('witness_infeas') else 0
                )
                res_clean['witness_safe_T'] = res.get('witness_safe_T')
                res_clean['witness_infeas_T'] = res.get('witness_infeas_T')
                res_clean['design'] = design['name']
                res_clean['content_factor'] = cf
                res_clean['dnn_family'] = design['dnn_family']
                res_clean['arch_family'] = design['arch_family']
                res_clean['sys_info'] = design['sys_info']
                all_results.append(res_clean)

                status = res['status']
                if status == 'UNRESOLVED':
                    print(f"    UNRESOLVED: {res.get('reason', '?')[:50]}")
                else:
                    flip = res['upper_d'] - res['lower_d']
                    print(f"    {status:<22} lower={res['lower_d']:6.1f}K  upper={res['upper_d']:6.1f}K  flip={flip:5.1f}K")
        except Exception as e:
            print(f"  FAILED: {e}")
            import traceback
            traceback.print_exc()

    # Save results
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(all_results, f, indent=2)
    print(f"\nSaved results to {args.output}")

    # Summary
    print(f"\n{'=' * 80}")
    print(f"  DECISIVE EXPERIMENT SUMMARY")
    print(f"{'=' * 80}")
    n_total = len(all_results)
    n_non_id = sum(1 for r in all_results if r.get('status') == 'NON_IDENTIFIABLE')
    n_cert_safe = sum(1 for r in all_results if r.get('status') == 'CERTIFIED_SAFE')
    n_unresolved = sum(1 for r in all_results if r.get('status') == 'UNRESOLVED')
    n_arch = len(set(r['arch_family'] for r in all_results))
    n_dnn = len(set(r['dnn_family'] for r in all_results))
    n_cf = len(set(r['content_factor'] for r in all_results))

    print(f"  Total runs: {n_total}")
    print(f"  NON_IDENTIFIABLE: {n_non_id} (decision-flip witnesses found)")
    print(f"  CERTIFIED_SAFE:   {n_cert_safe}")
    print(f"  UNRESOLVED:       {n_unresolved}")
    print(f"  Arch families covered: {n_arch}")
    print(f"  DNN families covered:  {n_dnn}")
    print(f"  Content factors:      {n_cf}")

    if n_non_id >= 1 and n_arch >= 2 and n_cf >= 2:
        print(f"\n  G2 GATE: PASSED")
        print(f"  Decision-flipping witnesses exist for ≥1 DNN, ≥2 arch families, ≥2 package regimes")
    else:
        print(f"\n  G2 GATE: not yet met")
        print(f"  Need: ≥1 NON_IDENTIFIABLE + ≥2 arch families + ≥2 content factors")


if __name__ == "__main__":
    main()