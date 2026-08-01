# The chain, end to end: what is established, what is open, and what each number rests on

STATUS 2026-08-01. This is the index. Every claim links to the document that owns it, and every
number states the population it was measured on. Anything not listed here is not established.

## The one idea everything else follows from

Steady conduction with temperature-independent conductivity and Robin cooling is **linear in the
power vector**. So *any* thermal operator of this physics is affine, `T = R p + a` -- HotSpot at any
grid, a block model, a 3-D FEM, all of them. Three consequences, and they are the whole method:

1. **The supremum of any row over a power polytope is exact and cheap.** `max_p (r . p + a)` over a
   box with a total-power equality is a greedy fill: one sort, no solver, no sampling.
2. **The same holds for the difference of two operators**, so the worst-case disagreement between
   any two models over the whole admissible set is exactly computable -- not estimated from samples.
3. **An operator is built by `n + 1` impulse solves and reused forever.** For the FEM the stiffness
   matrix does not depend on the power map, so all `n + 1` share one factorisation: 182 solves in
   30 s on one A800.

This is why an independent-solver comparison that was budgeted at 6-8 weeks took a day: the polytope
machinery written for cross-grid comparison transferred to cross-solver comparison **unchanged**,
because linearity is a property of the PDE and not of HotSpot.

## Established, with the population stated

| claim | number | population | owner |
| --- | --- | --- | --- |
| the frozen error budget covered only linearisation | model form is **25-106x** the 0.01 K contract | dev, 3 arch x 2 workloads | `MODEL_FORM_AGAINST_AN_INDEPENDENT_SOLVER.md` |
| discretisation is **not** where the error is | model form 0.25-1.06 K vs the complete `grid128->grid512` tail 0.05-0.34 K, a factor of **1.4-11.8** | same | same |
| HotSpot underestimates, one-signed | `T_FEM - T_grid512` is **+0.20 to +0.86 K on all six points** | same | same |
| the refinement tail is bounded | successive ratios 1.8-2.8 per doubling, observed order `p ~ 1`, so the tail past `grid512` is no larger than the last measured step | same | `ROBUST_FEASIBLE_FRONTIER.md` |
| GPU and CPU operators are the same map | parity **exactly 0.0 K/W** at `grid128`, `grid256`, `grid512` | 3 designs | `ARCHIVE_CENSUS_RUN_LOG.md` |
| the class-total constraints are redundant here | `b_ub - a_ub @ upper >= 0` always, and 0 to machine precision on every instance tried; LP agrees with greedy to **1.07e-9 K** | dev + proof | `ARCHIVE_CENSUS_RUN_LOG.md` |
| an operator can be amortised across a design class | exact reuse band **0.69-2.44 K**; class is a function of `(xx,yy,cx,cy)`; **14x** archive-wide | 64 archive designs | `CAN_THE_OPERATOR_BE_AMORTISED.md` |
| the archive's thermal column is not reproducible | **+5.9 to +10.1 K**, one-signed, five hypotheses refuted | 64 archive designs | `ARCHIVE_CENSUS_RESULT.md` |

## Withdrawn, and why

| withdrawn | replaced by | reason |
| --- | --- | --- |
| "100-740x" model-vs-budget ratio | 25-106x, measured here | the original came from another paper's package and system |
| "the polytope supremum is 4-133x the nominal value" | not restated | the two columns used **opposite sign conventions** |
| breakpoint at activity span 0.91 | **0.36**, then 0.10-0.20 once model form is budgeted | the certificate evaluated the peak at the nominal map, not over the polytope. **A discrepancy bound is not a temperature bound** |
| "raising the FEM mesh can only lower X" | measured: larger band on **61 of 62** designs, the exception by 0.0006 K | monotonicity does not follow from one design |
| "the 8 K gap is a package mismatch" | refuted, configs identical | — |
| "the 8 K gap is cell-max vs block-average" | refuted, the same-run gap is **+0.21 K median** | 40x too small |
| "the 8 K gap is the six-workload set" | refuted for temperature (+0.30 K); **confirmed for EDYP** (971 vs 811) | — |

## Provisional -- do not quote outside this repository

**`+32.1 %` and "5 of 6 certify".** Both are computed on **block-average rows**, and the 330 K limit
is not about block averages. Three independent routes agree on +32.1 %, but all three share that
endpoint, so their agreement is not evidence about it. The tightest point has **0.31 K** of slack
against a measured cell-versus-block gap of 0.21-0.76 K, so it is genuinely at risk.
`CertiTherm/cell_certificate.py` now exists and the dev runs are in flight.

## Open, ranked

1. **The mechanism of the 8 K.** Five hypotheses refuted; what remains is provenance-level -- a
   different HotSpot build, a different generated config at the time the archive was written, or a
   stale value. The **decision** it gated is answered: the archive supplies design vectors, not a
   thermal screen. The mechanism is not.
2. **The cell-level certificate's verdict.** Implemented and tested; the dev runs decide whether the
   frontier survives its own endpoint.
3. **The three declared-equivalent FEM assumptions.** Source depth, void filler, and the Robin
   realisation of `r_convec`. Each is now one environment variable and all three are running.
4. **Scale.** Everything above rests on 3 architectures x 2 workloads x 1 package.
5. **The uncertainty set is declared, not measured.** The certificate is a supremum over `P`; if `P`
   is wrong, everything is. `activity_span` is currently a knob.

## What would make this a contribution rather than a verifier

A certificate only ever **refuses**, so "we certify less than others" cannot be a headline. The
usable shape is the opposite: because the band here is **computed** (0.25-1.06 K) rather than guessed
(the field's 3-5 K guard bands, and ThermoDSE's own unsupported 348 K), a search constrained by it
can reach designs a guessed margin rejects. That number does not exist yet and is the missing piece.

The amortisation probe is what makes it reachable: thermal feasibility is a set of **linear rows**,
so it can be a constraint inside a search rather than an oracle called per candidate -- at
`n + 1` solves per design class, 14x fewer than per candidate.
