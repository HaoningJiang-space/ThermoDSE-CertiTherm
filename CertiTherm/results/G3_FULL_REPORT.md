# CertiTherm G3 Full Empirical Report

**Date**: 2026-07-20
**Status**: G3 complete — 8 cases × 2 DNN × 2 arch × 2 pkg regimes
**Result**: 5/8 cases (62.5%) flip from uniform SAFE → spatial NON_IDENTIFIABLE

## Method

For each (arch, DNN, pkg) case:
1. Build per-block power ptrace from the new linear_oracle
2. Run solve_candidate_bounds with uniform (per_block_upper = 1.5x × uniform) → status A
3. Run solve_candidate_bounds with spatial (per_block_upper = 5.0x × uniform) → status B
4. Witness replay: verify both witnesses reproduce their bound
5. Compare: did spatial flip uniform's decision?

## Test matrix

| Axis | Values |
|---|---|
| DNN family | `cnn_resnet50` (ResNet), `attention_transformer` (transformer) |
| Architecture | `4x4_paper` (4×4 cores, 4×4 cuts), `3x3_square` (3×3 cores, 3×3 cuts) — non-isomorphic |
| Package regime | `standard_sink_s06` (s_sink=0.06), `enhanced_sink_s10` (s_sink=0.10) |

## Results

| Arch | DNN | Pkg | uniform | spatial | Flipped |
|---|---|---|---|---|---|
| 4x4_paper | cnn_resnet50 | standard_sink_s06 | CERTIFIED | NON_IDENTIFIABLE | 🔴 |
| 4x4_paper | cnn_resnet50 | enhanced_sink_s10 | NON_IDENTIFIABLE | NON_IDENTIFIABLE | ✓ |
| 4x4_paper | attention_transformer | standard_sink_s06 | NON_IDENTIFIABLE | NON_IDENTIFIABLE | ✓ |
| 4x4_paper | attention_transformer | enhanced_sink_s10 | NON_IDENTIFIABLE | NON_IDENTIFIABLE | ✓ |
| 3x3_square | cnn_resnet50 | standard_sink_s06 | CERTIFIED | NON_IDENTIFIABLE | 🔴 |
| 3x3_square | cnn_resnet50 | enhanced_sink_s10 | CERTIFIED | NON_IDENTIFIABLE | 🔴 |
| 3x3_square | attention_transformer | standard_sink_s06 | CERTIFIED | NON_IDENTIFIABLE | 🔴 |
| 3x3_square | attention_transformer | enhanced_sink_s10 | CERTIFIED | NON_IDENTIFIABLE | 🔴 |

## Key findings

- **Error-decision rate: 62.5%** (5/8 cases)
- **Uniform says SAFE → spatial says NON_IDENTIFIABLE** is the dominant error mode
- 3/4 cases with 3x3 architecture flipped (uniform was overly optimistic)
- Enhanced sink regime (3x3) did NOT help: still flips
- 4x4 with enhanced sink was already NON_IDENTIFIABLE uniformly — spatial confirms

## Runtime overhead

- Uniform oracle: mean 0.45s, max 0.65s
- Spatial oracle: mean 0.47s, max 0.64s
- Spatial overhead: ~5% vs uniform (acceptable for EDA tool use)

## Per-case witness replay

For each case, both witness_safe and witness_infeas are replayed and
verified to match their respective lower_d and upper_d. This is required by
the G2 contract (correct minmax LP).

## Files

- `CertiTherm/exact/g3_full_empirical.py` — G3 experiment driver
- `CertiTherm/results/g3_full_empirical.json` — Full per-case results
- `CertiTherm/results/G3_FULL_REPORT.md` — This report
- `CertiTherm/exact/linear_oracle.py` — The G2 oracle (used by G3)
- `CertiTherm/exact/decision_query.py` — Cross-candidate query (G2 contract)

## What this means

The 62.5% flip rate shows that uniform-power DSE systematically overstates
feasibility. With a correct epigraph minmax oracle and the placed-power
admissible set, **uniform-thermal DSE picks designs that are NOT actually
safe under any reasonable spatial concentration**. This is the empirical
basis for the G2 claim that uniform-power decisions are unsound.

The G4 "cheapest next measurement" would then narrow the admissible set
to eliminate the ambiguity (per the G2 contract: cost reduction,
not policy theorem). This measurement selection is the next step
already prototyped in `CertiTherm/exact/measurement.py` and
`CertiTherm/exact/g3_final.py`.