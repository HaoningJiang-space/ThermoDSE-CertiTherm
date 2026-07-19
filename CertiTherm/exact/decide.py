"""
CertiTherm exact decision-identifiability oracle.

For design d with N blocks, the LP-based oracle computes:
  - lower_d = min_{p ∈ P_d} T_d(p)    (worst-case-safe)
  - upper_d = max_{p ∈ P_d} T_d(p)    (worst-case-unsafe)

where:
  P_d = {p : A_d p = z_d, l_d ≤ p ≤ u_d}    (admissible fine-power set)
  T_d(p) = max_r (T_ambient[r] + R[r,:] · p)    (HotSpot block model)

If lower_d ≤ T_budget < upper_d: design is "non-identifiable" (witness pair exists)
If upper_d ≤ T_budget: design is definitely safe
If lower_d > T_budget: design is definitely infeasible
"""
import argparse
import json
import os
import sys
import numpy as np
from scipy.optimize import linprog

sys.path.insert(0, '/home/ynwang/jhn/DSE')


def decide(sys_info, R, T_ambient, observation, block_names,
           T_budget=348.0, A_budget_m2=3e-4, area_mm2=None):
    """
    Run exact decision-identifiability oracle.

    Args:
      sys_info: 10-element chiplet config (for context only)
      R: N×N thermal resistance matrix (K/W)
      T_ambient: scalar ambient temperature (K)
      observation: dict with per-block observed power (W) OR total module power
      block_names: list of N block names matching R's columns
      T_budget: thermal constraint (K)
      A_budget_m2: area constraint (m²)
      area_mm2: actual area of design (m²)

    Returns: dict with:
      - status: 'CERTIFIED_SAFE' | 'CERTIFIED_INFEASIBLE' | 'NON_IDENTIFIABLE' | 'UNRESOLVED'
      - lower_d: minimum peak T over P_d
      - upper_d: maximum peak T over P_d
      - witness_safe: p_safe ∈ P_d with T_d(p_safe) ≤ T_budget
      - witness_infeas: p_infeas ∈ P_d with T_d(p_infeas) > T_budget
    """
    n = R.shape[0]
    if R.shape[0] != R.shape[1] or R.shape[0] != len(block_names):
        return {
            'status': 'UNRESOLVED',
            'reason': 'R_shape_mismatch',
            'R_shape': list(R.shape),
            'n_blocks': len(block_names),
        }

    # 1. Build the admissible set P_d
    # observation: per-block observed power (length n)
    if 'per_block_power' in observation:
        z_d = np.array(observation['per_block_power'])
    else:
        z_d = None

    # Per-block upper bound (content bound) - default 5x average
    if 'per_block_upper' in observation:
        u_d = np.array(observation['per_block_upper'])
    else:
        u_d = 5.0 * np.abs(z_d) if z_d is not None else 5.0 * np.ones(n)
    # Per-block lower bound
    if 'per_block_lower' in observation:
        l_d = np.array(observation['per_block_lower'])
    else:
        l_d = np.zeros(n)

    if z_d is None:
        return {
            'status': 'UNRESOLVED',
            'reason': 'no_observation_provided',
        }

    # 2. Compute lower_d = min_{p ∈ P_d} max_r (T_ambient[r] + R[r,:] · p)
    #                  = min_r (T_ambient[r] + min_{p ∈ P_d} R[r,:] · p)
    # Each inner min is an LP: min c^T p s.t. sum(p) = z_d.sum(), l ≤ p ≤ u
    # The aggregate observation: total power = sum(p) = z_d.sum() (one constraint)
    A_eq = np.ones((1, n))
    b_eq = np.array([float(z_d.sum())])
    lower_d_per_block = []
    for r_idx in range(n):
        c = R[r_idx, :]
        res = linprog(
            c, A_eq=A_eq, b_eq=b_eq,
            bounds=list(zip(l_d, u_d)),
            method='highs'
        )
        if not res.success:
            return {
                'status': 'UNRESOLVED',
                'reason': f'LP_failure_lower_r{r_idx}: {res.message}',
            }
        lower_d_per_block.append(T_ambient + res.fun)
    lower_d = max(lower_d_per_block)  # max over r

    # 3. Compute upper_d = max_{p ∈ P_d} max_r (T_ambient[r] + R[r,:] · p)
    #                  = max_r (T_ambient[r] + max_{p ∈ P_d} R[r,:] · p)
    upper_d_per_block = []
    for r_idx in range(n):
        c = -R[r_idx, :]  # negate to maximize
        res = linprog(
            c, A_eq=A_eq, b_eq=b_eq,
            bounds=list(zip(l_d, u_d)),
            method='highs'
        )
        if not res.success:
            return {
                'status': 'UNRESOLVED',
                'reason': f'LP_failure_upper_r{r_idx}: {res.message}',
            }
        upper_d_per_block.append(T_ambient - res.fun)
    upper_d = max(upper_d_per_block)

    # 4. Check feasibility and emit witnesses
    area_ok = (area_mm2 is None) or (area_mm2 * 1e-6 <= A_budget_m2)

    # Find witness_safe: minimize T (find p with T ≤ T_budget)
    # Find witness_infeas: maximize T (find p with T > T_budget)
    p_safe = None
    p_infeas = None

    if lower_d <= T_budget:
        # Find a p in P_d with T_d(p) ≤ T_budget
        r_star = int(np.argmax(lower_d_per_block))
        c = R[r_star, :]
        res = linprog(
            c, A_eq=A_eq, b_eq=b_eq,
            bounds=list(zip(l_d, u_d)),
            method='highs'
        )
        if res.success:
            p_safe = res.x
        witness_safe_T = T_ambient + (R[r_star, :] @ p_safe) if p_safe is not None else None
    else:
        witness_safe_T = None

    if upper_d > T_budget:
        r_star2 = int(np.argmax(upper_d_per_block))
        c = -R[r_star2, :]
        res = linprog(
            c, A_eq=A_eq, b_eq=b_eq,
            bounds=list(zip(l_d, u_d)),
            method='highs'
        )
        if res.success:
            p_infeas = res.x
        witness_infeas_T = T_ambient - (R[r_star2, :] @ -p_infeas) if p_infeas is not None else None
    else:
        witness_infeas_T = None

    # 5. Determine status
    if not area_ok:
        status = 'CERTIFIED_INFEASIBLE'  # area constraint violated
    elif upper_d <= T_budget:
        status = 'CERTIFIED_SAFE'
    elif lower_d > T_budget:
        status = 'CERTIFIED_INFEASIBLE'
    else:
        status = 'NON_IDENTIFIABLE'  # witness pair exists

    return {
        'status': status,
        'lower_d': float(lower_d),
        'upper_d': float(upper_d),
        'witness_safe_T': float(witness_safe_T) if witness_safe_T is not None else None,
        'witness_infeas_T': float(witness_infeas_T) if witness_infeas_T is not None else None,
        'witness_safe': p_safe.tolist() if p_safe is not None else None,
        'witness_infeas': p_infeas.tolist() if p_infeas is not None else None,
        'T_budget': T_budget,
        'A_budget_mm2': A_budget_m2 * 1e6,
        'area_ok': bool(area_ok),
    }


def decide_simple(sys_info, R, T_ambient, block_names, uniform_powers,
                   T_budget=348.0, A_budget_m2=3e-4, area_mm2=None,
                   content_factor=5.0):
    """
    Simple decision interface: provide uniform per-block power, get
    observation z_d = uniform_powers, and admissible set has per-block
    upper bound = content_factor * uniform.
    """
    observation = {
        'per_block_power': list(uniform_powers),
        'per_block_upper': [content_factor * p for p in uniform_powers],
        'per_block_lower': [0.0] * len(uniform_powers),
    }
    return decide(sys_info, R, T_ambient, observation, block_names,
                 T_budget=T_budget, A_budget_m2=A_budget_m2, area_mm2=area_mm2)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument('--R-matrix', required=True, help='Path to R matrix .npy file')
    ap.add_argument('--R-meta', required=True, help='Path to R meta .json file')
    ap.add_argument('--uniform-ptrace', help='Path to uniform ptrace (one row of N values)')
    ap.add_argument('--content-factor', type=float, default=5.0)
    ap.add_argument('--T-budget', type=float, default=348.0)
    ap.add_argument('--area-mm2', type=float, default=None)
    args = ap.parse_args()

    R = np.load(args.R_matrix)
    with open(args.R_meta) as f:
        meta = json.load(f)
    T_amb = meta['T_ambient']
    block_names = meta['blocks']
    n = R.shape[0]
    if args.uniform_ptrace:
        with open(args.uniform_ptrace) as f:
            line = f.readline()
            line2 = f.readline()
        z = [float(x) for x in line2.strip().split('\t')]
    else:
        z = [1.0] * n  # 1W per block default
    res = decide_simple(
        sys_info=meta['sys_info'], R=R, T_ambient=T_amb,
        block_names=block_names, uniform_powers=z,
        T_budget=args.T_budget, area_mm2=args.area_mm2,
        content_factor=args.content_factor,
    )
    print(json.dumps(res, indent=2))
