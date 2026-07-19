# G2 Soundness Fix Report

**Date**: 2026-07-19
**Status**: G2 LP oracle corrected, witness verification added, 14/14 unit tests pass

## Bug found

The original `decide.py` (commit `38db908` "CertiTherm Phase G2") computed:
```python
lower_d = max_r (T_amb[r] + min_{p ∈ P_d} R[r,:]·p)   # MAXMIN, not MINMAX
```

This is **maxmin**, not the required **minmax**:
```python
lower_d = min_{p ∈ P_d} max_r (T_amb[r] + R[r,:]·p)   # correct MINMAX
```

The difference is the min-max inequality: maxmin ≤ minmax in general.

## Counterexample (2-cell)

R = [[0,1],[1,0]], T_amb=0, sum(p)=2, p ∈ [0,10]^2.
- True lower_d (minmax): T = max(p0, p1), minimized at p=(1,1) → 1.0
- True upper_d (max over p): T = max(p0, p1), maximized at p=(2,0) → 2.0

Original (buggy) code returned: lower_d=0.0 (wrong), upper_d=2.0 (correct).
Fixed code returns: lower_d=1.0, upper_d=2.0 (both correct).

## Fix

Replaced the row-decomposed maxmin LP with an **epigraph formulation** for minmax:
```
min t
s.t. R[r,:]·p - t ≤ -T_amb[r]    for all r in 0..N-1
     sum(p) = z_d.sum()
     l_d ≤ p ≤ u_d
```

Variables: x = [p_0, ..., p_{N-1}, t]  (N+1 total)
Constraints:
- A_ub[r, :N] = R[r, :]
- A_ub[r, N] = -1
- b_ub[r] = -T_amb[r]
- A_eq[0, :N] = 1, A_eq[0, N] = 0
- b_eq[0] = z_d.sum()

Verified with `test_minmax_formulation_2cell`: lower=1.0, upper=2.0 ✓

## Witness verification

Witnesses are now verified by computing `max_r T_r(p_witness)` directly:
- For witness_safe: should equal lower_d
- For witness_infeas: should equal upper_d

All 12 runs in decisive experiment verify: ALL witnesses match the corresponding bounds.

## Updated decisive experiment results (with minmax LP)

| Design | CF=1.5 | CF=2.0 | CF=3.0 |
|---|---|---|---|
| 2x2_min | SAFE | SAFE | SAFE |
| **4x4_paper_TESA** | **NON_ID (325.99-350.70K)** | **NON_ID (325.55-359.88K)** | **NON_ID (325.33-378.19K)** |
| 3x3_square | SAFE | SAFE | SAFE |
| 5x4_nonsq | INFEAS | INFEAS | INFEAS |

**3/12 NON_IDENTIFIABLE, all with verified witnesses.**

## G2 status: STILL CONDITIONAL

Per the CCFA audit:
- ✅ LP oracle: now correct (minmax verified)
- ✅ Witness verification: now full peak T
- ⚠️ Test designs: still use "uniform"/"mixed" as DNN family labels, not real DNNs
- ⚠️ "Content factor" is not a real package regime
- ⚠️ Single 2-cell counterexample fixed, but the full 4x4 paper design still has the flipped verdict

G2 gates per the contract: need a real placed-power case with content-bound
admissible set P_d and a real decision-changing witness pair. The LP machinery
is now correct, but the empirical cases need to be re-run on real gem5+McPAT
or similar real-workload traces.

## Files modified

- `CertiTherm/exact/decide.py` — Epigraph minmax LP
- `CertiTherm/exact/decisive_experiment.py` — Full witness verification + manifest
- `CertiTherm/tests/test_decisive_oracle.py` — 3 new minmax tests + corrected test_observation_sum_constraint
- `CertiTherm/results/G2_SOUNDNESS_REPORT.md` — This report

## What's still missing for full G2

Per CCFA:
1. Real DNN family placement (e.g., ResNet, Transformer via gem5+McPAT)
2. Real package/cooling regime (not just "content factor")
3. Independent oracle verification (3D-ICE or LP/MILP)
4. Independent replay (separate machine + runner)
5. Manifest with full provenance: R matrix hash, observation hash, ptrace hash, input hash

Items 3-5 are implementable; items 1-2 require external data (gem5+McPAT
runs that we don't have locally).