# Shared-Support Farkas Co-Design — evidence (NON-CLAIM)

Proposed non-incremental reformulation: instead of decomposing (IHS master proposes a
cover, oracle finds a witness, add a hitting-set cut, repeat), solve ONE problem —
find a minimum-cost measurement set `x` such that EVERY collision cell `j` admits a
Farkas infeasibility certificate whose multiplier support lies inside the selected
measurements.

    P_j(S) = { z=(p_safe,p_reject) : B_j z <= d_j, E z = f,
               |a_i'(p_safe - p_reject)| <= tau_i  for i in S }
    S certifies  <=>  P_j(S) = empty for all j
                 <=>  each j has alpha_j,beta_j,lambda^{+/-}_j with support in S

## Step 1 — theorem and encoding validated by full 2^n enumeration

Tiny instance: 3 blocks, 3 reject cells, 5 measurement channels, all 32 subsets
enumerated. Two INDEPENDENT checks (separating the mathematics from the encoding,
because a monolithic reformulation usually fails at the encoding):

| check | result |
|---|---|
| **(A) theorem** — `P_j(S)=empty  <=>  Farkas cert with support in S`, tested by LP both ways, no big-M | **0 mismatches** over 32 subsets x 3 cells → **PASS** |
| brute-force optimum | `C* = 3` via `S = (0,1,2)` (14 certifying subsets) |
| **(B) encoding** — monolithic Farkas MIP (binaries `x_i`, per-cell multipliers `y_j`, gated `y_meas(i) <= M x_i`) | `C* = 3` via `S = (0,1,2)` → **matches brute force** |

### big-M sensitivity (the usual failure mode)

The encoding recovers `C*=3` for **every** M tested: `1e6, 1e3, 100, 10, 2`. Even
`M = 2` is sufficient here, because the homogeneous `<= -1` normalisation keeps the
certificate multipliers small. A small VALID M matters: it directly controls the
strength of the `lambda <= M x` relaxation, which is what usually renders monolithic
reformulations useless.

## What this does and does NOT establish

Establishes: the reformulation is mathematically correct and correctly encodable, and
big-M is not automatically fatal.

Does NOT establish (open, and the real risks):
- **Tractability at scale.** Real instances have ~681 cells x (~1167 alpha + 2x243
  lambda) ~ 1.1M continuous variables, ~309k stationarity rows, 243 binaries. This is
  precisely the regime that motivates decomposition in the first place.
- **Relaxation strength at scale.** Whether `L_frac` from the LP relaxation beats the
  CURRENT bound (an integral MILP over discovered cuts) is unknown -- complete but
  fractional vs partial but integral, and hitting-set LPs have Theta(log n)
  integrality gaps.
- **Novelty.** LP-dualising an inner feasibility test into a single-level MIP with
  indicator-linked multipliers is the standard robust/bilevel move -- it is the
  monolithic form that Benders/IHS exists to avoid. Any novelty must come from the
  shared-support-across-cells structure, the thermal decision-identifiability
  application, and the proof-carrying closure -- not the reformulation itself.

## Next (in order, cheapest-decisive first)
1. CPU monolithic on a REAL candidate: measure build size, memory, LP-relaxation
   bound `L_frac` vs the current MaxHS bound, and root-LP time. This kills or
   confirms tractability before any GPU work.
2. Only if (1) survives: block-angular GPU relaxation for a fractional design +
   certificate-aware rounding, with exact CPU verification (GPU never on the
   certification path -- a prior PDHG attempt here was rejected at the 1e-4 floor).
