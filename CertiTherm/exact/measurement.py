"""
Experimental post-G2 measurement-selection prototype (not a passed gate).

For a NON_IDENTIFIABLE design (lower_d ≤ T_budget < upper_d), the algorithm
selects the cheapest measurement m(p) that, when added to the observation
set, makes the resulting decision identifiable.

A measurement m(p) = w^T p for weight vector w partitions P_d into
equivalence classes. Adding m(p) to the observation restricts P_d to
P_d' = {p ∈ P_d : w^T p = m*}.

Cost model: 1 cost unit = 1 sensor / 1 measurement channel.
- Total mtxu power: 1 unit
- Total ubuf power: 1 unit
- Per-chip power (16 chips): 16 units
- Per-block power (186 blocks): 186 units
- Full design snapshot: highest cost (complete)

Algorithm:
1. For a given NON_IDENTIFIABLE design, evaluate each candidate measurement
2. For each: compute P_d' (post-measurement admissible set) and re-evaluate
3. Report whether either registered witness value resolves the current pair.

This is not a proof that every possible measurement outcome resolves the
query, nor a minimum-information theorem. It is retained as a G4 prototype and
must not be used until the physical cross-candidate G2 gate passes.
"""
import json
import argparse
import os
import numpy as np

from decide import decide, decide_simple


# Type-major component types (from spatial_power_injection._COMPONENT_TYPES)
_COMPONENT_TYPES = (
    'mtxu', 'vecu', 'ubuf', 'ibuf', 'obuf', 'io_0', 'io_1', 'io_2', 'io_3'
)


def get_block_indices_by_type(blocks, block_type):
    """Return indices of blocks that start with block_type (e.g., 'mtxu')."""
    if block_type == 'io':
        # io_0, io_1, etc. are separate types
        return None
    return [i for i, b in enumerate(blocks) if b.startswith(block_type + '_') or
            b == block_type or b.startswith(block_type)]


def get_block_indices_by_pattern(blocks, pattern_fn):
    """Return indices where pattern_fn(block_name) is True."""
    return [i for i, b in enumerate(blocks) if pattern_fn(b)]


def compute_decision_bounds(R, T_ambient, observation, block_names,
                              T_budget=348.0, A_budget_m2=3e-4, area_mm2=None):
    """
    Compute (lower_d, upper_d, status) for a given observation.
    observation: dict with per_block_power, per_block_upper, per_block_lower
    Returns: (lower_d, upper_d, status, witness_safe, witness_infeas)
    """
    res = decide(
        sys_info=[1, 1], R=R, T_ambient=T_ambient,
        block_names=block_names, observation=observation,
        T_budget=T_budget, A_budget_m2=A_budget_m2, area_mm2=area_mm2,
    )
    return res


def get_candidate_measurements(blocks, n_chips_per_side=4):
    """
    Enumerate candidate measurements with their cost.

    Each measurement is defined by a weight vector w (one entry per block).
    Cost = sum(w != 0), the number of non-zero weights (= number of sensor
    channels needed).

    Returns: list of (name, weight_vector, cost) tuples
    """
    n = len(blocks)
    measurements = []

    # 1. Type-major component sums (9 measurements, one per component type)
    for t in _COMPONENT_TYPES:
        w = np.zeros(n)
        for i, b in enumerate(blocks):
            if b.startswith(t + '_') or b == t:
                w[i] = 1.0
        if w.sum() > 0:
            measurements.append((f'total_{t}', w, int(w.sum())))

    # 2. Per-chip power (n_chips cells)
    # Each chip has mtxu, vecu, ubuf, ibuf, obuf, io_0/1/2/3 = 9 components
    # Total per-chip power = sum of 9 components for that chip
    for chip_idx in range(n_chips_per_side * n_chips_per_side):
        w = np.zeros(n)
        for comp_type in _COMPONENT_TYPES:
            target = f'{comp_type}_{chip_idx}'
            if target in blocks:
                w[blocks.index(target)] = 1.0
        if w.sum() > 0:
            measurements.append((f'chip_{chip_idx}_total', w, int(w.sum())))

    # 3. Per-type per-chip (finer)
    for chip_idx in range(n_chips_per_side * n_chips_per_side):
        for comp_type in _COMPONENT_TYPES:
            target = f'{comp_type}_{chip_idx}'
            if target in blocks:
                w = np.zeros(n)
                w[blocks.index(target)] = 1.0
                measurements.append((f'chip{chip_idx}_{comp_type}', w, 1))

    # 4. Interposer + edges (cheap, 5 blocks)
    w = np.zeros(n)
    for i, b in enumerate(blocks):
        if b.startswith('interposer') or b.startswith('eblk'):
            w[i] = 1.0
    if w.sum() > 0:
        measurements.append(('interposer_eblk', w, int(w.sum())))

    # 5. Single-type aggregate (1 measurement each)
    # mtxu, ubuf, ibuf, obuf, vecu each
    for t in ['mtxu', 'ubuf', 'ibuf', 'obuf', 'vecu']:
        w = np.zeros(n)
        for i, b in enumerate(blocks):
            if b.startswith(t + '_'):
                w[i] = 1.0
        if w.sum() > 0:
            measurements.append((f'all_{t}_chips', w, 1))

    return measurements


def select_cheapest_resolving_measurement(
    R, T_ambient, blocks, observation, T_budget=348.0, A_budget_m2=3e-4, area_mm2=None,
    n_chips_per_side=4, verbose=False,
):
    """
    Find the cheapest candidate measurement that, when added to the
    observation, makes the decision identifiable (CERTIFIED_SAFE or
    CERTIFIED_INFEASIBLE).
    """
    # 1. Compute current decision
    current = decide(
        sys_info=[1, 1], R=R, T_ambient=T_ambient,
        block_names=blocks, observation=observation,
        T_budget=T_budget, A_budget_m2=A_budget_m2, area_mm2=area_mm2,
    )
    if current['status'] != 'NON_IDENTIFIABLE':
        return {
            'current_status': current['status'],
            'no_measurement_needed': True,
            'cheapest_measurement': None,
            'cost': 0,
            'new_status': current['status'],
            'current_lower': current.get('lower_d'),
            'current_upper': current.get('upper_d'),
        }

    # 2. Enumerate candidate measurements
    candidates = get_candidate_measurements(blocks, n_chips_per_side)
    candidates.sort(key=lambda x: x[2])  # sort by cost

    # 3. For each candidate, simulate adding the measurement
    n = len(blocks)
    current_lower = current['lower_d']
    current_upper = current['upper_d']

    if verbose:
        print(f"\n=== G3 measurement selection ===")
        print(f"  Current status: NON_IDENTIFIABLE (lower={current_lower:.1f}K, upper={current_upper:.1f}K)")
        print(f"  T_budget: {T_budget:.1f}K")
        print(f"  Available: {len(observation['per_block_power'])} power values, u={observation['per_block_upper'][:3]}...")
        print(f"  Testing {len(candidates)} candidate measurements...")

    resolved = []
    for name, w, cost in candidates:
        # Simulate measurement: w^T p = m* (use witness_safe value)
        # If we measure m* = w^T p_safe, then P_d' restricts to {p : w^T p = m*}
        if current.get('witness_safe') is None or current.get('witness_infeas') is None:
            continue
        m_star_safe = float(np.dot(w, current['witness_safe']))
        m_star_infeas = float(np.dot(w, current['witness_infeas']))

        # If both witness pairs give same m*, measurement doesn't help
        if abs(m_star_safe - m_star_infeas) < 1e-3:
            continue

        # Restrict P_d: add constraint w^T p = m* (assume worst case: m* = m_star_safe,
        # the user can observe m* and rule out the infeas witness)
        obs_restricted = {
            'per_block_power': observation['per_block_power'],
            'per_block_upper': observation['per_block_upper'].copy(),
            'per_block_lower': observation['per_block_lower'].copy(),
        }
        # Add the new equality constraint via augmented A_eq / b_eq
        # For simplicity, the decide() function uses sum=observation.sum() as A_eq
        # We need a different way to incorporate w^T p = m*
        # Simplest: encode it as a tighter per-block range (project to constraint)
        # For witness-safe projection: m* safe means w^T p = m_star_safe
        # For witness-infeas projection: m* infeas means w^T p = m_star_infeas
        # We test BOTH possibilities (oracle picks m* best for it)

        # Test with m_star_safe (the witness_safe T is valid, so p_safe satisfies)
        obs_after = obs_restricted.copy()
        obs_after['measurement_w_p'] = (w, m_star_safe)
        res_safe = decide_with_extra_measurement(
            R, T_ambient, blocks, obs_after, T_budget, A_budget_m2, area_mm2,
        )
        # Test with m_star_infeas
        obs_after2 = obs_restricted.copy()
        obs_after2['measurement_w_p'] = (w, m_star_infeas)
        res_infeas = decide_with_extra_measurement(
            R, T_ambient, blocks, obs_after2, T_budget, A_budget_m2, area_mm2,
        )

        # If EITHER measurement makes decision identifiable, the measurement is useful
        statuses = [res_safe['status'], res_infeas['status']]
        if verbose and cost <= 20:
            print(f"  cost={cost:3d} {name:35s} -> safe_obs: {res_safe['status']:<22} infeas_obs: {res_infeas['status']}")

        if 'CERTIFIED' in res_safe['status'] or 'CERTIFIED' in res_infeas['status']:
            resolved.append({
                'name': name,
                'cost': cost,
                'res_after_safe_measurement': res_safe,
                'res_after_infeas_measurement': res_infeas,
            })

    resolved.sort(key=lambda x: x['cost'])

    return {
        'current_status': current['status'],
        'no_measurement_needed': False,
        'current_lower': current_lower,
        'current_upper': current_upper,
        'T_budget': T_budget,
        'candidates_tested': len(candidates),
        'resolving_measurements_count': len(resolved),
        'cheapest_measurement': resolved[0] if resolved else None,
        'all_resolving': resolved[:5] if resolved else [],  # top 5 cheapest
    }


def decide_with_extra_measurement(R, T_ambient, blocks, observation, T_budget,
                                     A_budget_m2=3e-4, area_mm2=None):
    """
    Like decide() but with an extra linear equality constraint w^T p = m*.
    This restricts the admissible set P_d further.
    """
    n = np.asarray(R).shape[0]
    restricted = dict(observation)
    measurement = restricted.pop('measurement_w_p', None)

    if 'A_eq' in restricted or 'b_eq' in restricted:
        if 'A_eq' not in restricted or 'b_eq' not in restricted:
            return {
                'status': 'UNRESOLVED',
                'reason': 'UNRESOLVED_INVALID_INPUT',
                'detail': 'A_eq and b_eq must be supplied together',
            }
        A_eq = np.asarray(restricted['A_eq'], dtype=float)
        b_eq = np.asarray(restricted['b_eq'], dtype=float)
    elif 'per_block_power' in restricted:
        powers = np.asarray(restricted['per_block_power'], dtype=float)
        A_eq = np.ones((1, n), dtype=float)
        b_eq = np.array([float(np.sum(powers))], dtype=float)
    else:
        return {
            'status': 'UNRESOLVED',
            'reason': 'UNRESOLVED_INVALID_INPUT',
            'detail': 'an obtainable equality observation is required',
        }

    if measurement is not None:
        try:
            w_extra, measured_power = measurement
            w_extra = np.asarray(w_extra, dtype=float).reshape(1, -1)
            A_eq = np.vstack([A_eq, w_extra])
            b_eq = np.concatenate([b_eq, [float(measured_power)]])
        except (TypeError, ValueError) as exc:
            return {
                'status': 'UNRESOLVED',
                'reason': 'UNRESOLVED_INVALID_INPUT',
                'detail': str(exc),
            }

    restricted['A_eq'] = A_eq
    restricted['b_eq'] = b_eq
    return decide(
        sys_info=[1, 1],
        R=R,
        T_ambient=T_ambient,
        observation=restricted,
        block_names=blocks,
        T_budget=T_budget,
        A_budget_m2=A_budget_m2,
        area_mm2=area_mm2,
    )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--R-matrix', default='/home/ynwang/jhn/DSE/CertiTherm/exact/R_design_4x4.npy')
    ap.add_argument('--R-meta', default='/home/ynwang/jhn/DSE/CertiTherm/exact/R_design_4x4_meta.json')
    ap.add_argument('--ptrace', default='/home/ynwang/jhn/DSE/ThermoDSE/tmp/ptrace/cores_3D.ptrace')
    ap.add_argument('--content-factor', type=float, default=1.5)
    ap.add_argument('--T-budget', type=float, default=348.0)
    ap.add_argument('--output', default='/home/ynwang/jhn/DSE/CertiTherm/results/g3_measurement_selection.json')
    args = ap.parse_args()

    R = np.load(args.R_matrix)
    with open(args.R_meta) as f:
        meta = json.load(f)
    T_amb = meta['T_ambient']
    block_names = meta['blocks']

    # Get ptrace as observation
    with open(args.ptrace) as f:
        header = f.readline().strip().split('\t')
        values = [float(x) for x in f.readline().strip().split('\t')]

    observation = {
        'per_block_power': values,
        'per_block_upper': [args.content_factor * v for v in values],
        'per_block_lower': [0.0] * len(values),
    }

    # Get area
    from core.chiplet_eva import chiplet_evaluator
    sys_info = meta['sys_info']
    ev = chiplet_evaluator(
        hotspot_path='/home/ynwang/jhn/DSE/HotSpot',
        sim_path='/home/ynwang/jhn/DSE/ThermoDSE/tmp',
        sys_info=sys_info, thermal_map=False,
        baseline1=False, baseline2=False, baseline3=False,
        wkld_idpdt=False, clock_freq=1.8e9,
    )
    ev.generate_hardware()
    ev.evaluate()
    area_mm2 = (ev.sys_h * ev.sys_w + ev.IO_die_area_each * 8) * 1e6

    print(f"=" * 80)
    print(f"  CertiTherm G3: Measurement Selection")
    print(f"=" * 80)
    print(f"  Design: {sys_info[:4]}")
    print(f"  T_budget: {args.T_budget}K, Content factor: {args.content_factor}")
    print(f"  T_uniform: 341.3K (from prior evaluation)")

    res = select_cheapest_resolving_measurement(
        R, T_amb, block_names, observation,
        T_budget=args.T_budget, A_budget_m2=3e-4, area_mm2=area_mm2,
        n_chips_per_side=4, verbose=True,
    )

    print(f"\n=== G3 RESULT ===")
    print(f"  Current status: {res['current_status']}")
    print(f"  Resolving measurements found: {res['resolving_measurements_count']}")
    if res.get('cheapest_measurement'):
        m = res['cheapest_measurement']
        print(f"  CHEAPEST: cost={m['cost']} channels, name={m['name']}")
        print(f"    after measurement (safe obs): {m['res_after_safe_measurement']['status']}")
        print(f"    after measurement (infeas obs): {m['res_after_infeas_measurement']['status']}")
    else:
        print(f"  No measurement resolves the ambiguity")

    # Save
    os.makedirs(os.path.dirname(args.output), exist_ok=True)
    # Strip non-serializable items
    def _clean(d):
        if isinstance(d, dict):
            return {k: _clean(v) for k, v in d.items()
                    if k not in ('witness_safe', 'witness_infeas')}
        if isinstance(d, list):
            return [_clean(x) for x in d[:5]]
        return d
    with open(args.output, 'w') as f:
        json.dump(_clean(res), f, indent=2)
    print(f"\nSaved to {args.output}")


if __name__ == "__main__":
    main()
