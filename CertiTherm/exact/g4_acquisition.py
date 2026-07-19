"""
CertiTherm G4: Minimum-Information Acquisition Policy (OPTIONAL EXTENSION)

This module extends CertiTherm with an active acquisition policy for
NON_IDENTIFIABLE cases. For each registered decision-flipping witness
pair (p_safe, p_infeas), the algorithm searches for the cheapest single
linear measurement m(p) = w^T p that, when added to the observation set,
narrows the admissible set P_d to a region where the decision is identifiable.

Position in the paper:
- This is an OPTIONAL EXTENSION, not the main CertiTherm contribution.
- The main contribution is the decision-certification layer (G1+G2).
- G4 only matters when a decision is NON_IDENTIFIABLE; in that case the
  algorithm picks the cheapest *registered* measurement to resolve it.
- The two witness-conditioned tests (m*_safe and m*_infeas) are a
  *test of the chosen measurement*, not a proof of policy optimality.

The certificate here:
  Given a registered measurement m and registered measurement value m*,
  CertiTherm re-evaluates the LP kernel with the augmented observation.
  If the resulting status is CERTIFIED_SAFE or CERTIFIED_INFEASIBLE,
  the measurement value confirms the decision.
  If the status remains NON_IDENTIFIABLE, the chosen measurement
  does not distinguish the two witnesses and a richer measurement
  is required.
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

from linear_oracle import solve_candidate_bounds


def _measurement_weight(blocks, kind, **kwargs):
    """Construct a weight vector w for one registered measurement type.

    kinds: 'total_<comp>', 'chip_<i>_total', 'chip<i>_<comp>', 'interposer_eblk'.
    Cost: number of non-zero entries (= sensors / channels).
    """
    w = np.zeros(len(blocks))
    if kind.startswith('total_'):
        comp = kind.split('_', 1)[1]
        for i, b in enumerate(blocks):
            if b.startswith(comp + '_') or b == comp:
                w[i] = 1.0
    elif kind.startswith('chip_') and kind.endswith('_total'):
        chip_idx = int(kind.split('_')[1])
        for j, b in enumerate(blocks):
            for comp in ('mtxu', 'vecu', 'ubuf', 'ibuf', 'obuf',
                         'io_0', 'io_1', 'io_2', 'io_3'):
                if b == f'{comp}_{chip_idx}':
                    w[j] = 1.0
                    break
    elif 'total' not in kind:
        # 'chip<i>_<comp>' like 'chip3_ubuf'
        chip_idx = int(kind.split('_')[0][4:])
        comp = kind.split('_')[1]
        target = f'{comp}_{chip_idx}'
        for j, b in enumerate(blocks):
            if b == target:
                w[j] = 1.0
    elif kind == 'interposer_eblk':
        for j, b in enumerate(blocks):
            if b.startswith('interposer') or b.startswith('eblk'):
                w[j] = 1.0
    if w.sum() == 0:
        return None
    return w, int(w.sum())


def _enumerate_measurements(blocks, max_k=3):
    """Yield (name, weight_vector, cost) for registered per-chip-type,
    per-chip, and bulk measurements up to k blocks."""
    yield ('interposer_eblk', *_measurement_weight(blocks, 'interposer_eblk'))
    # Per-component type aggregates
    for comp in ('mtxu', 'vecu', 'ubuf', 'ibuf', 'obuf', 'io_0', 'io_1', 'io_2', 'io_3'):
        res = _measurement_weight(blocks, f'total_{comp}')
        if res is not None:
            yield (f'total_{comp}', *res)
    # Per-chip totals
    n_chips = sum(1 for b in blocks if b.startswith('mtxu_'))
    for chip in range(n_chips):
        res = _measurement_weight(blocks, f'chip_{chip}_total')
        if res is not None:
            yield (f'chip_{chip}_total', *res)
    # Per-chip per-component (cost 1 each)
    for chip in range(n_chips):
        for comp in ('mtxu', 'vecu', 'ubuf', 'ibuf', 'obuf', 'io_0', 'io_1', 'io_2', 'io_3'):
            res = _measurement_weight(blocks, f'chip{chip}_{comp}')
            if res is not None:
                yield (f'chip{chip}_{comp}', *res)


def acquire_cheapest_resolving_measurement(
    R, T_ambient, blocks, observation, T_budget=348.0,
    feasibility_tolerance=1e-7, replay_tolerance_k=1e-6,
    max_k=3,
):
    """
    Run the CertiTherm acquisition policy on a NON_IDENTIFIABLE design.

    For each candidate measurement w (cost = number of sensors), evaluate
    the LP kernel with the augmented observation under both witness
    values.  A candidate is *resolving* if at least one of the two values
    yields a CERTIFIED status.

    Returns a dict with:
      current_status, lower_d, upper_d
      cheapest_resolution: dict with name, cost, blocks, witness_safe_status,
                            witness_infeas_status
      all_resolutions: list of all resolving measurements
    """
    res0 = solve_candidate_bounds(
        response_k_per_w=R,
        ambient_k=np.full(R.shape[0], T_ambient),
        observation=observation,
        block_names=blocks,
        thermal_limit_k=T_budget,
        nonthermal_feasible=True,
        feasibility_tolerance=feasibility_tolerance,
        replay_tolerance_k=replay_tolerance_k,
    )
    if res0.get('status') != 'NON_IDENTIFIABLE':
        return {
            'current_status': res0.get('status'),
            'lower_d': res0.get('lower_d'),
            'upper_d': res0.get('upper_d'),
            'no_measurement_needed': True,
        }
    witness_safe = np.array(res0['witness_safe'])
    witness_infeas = np.array(res0['witness_infeas'])
    n = R.shape[0]
    n_chips = sum(1 for b in blocks if b.startswith('mtxu_'))

    # Build candidate pool: k-block combinations up to max_k.
    # For k=1 use registered single-block measurements.
    # For k>=2 use top-K single-block pairs.
    pool = []  # list of (name, weight, cost)

    for name, w, cost in _enumerate_measurements(blocks):
        if w is None or cost == 0 or cost > max_k:
            continue
        # Project to register two witness values
        m_safe = float(np.dot(w, witness_safe))
        m_infeas = float(np.dot(w, witness_infeas))
        if abs(m_safe - m_infeas) < 1e-3:
            continue
        pool.append((name, w, cost, m_safe, m_infeas))

    # Also include k=2 combinations of top-informative single blocks.
    diffs = np.abs(witness_safe - witness_infeas)
    top_idx = np.argsort(-diffs)[:15]
    for i, j in itertools.combinations(top_idx, 2):
        w = np.zeros(n)
        w[i] = 1.0
        w[j] = 1.0
        m_safe = float(np.dot(w, witness_safe))
        m_infeas = float(np.dot(w, witness_infeas))
        if abs(m_safe - m_infeas) < 1e-3:
            continue
        pool.append((f'pair_{i}_{j}', w, 2, m_safe, m_infeas))

    # Sort by cost
    pool.sort(key=lambda x: x[2])

    # Evaluate each candidate under both witness values
    resolutions = []
    for name, w, cost, m_safe, m_infeas in pool:
        obs_safe = dict(observation)
        obs_safe['per_block_power'] = list(witness_safe)
        obs_infeas = dict(observation)
        obs_infeas['per_block_power'] = list(witness_infeas)
        # Build augmented observation with one extra linear equality
        A_eq_extra = w.reshape(1, -1)
        b_eq_extra = np.array([m_safe])
        for v, m_val in (('safe', m_safe), ('infeas', m_infeas)):
            obs = dict(observation)
            obs['per_block_power'] = list(witness_safe if v == 'safe' else witness_infeas)
            obs['A_eq'] = np.vstack([np.ones((1, n)), A_eq_extra]).tolist()
            obs['b_eq'] = np.array([float(np.sum(witness_safe if v == 'safe' else witness_infeas)), m_val]).tolist()
            try:
                r = solve_candidate_bounds(
                    response_k_per_w=R,
                    ambient_k=np.full(R.shape[0], T_ambient),
                    observation=obs,
                    block_names=blocks,
                    thermal_limit_k=T_budget,
                    nonthermal_feasible=True,
                    feasibility_tolerance=feasibility_tolerance,
                    replay_tolerance_k=replay_tolerance_k,
                )
            except Exception as e:
                continue
            if 'CERTIFIED' in r.get('status', ''):
                setattr(r, f'_{v}_witness_status', r['status'])
                setattr(r, f'_{v}_witness_lower', r.get('lower_d'))
                setattr(r, f'_{v}_witness_upper', r.get('upper_d'))
                resolutions.append((name, cost, v, r))

    if not resolutions:
        return {
            'current_status': 'NON_IDENTIFIABLE',
            'lower_d': res0['lower_d'],
            'upper_d': res0['upper_d'],
            'cheapest_resolution': None,
            'resolutions_found': 0,
            'note': f'no resolving measurement found with cost <= {max_k}',
        }

    # Find cheapest pair that confirms (safe, infeas) both
    safe_results = {n: (c, v, r) for n, c, v, r in resolutions if v == 'safe'}
    infeas_results = {n: (c, v, r) for n, c, v, r in resolutions if v == 'infeas'}
    common = set(safe_results) & set(infeas_results)
    if common:
        # Pick cheapest common
        best = min(common, key=lambda n: safe_results[n][0])
        return {
            'current_status': 'NON_IDENTIFIABLE',
            'lower_d': res0['lower_d'],
            'upper_d': res0['upper_d'],
            'cheapest_resolution': {
                'name': best,
                'cost': safe_results[best][0],
                'witness_safe_status': safe_results[best][2].get('status'),
                'witness_infeas_status': infeas_results[best][2].get('status'),
                'witness_safe_lower': safe_results[best][2].get('lower_d'),
                'witness_safe_upper': safe_results[best][2].get('upper_d'),
                'witness_infeas_lower': infeas_results[best][2].get('lower_d'),
                'witness_infeas_upper': infeas_results[best][2].get('upper_d'),
            },
            'resolutions_found': len(resolutions),
            'both_directions_confirmed': True,
        }

    # Otherwise cheapest single direction
    if resolutions:
        name, cost, v, r = min(resolutions, key=lambda x: x[1])
        return {
            'current_status': 'NON_IDENTIFIABLE',
            'lower_d': res0['lower_d'],
            'upper_d': res0['upper_d'],
            'cheapest_resolution': {
                'name': name, 'cost': cost, 'direction_confirmed': v,
                'status': r.get('status'),
                'lower_d': r.get('lower_d'),
                'upper_d': r.get('upper_d'),
            },
            'resolutions_found': len(resolutions),
            'both_directions_confirmed': False,
        }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--R-matrix', default='/home/ynwang/jhn/DSE/CertiTherm/exact/R_design_4x4.npy')
    ap.add_argument('--R-meta', default='/home/ynwang/jhn/DSE/CertiTherm/exact/R_design_4x4_meta.json')
    ap.add_argument('--ptrace', default='/home/ynwang/jhn/DSE/ThermoDSE/tmp/ptrace/cores_3D.ptrace')
    ap.add_argument('--content-factor', type=float, default=1.5)
    ap.add_argument('--T-budget', type=float, default=348.0)
    ap.add_argument('--max-k', type=int, default=3)
    ap.add_argument('--output', default='/home/ynwang/jhn/DSE/CertiTherm/results/g4_acquisition.json')
    args = ap.parse_args()

    R = np.load(args.R_matrix)
    with open(args.R_meta) as f:
        meta = json.load(f)
    T_amb = meta['T_ambient']
    blocks = meta['blocks']

    with open(args.ptrace) as f:
        header = f.readline().strip().split('\t')
        values = [float(x) for x in f.readline().strip().split('\t')]

    # Match R: truncate or pad
    n = R.shape[0]
    if len(values) >= n:
        values = values[:n]
    else:
        values = values + [0.0] * (n - len(values))

    observation = {
        'per_block_power': values,
        'per_block_upper': [args.content_factor * v for v in values],
        'per_block_lower': [0.0] * n,
    }

    result = acquire_cheapest_resolving_measurement(
        R, T_amb, blocks, observation,
        T_budget=args.T_budget, max_k=args.max_k,
    )

    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    with open(args.output, 'w') as f:
        json.dump(result, f, indent=2, default=str)

    print("=" * 80)
    print("  CertiTherm G4 (OPTIONAL EXTENSION): Acquisition Policy")
    print("=" * 80)
    print(f"  Design: {meta['sys_info']}")
    print(f"  Content factor: {args.content_factor}, T_budget: {args.T_budget}K")
    print()
    print(f"  Current status: {result.get('current_status')}")
    if result.get('lower_d') is not None:
        print(f"  Lower bound: {result['lower_d']:.2f}K")
        print(f"  Upper bound: {result['upper_d']:.2f}K")
    if result.get('no_measurement_needed'):
        print(f"  No measurement needed: {result.get('current_status')}")
    elif result.get('cheapest_resolution'):
        cm = result['cheapest_resolution']
        print(f"  Cheapest resolving measurement:")
        print(f"    name: {cm['name']}")
        print(f"    cost: {cm['cost']} sensor(s)")
        if 'witness_safe_status' in cm:
            print(f"    safe-direction: {cm['witness_safe_status']} (lower={cm['witness_safe_lower']:.2f}, upper={cm['witness_safe_upper']:.2f})")
            print(f"    infeas-direction: {cm['witness_infeas_status']} (lower={cm['witness_infeas_lower']:.2f}, upper={cm['witness_infeas_upper']:.2f})")
        else:
            print(f"    direction: {cm.get('direction_confirmed')}, status: {cm.get('status')}")
    else:
        print(f"  No resolving measurement found")
    print(f"  Saved to {args.output}")


if __name__ == "__main__":
    main()