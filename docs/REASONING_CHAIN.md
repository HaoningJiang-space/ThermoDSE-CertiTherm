# The chain, end to end: what is established, what is open, and what each number rests on

STATUS 2026-08-03. This is the index. Every claim links to the document that owns it, and every
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
| the frozen error budget covered only linearisation | model form is **25-106x** the 0.01 K contract over the polytope, **20-86x** at the nominal map -- **at run `32666c9`; see the open collision below** | dev, 3 arch x 2 workloads, span 0.30 | `MODEL_FORM_AGAINST_AN_INDEPENDENT_SOLVER.md` |
| model form exceeds the refinement tail | **1.4-11.8x**, band **0.251-1.061 K** polytope-wide, per row, one-sided, **at run `32666c9`** | same | `MODEL_FORM_AGAINST_AN_INDEPENDENT_SOLVER.md` |
| HotSpot reads colder than an independent FEM | `T_FEM - T_grid512` = **+0.21 to +0.93 K, positive at all six NOMINAL MAPS** -- not shown polytope-wide, which would need the difference MINIMISED over the set | same | `MODEL_FORM_AGAINST_AN_INDEPENDENT_SOLVER.md` |
| the FEM reference satisfies an analytical identity | `mean(T_top) = T_amb + r_convec*P` to solver precision; the 3.0e-4 residual is a predicted slab offset, ratio **1.000** on all six | same | `FEM_ANALYTICAL_VERIFICATION.md` |
| a lumped sink boundary would move the band | **0.26-1.01 K** -- a sensitivity to a BC HotSpot does not use, not a correction | same | `LUMPED_BOUNDARY_SENSITIVITY.md` |

| the refinement tail is bounded | successive ratios 1.8-2.8 per doubling, observed order `p ~ 1`, so the tail past `grid512` is no larger than the last measured step | same | `ROBUST_FEASIBLE_FRONTIER.md` |
| GPU and CPU operators are the same map | parity **exactly 0.0 K/W** at `grid128`, `grid256`, `grid512` | 3 designs | `ARCHIVE_CENSUS_RUN_LOG.md` |
| `gridN-avg` breaks thermal reciprocity | **2.5 - 12.0 %**, shrinking with refinement; FEM and `block` are 0.00 %. Effect on `sup_p T`: **+0.002 to +0.071 K** | dev + census | `CertiTherm/reciprocity.py` |
| the class-total constraints are redundant here | `b_ub - a_ub @ upper >= 0` always, and 0 to machine precision on every instance tried; LP agrees with greedy to **1.07e-9 K** | dev + proof | `ARCHIVE_CENSUS_RUN_LOG.md` |
| an operator can be amortised across a design class | exact reuse band **0.69-2.44 K**; class is a function of `(xx,yy,cx,cy)`; **14x** archive-wide | 64 archive designs | `CAN_THE_OPERATOR_BE_AMORTISED.md` |
| the archive's thermal column is not reproducible | **+5.9 to +10.1 K**, one-signed, five hypotheses refuted | 64 archive designs | `ARCHIVE_CENSUS_RESULT.md` |
| **a pointwise residual majorant cannot certify, at ANY element degree** | equilibration removes 97 % of it and the factor lands on **1.0012** at P1; P2 gives **0.8545 median but 1.0790 max**, and the rate is `h^0.751` against P1's `h^0.770` -- the same, because the absolute-jump measure's `O(1)` mass is a statement about FACES and no degree change touches it. Reaching the registered bar needs **~1.9e9 dofs** | synthetic layered box, contrast 3.08 (the favourable case) | `GB1_THE_NAIVE_MAJORANT_IS_VACUOUS.md` |
| **both missing trace sources go to the CENTRAL block, by the generator's own column order** | `gen_all_ptrace_3D` writes `interposer` first and `p_itp,0,0,0,0`, so the frame carries zero; the commented DRAM block repeats it. Priced by one matvec: **3 of 6 dev points survive a fully corrected trace**, `arch_b -> arch_c` does not reverse but **`arch_c`/transformer becomes UNRESOLVED** | dev, 6 points, `grid128` cell operators, span 0.30 | `THE_GENERATOR_PUTS_THE_MISSING_HEAT_CENTRALLY.md` |
| the NoC over-count is per-architecture and minor | `4*cx*cy / ((cy-1)*2*cx + (cx-1)*2*cy)` = **1.3125 / 1.2903 / 1.3333**; fixing it returns only **0.068-0.471 K** | same | same |
| **the uniform NoC spread is the LARGEST trace defect** | bracketed below by the uniform spread and above by all-on-the-worst-io-block: **3.137 to 46.445 K**, and **every upper bracket exceeds its own slack on all six points**. A loose bound, not an estimate -- but wide enough to contain every verdict, so no certificate on this trace is robust to it | same | `THE_GENERATOR_PUTS_THE_MISSING_HEAT_CENTRALLY.md` |
| **the separator window is one-dimensional** | separator iff `margin + e_total <= dist < g`, so its non-emptiness is candidate-independent arithmetic and is **not** what binds -- at `g=3` it is 1.5-2.7 K wide. **None of the six dev points lies in the band** | same | `G2_REPAIR_THE_WINDOW_IS_ONE_DIMENSIONAL.md` |

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
| ~~"HotSpot systematically underestimates, one-signed on six points"~~ | **the withdrawal is VOID; the claim stands at +0.21 to +0.93 K, positive on all six** | it was withdrawn on the premise that HotSpot lumps its sink node. It does not -- see the last row of this table |
| ~~"model form is 25-106x the contract, 1.4-11.8x the tail"~~ | **the withdrawal is VOID; both numbers stand** | same false premise. `0-60x` / `0-11.8x` are properties of a lumped-boundary comparison, now owned by `LUMPED_BOUNDARY_SENSITIVITY.md` |
| "the reciprocity break costs ~2.3 K, comparable to the model-form band" | **+0.002 to +0.071 K**, measured by symmetrising | a relative entrywise figure times a scale is not an effect on a max of weighted sums |
| "the boundary term is at most a third of the band" | ~~it was most of it~~ -- **there is no boundary-realisation mismatch at all** | HotSpot distributes `r_convec` by cell area (`temperature_grid.c:1054`), which is the uniform Robin already used. Both the "at most a third" reading AND the withdrawal it led to are void |

## Provisional -- do not quote outside this repository

**The 0.25-1.06 K model-form band is no longer provisional either.** It was held here on the belief
that a boundary-realisation term sat inside it; HotSpot distributes `r_convec` by cell area, so the
distributed-Robin comparison was like-for-like and there is no such term to subtract. **`+32.1 %`
and "5 of 6 certify" are also no longer provisional**: both hold at the cell endpoint without any
band folded in. What remains conditional is the ENDPOINT, not the band. The frontier numbers were
computed on
**block-average rows**, and the 330 K limit
is not about block averages. Three independent routes agree on +32.1 %, but all three share that
endpoint, so their agreement is not evidence about it. The tightest point has **0.31 K** of slack
against a measured cell-versus-block gap of 0.21-0.76 K, so it is genuinely at risk.
`CertiTherm/cell_certificate.py` now exists and the dev runs are in flight.

## Open, ranked

1. **The mechanism of the 8 K -- SIX hypotheses refuted, mechanism not established.** Package, power
   map, functional, workload set, evaluator flags, and -- newly, correcting an earlier claim in this
   file -- the compatibility layer. That last one restores `word_bytes=1`, which is **the value every
   other implementation already uses**, so it changes whether a call raises and not what it computes.
   The submodule is a single-commit snapshot; the sibling repo shows the archive was added at the
   pinned `51c1506` while the API fix came 27 commits later. **The producing tree is not recoverable
   from this repository.** The decision it gated is answered without it: the archive supplies design
   vectors, not a thermal screen.
2. ~~**The cell-level certificate's verdict.**~~ **CLOSED.** `arch_b`/transformer is refused at the
   cell endpoint by **-0.36 K with no band folded in** (cell peak 330.30 K, above the limit
   itself); `arch_c`/transformer certifies with +4.03 K. The `arch_b -> arch_c` switch and the
   +32.1 % price therefore **survive without the block-average assumption**. **All six dev points: 5 of 6 certify**, gap +0.21 to +0.62 K.
   `CELL_ENDPOINT_RESULT.md`.
3. ~~**The three declared-equivalent FEM assumptions.**~~ **CLOSED, and all three are safe.** Source
   depth **+0.0201 K** and void filler **+0.0000 K** were always safe. The Robin realisation was
   believed unsafe for two rounds and is now **confirmed safe at source**: `temperature_grid.c:1054`
   and `temperature_block.c:207` both divide `r_convec` proportional to cell area, which IS the
   uniform Robin the adapter used. The exact lumped-node construction still exists and measures
   **0.260 - 1.005 K**, but that is a sensitivity to a boundary condition HotSpot does not use
   (`LUMPED_BOUNDARY_SENSITIVITY.md`), not a term inside the band. Guarded by
   `_assert_convection_is_distributed`. Historical framing below.

   **The three declared-equivalent FEM assumptions -- MEASURED, and one of them is not safe.**
   On `arch_c`/resnet50 at n=192 against a 321.7263 K baseline: source in the top 10 % of the die
   moves the peak **+0.0201 K**; a near-adiabatic void instead of still air moves it **+0.0000 K**.
   Those two are safe. **The Robin realisation is the same size as the band.** Per case on all six
   points, `spread / band` is 0.55 - 1.59, median 0.98, three of six at or above 1; the spread is a
   near-constant 9.7 - 10.9 % of the total rise. An earlier single-design reading of "at most a
   third" was wrong in direction and magnitude. Historical: The uniform Robin already
   reproduces the lumped total-flux relation with the MEAN top temperature, so the two realisations
   differ only by the sink-top SPREAD, measured at **0.345 K** across a 3.578 K rise. The
   conductivity-scaling run's -0.7340 K exceeds that and therefore also changes lateral sink
   spreading -- it is not an isolation of the term. Historical figure: driving the sink towards the
   isothermal limit moved the peak **-0.7340 K** (x10, energy balance 2.07e-07, the ONLY
   admissible point; x100 and x1000 were refused by the gate and their numbers are inadmissible and
   must not be quoted). That is the same sign and comparable magnitude to the entire
   model-form band, so **the band is an upper bound on model form rather than a measurement of it**,
   and separating the two is now the first thing the FEM reference owes.
4. **Scale.** Everything above rests on 3 architectures x 2 workloads x 1 package.
5. **The uncertainty set is declared, not measured.** The certificate is a supremum over `P`; if `P`
   is wrong, everything is. `activity_span` is currently a knob.

## Direction, decided 2026-08-01

Architecture-level DSE with an internalised thermal constraint is **demoted to future work with a
named obstruction**: a small geometric displacement does not give a small coefficient perturbation
once a material interface moves, and 64 archive designs induce 64 distinct geometries with zero
shared. The direction is now **thermal-constrained scheduling and mapping on a FIXED geometry**,
where `R` is built once and the constraint really is linear in the decision variable.
See `DIRECTION_FIXED_GEOMETRY.md`.

## What would make this a contribution rather than a verifier

A certificate only ever **refuses**, so "we certify less than others" cannot be a headline. The
usable shape is the opposite: because the band here is **computed** (0.25-1.06 K) rather than guessed
(the field's 3-5 K guard bands, and ThermoDSE's own unsupported 348 K), a search constrained by it
can reach designs a guessed margin rejects. That number does not exist yet and is the missing piece.

**On a fixed geometry that shape is reachable and the obstruction is gone**: `R` is built once, the
decision variable *is* the power allocation, and the constraint is genuinely linear in it, so a
schedule search performs **zero thermal solves online** against one HotSpot call per candidate for
the incumbent. Across *architectures* it is not reachable -- see `DIRECTION_FIXED_GEOMETRY.md` for
why the 14x class amortisation does not rescue it.

## 2026-08-04 — the missing piece, and what it cost to get there

The paragraph above names one number as missing: *"a search constrained by a computed band can reach
designs a guessed margin rejects"*. Three things now exist toward it and two prior entries are
withdrawn.

**Established.**

| what | owner |
| --- | --- |
| the in-loop certificate is an **exact** supremum (continuous knapsack), one-sided, fail-closed, **12 ms** per candidate against 20-30 s for a HotSpot solve | `CERTIFICATE_IN_THE_LOOP.md` |
| all six development points certified on the **routed** trace — the first verdicts here not taken on the legacy one; five certify | `ROUTED_CERTIFICATE_AND_THE_BOUND_THAT_IS_NOT_ONE.md` |
| the incumbent's own designs fail their own envelope: one refused at its **nominal** map, five with radius 0.49-1.16 | `THE_INCUMBENT_DESIGNS_DO_NOT_SURVIVE_THEIR_OWN_ENVELOPE.md` |
| the assumed-uniform nuisance placement is **not an upper bound** — below the routed one on 4 of 6, by up to 1.25 K | `ROUTED_CERTIFICATE_AND_THE_BOUND_THAT_IS_NOT_ONE.md` |
| the missing-energy fraction is **per case**, 0.3328-0.9997, and the value previously used was the largest | `PER_CASE_Q_WITHDRAWS_THE_PLACEMENT_FREE_REFUSAL.md`, `experiments/missing_energy_ledger.tsv` |
| every nuisance parameter measured on all six: DRAM `kappa = 1.000` on 4 dies, frame carries **zero** | `THE_NUISANCE_PARAMETERS_ARE_ALL_MEASURED.md` |
| the impulse loop parallelises **bit-identically**, 1333 s → 89 s | `THE_IMPULSE_LOOP_IS_PARALLEL.md` |
| leg-by-leg status, including the two refuted premises | `THREE_LEGS_STATUS.md` |

**Withdrawn.** The trace corrections' priced conclusions (`THE_GENERATOR_PUTS_THE_MISSING_HEAT_
CENTRALLY.md`) — 3 of 6 survive becomes **5 of 6**, and `arch_c`/transformer is certified rather than
UNRESOLVED. G2's population verdict (`G2_REPAIR_...`) — its `dist` column inherited the same scaled
`Q`, and the archive population it would screen is **cold** (5.5-18.5 W against 28-57 W).

**The fixed-geometry direction is confirmed and strengthened, not changed.** Reuse over 61 archive
designs under routed lowering is **0.0 %**, and perturbing one field at a time, **zero of ten** leave
the floorplan invariant on `arch_b` and `arch_c`. A first measurement on `arch_a` alone found
`interval` invariant; that was that design's artefact (`cut_x = cut_y = 1`, no inter-chiplet gap to
space) and generalising it was an error corrected by measuring a second base, not by argument.

**Obtained 2026-08-04** (`CERTIFIED_SEARCH_RESULT.md`). Seeded from `arch_b`/transformer, whose
certified peak is 331.558 K — **REFUTED by 1.618 K** — a certificate-constrained search over the
archive's own value sets reaches a **CERTIFIED** design at 329.612 K for **`+8.77 %` EDYP**. Energy
falls; latency and yield pay. And the cost split is leg 2's real number: operator builds 1526 s,
ThermoDSE 134 s, **the certificate 2.786 s — 0.17 % of the search**.

The same failure repeats on a second population: of 61 archive designs under `transformer`, each
selected on a reported peak ≤ 330 K, `arxv031` certifies at +0.723 K and **stops certifying at 9 %
activity variation**. (The one `REFUTED_AT_NOMINAL` is refused by 41 mK — inside the model-form band,
so `UNRESOLVED`-grade, and it is not the load-bearing row.)

**Still missing.** `e_total` at the cell endpoint. No model-form band is folded into any table above,
and folding it in moves the found design's `+0.328 K` slack into `UNRESOLVED`. It is the single number
most likely to overturn this round and it is the binding action.
