# CertiTherm G3 Report: EDA-Specific Next Measurement Selection

**Date**: 2026-07-19
**Status**: G3 complete for 4x4 paper design with CF=1.5x

## Method

For a NON_IDENTIFIABLE design (lower_d ≤ T_budget < upper_d), enumerate
candidate measurements (k-block combinations) and find the cheapest that
makes the design identifiable (lower_d' > T_budget or upper_d' ≤ T_budget).

Each measurement is a vector w with w_i ∈ {0, 1}. Adding constraint
`w^T p = m*` restricts the admissible set P_d. The oracle recomputes
lower_d, upper_d, and emits witness pair for replay.

Cost = k (number of sensors / measurement channels).

## Result for paper's 4x4 TESA SA ideal design with CF=1.5x

**Current state** (before measurement):
- lower_d = 325.99K, upper_d = 350.70K
- Status: NON_IDENTIFIABLE
- T_budget = 348K (decision-flip in [325.99, 350.70])

**Cheapest resolving measurement**:
- **k = 1 block** (cost = 1 sensor)
- **block = `ubuf_2`** (one of the 16 ubuf_0..ubuf_15 buffer blocks)

**Witness pair**:
- After observing m*_safe (= ubuf_2 power under witness_safe):
  - new lower_d = 324.78K, new upper_d = 337.20K
  - **Status: CERTIFIED_SAFE** (T_budget=348K > upper_d)
- After observing m*_infeas (= ubuf_2 power under witness_infeas):
  - new lower_d = 348.74K, new upper_d = 350.70K
  - **Status: CERTIFIED_INFEASIBLE** (lower_d > T_budget=348K)

The single ubuf_2 power measurement narrows the admissible set P_d
sufficiently to break the ambiguity in both directions:
- If ubuf_2 reads low (m*_safe): every admissible map is safe
- If ubuf_2 reads high (m*_infeas): every admissible map is unsafe

## Top resolving measurements

| Cost | Measurement | After safe obs | After infeas obs |
|---|---|---|---|
| 1 | ubuf_2 | CERTIFIED_SAFE (324.78-337.20K) | CERTIFIED_INFEASIBLE (348.74-350.70K) |

## Method summary

For paper's 4x4 design with content factor 1.5x:
1. The decision-flip is in a 24.71K window (lower=325.99, upper=350.70)
2. The cheapest informative single-block measurement is `ubuf_2`
3. With 1 sensor (1 channel), the ambiguity is fully resolved

## Files

- `CertiTherm/exact/g3_final.py` — G3 measurement selection script
- `CertiTherm/exact/measurement.py` — Reusable measurement infrastructure
- `CertiTherm/results/g3_measurement_selection.json` — Full result data
- `CertiTherm/results/G3_REPORT.md` — This report

## G3 status per frozen RESEARCH_CONTRACT

Per the contract, G3 is "Broad DSE Decision-Value and Systems-Cost Gate" with:
- 2 real DNN families
- 2 non-isomorphic architecture families
- 2 real package/cooling regimes

What G3 shows in this run:
- ✓ Algorithm correct: finds cheapest measurement (ubuf_2, cost=1)
- ✓ Witness replay verified: m*_safe → CERTIFIED_SAFE, m*_infeas → CERTIFIED_INFEASIBLE
- ⚠️ Single architecture family (4x4 TESA)
- ⚠️ Synthetic content factor (not real package regime)
- ⚠️ Single DNN family (uniform across all 7 networks)

To fully satisfy the contract G3 gate, would need to repeat on:
- 2x2, 3x3, 5x4 designs (different arch families) — verified to be SAFE/INFEASIBLE, not NON_IDENT
- Real gem5+McPAT per-block power (not 1.5x uniform)

The algorithm and witness machinery are correct; the empirical breadth is limited by available data.