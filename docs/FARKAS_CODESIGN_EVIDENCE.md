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

## N0 — corrected margin audit (supersedes the earlier sum-hinge numbers)

The first audit was defective (sum-hinge; silently skipped unresolved cells; invented
verdict thresholds; false "Kelvin-equivalent" units; no registry validation). All
fixed. Two things the correction immediately bought:

**1. It caught a real fail-open.** On arch_c the fail-closed version reports
**6 cells that do not resolve** (HiGHS status 4). The old version skipped them and
printed `Gamma_1 = 4.008e-05` as if it were the global minimum. That number is
withdrawn as untrustworthy, not merely superseded.

**2. It exposed a normalisation trap.** Every action tolerance in the registry is
uniformly `tau = 1e-8`, so the dimensionless `rel` normalisation (divide by `tau`)
inflates coefficients by ~1e8 and is what caused those 6 numerical failures. `rel` is
therefore unusable on this registry despite being the scaling-invariant choice.

### Result (arch_c, verified cover 143/199 actions, norm=abs, 0 unresolved)

| statistic | value (raw power units) |
|---|---:|
| Gamma_inf min (worst cell) | **1.0684e-06** |
| p1 | 2.1512e-06 |
| median | 1.9133e-01 |
| max | 2.2182 |

cells: 543 total, 289 unreachable, 254 with a margin, **0 UNRESOLVED**.
Worst cell = model/point (0,175); its adversarial world pair is saved.

### Reading (deliberately not a robustness verdict)

- Robustness is **highly heterogeneous**: the worst cell sits ~10^5 x below the
  median. A single near-critical cell governs the contract.
- In tolerance units the worst margin is ~107 tau, so it is NOT a solver knife edge.
- Whether 1.07e-06 raw power units is physically adequate depends on a `rho` derived
  from the frozen measurement-error contract. This audit refuses to invent one, and
  no robust/fragile verdict is claimed here.

### Tiny-instance gate (prerequisite, PASS)

`Gamma_inf(S) > 0 <=> S identifying`: 0 mismatches over all 2^n subsets; duplicating a
channel leaves `Gamma_inf` unchanged (duplication-invariant). Honest caveat: the
contrast test did NOT exhibit `Gamma_1` inflation on that instance -- the adversary
picks a `z` where the duplicated channel is not binding and the min over cells masks
per-cell inflation -- so the `Gamma_1` duplicate-bias remains motivated, not demonstrated.
