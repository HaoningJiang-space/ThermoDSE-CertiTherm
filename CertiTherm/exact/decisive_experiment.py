"""Legacy synthetic content-factor pilot.

This script does not implement the frozen cross-candidate G2 query and can
never pass G2.  Claim-grade runs must use ``run_g2_query.py`` with a registered
placed-power bundle.  The pilot remains useful for debugging candidate bounds.
"""
import os
import json
import argparse
from pathlib import Path
import numpy as np

from .decide import decide
from .linear_oracle import canonical_sha256
from .R_matrix import compute_full_R_matrix


REPO_ROOT = Path(__file__).resolve().parents[2]


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


def compute_pumped_observation(
    sim_path,
    hotspot_path,
    sys_info,
    content_factor,
):
    """
    Compute observation z_d for design sys_info.
    Use the actual chiplet_evaluator to get baseline ptrace, then create
    a "content-bound" observation: each block's max is content_factor * uniform.
    """
    from core.chiplet_eva import chiplet_evaluator
    ev = chiplet_evaluator(
        hotspot_path=hotspot_path,
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
    return observation, header, area_mm2, values


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
    ap.add_argument(
        '--output',
        default=str(REPO_ROOT / 'CertiTherm' / 'results' / 'decisive_experiment.json'),
    )
    ap.add_argument('--R-dir', default=str(Path(__file__).resolve().parent))
    ap.add_argument('--sim-path', required=True)
    ap.add_argument(
        '--hotspot-path',
        default=str(REPO_ROOT / '.build' / 'hotspot'),
    )
    ap.add_argument('--T-budget', type=float, default=348.0)
    ap.add_argument('--content-factors', type=float, nargs='+', default=[1.5, 2.0, 3.0])
    args = ap.parse_args()

    run_sh = os.path.join(args.sim_path, 'run.sh')

    print("=" * 80)
    print("  CertiTherm SYNTHETIC CONTENT-FACTOR PILOT")
    print("  This run cannot pass the physical cross-candidate G2 gate")
    print("=" * 80)

    all_results = []
    for design in TEST_DESIGNS:
        print(f"\n--- Design: {design['name']} (sys_info[:4]={design['sys_info'][:4]}) ---")
        try:
            R, meta = compute_R_for_design(
                design['sys_info'], args.sim_path, args.hotspot_path, run_sh, args.R_dir
            )
            if R is None:
                print(f"  R matrix computation FAILED")
                all_results.append({
                    'status': 'UNRESOLVED',
                    'reason': 'R_matrix_computation_failed',
                    'design': design['name'],
                    'evidence_class': 'synthetic_fixture',
                })
                continue

            for cf in args.content_factors:
                print(f"  Content factor = {cf}")
                # Get observation z_d
                obs, header, area_mm2, values = compute_pumped_observation(
                    args.sim_path, args.hotspot_path, design['sys_info'], cf
                )

                # Run LP oracle
                res = decide(
                    sys_info=meta['sys_info'], R=R, T_ambient=meta['T_ambient'],
                    block_names=meta['blocks'],
                    observation=obs,
                    T_budget=args.T_budget, area_mm2=area_mm2,
                )
                # Compute peak T at witness for full replay verification
                p_safe = res.get('witness_safe')
                p_infeas = res.get('witness_infeas')
                T_peak_at_p_safe = None
                T_peak_at_p_infeas = None
                if p_safe is not None:
                    T_at_p_safe = meta['T_ambient'] + R @ np.array(p_safe)
                    T_peak_at_p_safe = float(np.max(T_at_p_safe))
                if p_infeas is not None:
                    T_at_p_infeas = meta['T_ambient'] + R @ np.array(p_infeas)
                    T_peak_at_p_infeas = float(np.max(T_at_p_infeas))
                # Keep complete observations and witnesses in raw pilot output.
                res_clean = dict(res)
                res_clean['witness_safe_T'] = res.get('witness_safe_T')
                res_clean['witness_infeas_T'] = res.get('witness_infeas_T')
                res_clean['design'] = design['name']
                res_clean['content_factor'] = cf
                res_clean['dnn_family'] = design['dnn_family']
                res_clean['arch_family'] = design['arch_family']
                res_clean['sys_info'] = design['sys_info']
                # Stable content digests; Python's process-random hash() is forbidden.
                res_clean['provenance'] = {
                    'R_sha256': canonical_sha256({
                        'shape': list(R.shape),
                        'dtype': str(R.dtype),
                        'values': R,
                    }),
                    'R_shape': list(R.shape),
                    'T_ambient': float(meta['T_ambient']),
                    'observation_sha256': canonical_sha256(obs),
                    'observation_sum': float(sum(values)),
                    'observation_len': len(values),
                    'T_budget': float(args.T_budget),
                    'n_chips_per_side': 4,
                }
                res_clean['observation'] = obs
                res_clean['witness_safe_T_computed'] = T_peak_at_p_safe if p_safe is not None else None
                res_clean['witness_infeas_T_computed'] = T_peak_at_p_infeas if p_infeas is not None else None
                res_clean['record_schema_version'] = 'certitherm.synthetic-candidate-pilot.v1'
                res_clean['evidence_class'] = 'synthetic_fixture'
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
            all_results.append({
                'status': 'UNRESOLVED',
                'reason': 'pilot_exception',
                'detail': str(e),
                'design': design['name'],
                'evidence_class': 'synthetic_fixture',
            })

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
    n_arch = len({r['arch_family'] for r in all_results if 'arch_family' in r})
    n_dnn = len({r['dnn_family'] for r in all_results if 'dnn_family' in r})
    n_cf = len({r['content_factor'] for r in all_results if 'content_factor' in r})

    print(f"  Total runs: {n_total}")
    print(f"  NON_IDENTIFIABLE: {n_non_id} (decision-flip witnesses found)")
    print(f"  CERTIFIED_SAFE:   {n_cert_safe}")
    print(f"  UNRESOLVED:       {n_unresolved}")
    print(f"  Arch families covered: {n_arch}")
    print(f"  DNN families covered:  {n_dnn}")
    print(f"  Content factors:      {n_cf}")

    print(f"\n  G2 GATE: NOT EVALUATED BY THIS SYNTHETIC PILOT")
    print("  Use run_g2_query.py with real placed-power observations and multiple candidates")


if __name__ == "__main__":
    main()
