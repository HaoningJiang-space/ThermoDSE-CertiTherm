# Corrected G2 gate outcome

Date: 2026-07-19

Execution commit: `506fc1b2069df86238386ed98ee57e678020d165`

Status: **PASS within the frozen narrow placed-power scope**

## Outcome

The corrected rectangular min-max oracle was replayed on the registered M4 and
M2 SNAX GEMM placed-power domains. Candidate order is the preregistered M4 then
M2 throughput preference; it was not selected from temperature results.

| Query | Thermal limit | Result | Replayed outcome(s) |
| --- | ---: | --- | --- |
| universal certificate | 318.73104198263934 K | `CERTIFIED` | `snax_gemm_m2_t8` |
| decision witness | 318.7169029548827 K | `NON_IDENTIFIABLE` | `snax_gemm_m2_t8`, `NO_FEASIBLE_DESIGN` |

The certified-query digest is
`881fa29f5ca18712e678da6ca469b853b5e3ea2f677caa0849548eb99eba025c`.
The non-identifiable-query digest is
`6df256c19707bbf5eb846cc8edcf83a65e458afaa1bd4c8fc01741166d0ef5f7`.
Both complete decision tuples passed direct, solver-free selection replay.

## Physical bounds and parity

| Candidate | Variables / groups / thermal points | Lower–upper peak | Full decision margin | State at witness query | Max current/external bound delta |
| --- | ---: | ---: | ---: | --- | ---: |
| M4 | 4608 / 18 / 256 | 318.74592322468743–318.7487565166226 K | 0.002343685852766524 K | certified infeasible | 6.26e-13 K |
| M2 | 1536 / 6 / 256 | 318.7159000757559–318.7179059124411 K | 0.0005985924339939375 K | non-identifiable | 7.85e-08 K |

Inputs are bound by
`CertiTherm/evidence/g2_placed_power_registry.json` (SHA-256
`b18e08e340e3ca0ff2a031549fde40cbf2620306a2376edcb3aa03166434e687`).
The external evidence uses real route-clean post-PnR group/cell power,
256-point native HotSpot Green operators, and independently replayed
HiGHS/GLOP, groupwise greedy, and epigraph-dual bounds. Across the original
evidence and this correction there were 2,104 native HotSpot executions.

Two clean remote executions passed all 37 tests and both artifact replays.
Their runtime-bound artifact hashes differ as expected, while the scientific
digest is identical:
`9bd0d1b4fa7b7babb301a8e26503ed32a7aa3032b4895a1ac59a36406ad08826`.
Raw replay artifacts remain outside Git; only the input registry and this
concise outcome are committed.

## What changed from the invalidated pilot

- replaced row-wise max-min with the correct epigraph min-max problem;
- enforced nonzero lower bounds, explicit equalities/inequalities, compactness,
  monotonicity, finite values, and fail-closed solver/replay behavior;
- generalized the thermal operator from square toy matrices to the physical
  256-by-1536/4608 rectangular operators;
- included the registered two-sided thermal-model error band;
- lifted candidate bounds to the frozen cross-candidate selection theorem and
  content-bound complete witness tuples;
- invalidated the old synthetic G2 and premature G3 claims.

## Scope boundary and next gate

This result proves existence in a conservative, workload-consistent
placed-power over-approximation. It does not prove that every optimized box
witness is a causally attainable complete workload trace, and it covers only
two nearby SNAX GEMM architecture points under one package/thermal regime.

Therefore G2 is closed, but G3 remains open. The next work is the registered
2 DNN families × 2 non-isomorphic architecture families × 2 package regimes
evaluation with fair baselines, false-decision metrics, runtime/RSS, and
failure taxonomy. The invalidated single-sensor measurement result is not
reused.
