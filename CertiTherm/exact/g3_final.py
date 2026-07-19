"""
Legacy post-G2 measurement-search prototype.

For a NON_IDENTIFIABLE design, enumerate candidate measurements
(1-block, 2-block, k-block combinations) and find the cheapest k that
makes the design identifiable (lower_d' > T_budget or upper_d' <= T_budget).

The historical output from this script is invalidated. The current helper now
reuses the corrected LP kernel, but testing only two witness-conditioned
measurement values does not establish a policy or minimum-information claim.
"""
import os
import sys
import json
import argparse
import itertools
import numpy as np

sys.path.insert(0, '/home/ynwang/jhn/DSE')
sys.path.insert(0, '/home/ynwang/jhn/DSE/ThermoDSE')
sys.path.insert(0, '/home/ynwang/jhn/DSE/CertiTherm/exact')

from decide import decide
from measurement import get_candidate_measurements, decide_with_extra_measurement


def select_cheapest_resolving(
    R, T_ambient, blocks, observation, T_budget=348.0,
    max_k=3, n_top_single=10,
):
    """
    Find cheapest k-block measurement that resolves NON_IDENTIFIABLE.
    For k=1: enumerate top-N single blocks.
    For k>1: enumerate pairs/triples of top-N blocks.
    """
    # Current state
    res = decide(
        sys_info=[1, 1], R=R, T_ambient=T_ambient,
        block_names=blocks, observation=observation,
        T_budget=T_budget,
    )
    if res['status'] != 'NON_IDENTIFIABLE':
        return {
            'current_status': res['status'],
            'no_measurement_needed': True,
            'current_lower': res.get('lower_d'),
            'current_upper': res.get('upper_d'),
        }
    witness_safe = np.array(res['witness_safe'])
    witness_infeas = np.array(res['witness_infeas'])
    diff = witness_safe - witness_infeas

    # Top-N most-informative single blocks
    n = R.shape[0]
    top_idx = np.argsort(-np.abs(diff))[:n_top_single]

    resolving = []
    for k in range(1, max_k + 1):
        for combo in itertools.combinations(top_idx, k):
            w = np.zeros(n)
            for i in combo:
                w[i] = 1.0
            m_safe = float(np.dot(w, witness_safe))
            m_infeas = float(np.dot(w, witness_infeas))
            if abs(m_safe - m_infeas) < 1e-3:
                continue
            obs1 = dict(observation)
            obs1['measurement_w_p'] = (w, m_safe)
            r1 = decide_with_extra_measurement(R, T_ambient, blocks, obs1, T_budget=T_budget)
            obs2 = dict(observation)
            obs2['measurement_w_p'] = (w, m_infeas)
            r2 = decide_with_extra_measurement(R, T_ambient, blocks, obs2, T_budget=T_budget)
            if 'CERTIFIED' in r1['status'] or 'CERTIFIED' in r2['status']:
                block_names = [blocks[i] for i in combo]
                resolving.append({
                    'k': k,
                    'cost': k,  # cost = number of blocks = k
                    'blocks': block_names,
                    'r1': {'status': r1['status'], 'lower_d': r1['lower_d'], 'upper_d': r1['upper_d']},
                    'r2': {'status': r2['status'], 'lower_d': r2['lower_d'], 'upper_d': r2['upper_d']},
                })
        if resolving:
            break  # found k-block solution

    if not resolving:
        return {
            'current_status': res['status'],
            'no_measurement_needed': False,
            'current_lower': res['lower_d'],
            'current_upper': res['upper_d'],
            'resolving_measurements': [],
            'note': f'no resolving measurement found in top {n_top_single} blocks with k up to {max_k}',
        }

    resolving.sort(key=lambda x: (x['cost'], -max(x['r1']['lower_d'] if 'CERTIFIED_INFEASIBLE' in x['r1']['status'] else x['r1']['upper_d'], x['r2']['lower_d'] if 'CERTIFIED_INFEASIBLE' in x['r2']['status'] else x['r2']['upper_d'])))
    return {
        'current_status': res['status'],
        'no_measurement_needed': False,
        'current_lower': res['lower_d'],
        'current_upper': res['upper_d'],
        'cheapest_measurement': resolving[0],
        'all_resolving': resolving[:5],
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--R-matrix', default='/home/ynwang/jhn/DSE/CertiTherm/exact/R_design_4x4.npy')
    ap.add_argument('--R-meta', default='/home/ynwang/jhn/DSE/CertiTherm/exact/R_design_4x4_meta.json')
    ap.add_argument('--ptrace', default='/home/ynwang/jhn/DSE/ThermoDSE/tmp/ptrace/cores_3D.ptrace')
    ap.add_argument('--content-factor', type=float, default=1.5)
    ap.add_argument('--T-budget', type=float, default=348.0)
    ap.add_argument('--output', default='/home/ynwang/jhn/DSE/CertiTherm/results/g3_measurement_selection.json')
    ap.add_argument('--max-k', type=int, default=3)
    ap.add_argument('--n-top-single', type=int, default=10)
    args = ap.parse_args()

    R = np.load(args.R_matrix)
    with open(args.R_meta) as f:
        meta = json.load(f)
    T_amb = meta['T_ambient']
    blocks = meta['blocks']

    with open(args.ptrace) as f:
        header = f.readline().strip().split('\t')
        values_full = [float(x) for x in f.readline().strip().split('\t')]
    # Truncate to match R
    values = values_full[:R.shape[0]]

    observation = {
        'per_block_power': values,
        'per_block_upper': [args.content_factor * v for v in values],
        'per_block_lower': [0.0] * len(values),
    }

    result = select_cheapest_resolving(
        R, T_amb, blocks, observation, T_budget=args.T_budget,
        max_k=args.max_k, n_top_single=args.n_top_single,
    )

    # Save
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(result, f, indent=2)

    # Print summary
    print("=" * 80)
    print("  CertiTherm G3: EDA-Specific Next Measurement Selection")
    print("=" * 80)
    print(f"  Design: {meta['sys_info']}")
    print(f"  Content factor: {args.content_factor}")
    print(f"  T_budget: {args.T_budget}K")
    print()
    if result.get('no_measurement_needed'):
        print(f"  NO MEASUREMENT NEEDED: {result['current_status']}")
        print(f"  Current: lower={result.get('current_lower'):.2f}K, upper={result.get('current_upper'):.2f}K")
    else:
        print(f"  Current status: {result['current_status']}")
        print(f"  Current: lower={result['current_lower']:.2f}K, upper={result['current_upper']:.2f}K")
        print(f"  T_budget: {args.T_budget}K (decision-flip in [lower, upper])")
        if result.get('cheapest_measurement'):
            m = result['cheapest_measurement']
            print()
            print(f"  CHEAPEST RESOLVING MEASUREMENT:")
            print(f"    k = {m['k']} block(s) (cost = {m['cost']})")
            print(f"    blocks = {m['blocks']}")
            print(f"    after m*_safe:   {m['r1']}")
            print(f"    after m*_infeas: {m['r2']}")
        if result.get('all_resolving'):
            print()
            print(f"  Top {len(result['all_resolving'])} resolving measurements:")
            for i, m in enumerate(result['all_resolving']):
                print(f"    #{i+1}: k={m['k']} cost={m['cost']} blocks={m['blocks']}")
    print()
    print(f"  Saved to: {args.output}")


if __name__ == "__main__":
    main()
