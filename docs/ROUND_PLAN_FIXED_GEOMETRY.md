# Round plan: fixed-geometry thermal-constrained mapping, and what "done" means

PLAN 2026-08-02. Written after a full read of the git history and the owning documents. This states
the direction, what is already established, the gates that remain, and **the bar each gate has to
clear before the round can stop**. It does not restate numbers -- every one links to its owner.

## The direction, and why it is this one

**Chiplet thermal feasibility is the object; the certificate is the instrument.** The project asks
whether the observations obtainable at a design stage suffice to certify a thermal-feasibility-driven
chiplet architecture decision. That has not changed and must not.

Architecture-level DSE with an internalised thermal constraint is **demoted to future work with a
named obstruction** (`DIRECTION_FIXED_GEOMETRY.md`): a small geometric displacement does not give a
small coefficient perturbation once a material interface moves, and the 64 archive designs induce 64
distinct floorplan geometries with zero shared. The exact reuse band within a design class is
0.69-2.44 K against a model-form band of 0.25-1.06 K, so amortising across geometry costs one to ten
times the term the method exists to measure.

The direction is therefore **thermal-constrained mapping on a FIXED geometry**. One qualifier is
load-bearing and is easy to lose: `T = R p + a` is the **steady** affine map, so it answers questions
about a time-averaged power vector. A real time-scheduling claim -- ordering, release times, transient
peaks -- needs a state recursion `x_{t+1} = A x_t + B p_t + c`, which lives in
`CertiTherm/transient.py` and is a different round.

## Established (owners hold the numbers)

| what | owner |
| --- | --- |
| the affine structure and why the polytope machinery transfers across solvers unchanged | `REASONING_CHAIN.md` |
| model form against an independent FEM, one-signed, and its size against the frozen contract | `MODEL_FORM_AGAINST_AN_INDEPENDENT_SOLVER.md` |
| the FEM reference satisfies an analytical identity, residual predicted in advance | `FEM_ANALYTICAL_VERIFICATION.md` |
| the cell endpoint: 5 of 6 certify, the refusal is the tightest, the frontier no longer rests on block averages | `CELL_ENDPOINT_RESULT.md` |
| `gridN-avg` breaks thermal reciprocity, and what it costs the certifying quantity | `CertiTherm/reciprocity.py` |
| the archive's thermal column is not reproducible, six hypotheses refuted | `ARCHIVE_CENSUS_RESULT.md` |
| a lumped sink boundary is a sensitivity, not a correction | `LUMPED_BOUNDARY_SENSITIVITY.md` |

## Open, in the order they must be closed

### G0 -- provenance, and it is a precondition not a task

`HEAD` moved more than a dozen times during the analysis that produced this plan, and the
cell-endpoint run is recorded as not having bound its starting SHA. **No claim-grade run may start
from a moving checkout.**

**Bar to clear:** an isolated worktree at a pinned SHA; `make bootstrap && make check` green on
moe-server in that worktree; every result artifact carries the starting SHA, the input and config
digests, the binary digest and the exit status. Until then no number produced is attributable.

### G1 -- the honest trace

`THERMODSE_ENDPOINT_AUDIT.md` establishes that of the dissipated energy, DRAM (40.56 %) never reaches
HotSpot at all, NoC is spread **uniformly** over `io_*` -- which destroys the spatial information a
mapping decision would move -- and NoP is a single lumped column. Only the core term, 88.3 % of the
placed power, is spatially resolved.

**A mapping experiment on this trace measures the trace, not the mapping.** A cheap probe over the
resolved term was designed twice and withdrawn (`G1_MAPPING_LEVERAGE_WITHDRAWN.md`) because neither
of its outcomes would have changed this conclusion.

**Bar to clear:** compute, NoC, NoP and DRAM energy each placed and conserved, with the placement
justified against source rather than assumed; the energy ledger closing to the same zero residual the
audit already achieves; and the resulting power map differing from the current one by an amount that
is reported, not discovered later.

### G2 -- the quality separation pilot, NON-CLAIM

> **REPAIRED 2026-08-03, see `G2_REPAIR_THE_WINDOW_IS_ONE_DIMENSIONAL.md`. Do not run the version
> below.** It had three defects: the upper edge `e_total` exists in no source file, the lower edge
> `g` is unsourced, and the named "slack negative control" `arch_b`/resnet50 has a net margin of
> **0.143 K** under the corrected trace — it is the tightest surviving case.
>
> The repair collapses the window to one dimension. With `dist = L - T`, a candidate is a separator
> **iff** `margin + e_total <= dist < g`. So the window's non-emptiness is candidate-independent
> arithmetic (`g > margin + e_total`), and it is **not** the binding constraint: at `g = 3` the
> window is 1.5-2.7 K wide across the whole plausible `e_total` range. What binds is the population —
> **none of the six development points lies in the band**, which is `archive-census-v1`'s failure
> visible before the pilot rather than after it. G2 splits into `G2a` (screen for candidates with
> `dist` in the band, over a population wider than the development split) and `G2b` (the separator
> test, reported as the `(g, e_total)` region rather than a verdict at assumed constants).

### G3 -- only after G2 is GO

Migrate `CertiTherm/error_budget.py` into the production path. It is a tested prototype with **zero
production callers**; `thermal_constraints.py` still broadcasts the non-negative scalar
`ThermalFamily.error_k`. The migration is **not a field swap**: SAFE rows, REJECT specifications,
kernel subsets and collision witnesses are all derived from the constraint set and must be re-derived
under a new freeze, because a subset proved sufficient under a scalar maximum need not remain
sufficient once rows are relaxed by different amounts.

Then, and only then, H1: a one-sided within-cell bound. **A max of cell averages is not a bound on
the pointwise peak the limit refers to** -- `H^1(Omega)` does not embed in `L^infinity` in three
dimensions, so no amount of grid refinement closes it. The route with the best prospect is a
comparison-principle supersolution, which is one-sided and therefore matches what a fail-closed
certificate needs; a residual-based energy bound does not close it alone.

## Not to be reopened

Cross-geometry `R` reuse (H2); the 8 K archive mechanism (named at `564f699`, and the decision it
gated is answered without it); enlarging the held-out split; turning the reciprocity reporter into a
hard assertion; and mesh coarsening of the FEM far field, which was rejected on its own verification
after moving the peak by 29 % of the band.

## Standing rules this round has paid for

* **Read the assembly, not the parameter name.** `r_convec` is named like a lumped resistance and
  documented as sink-to-ambient; two rounds treated the name as the specification, built an exact
  lumped-node FEM to separate a term that does not exist, and withdrew a valid finding. One grep of
  `temperature_grid.c` settled it. Now guarded in code by `_assert_convection_is_distributed`.
* **A withdrawal is not automatically the safe direction.** A correction that only weakens a claim
  cannot manufacture a false positive, which is why it needs no pre-review -- but withdrawing on a
  false premise destroys a real finding and no fail-closed gate in this repository will catch it,
  because every one of them is built to stop the opposite error.
* **Propagate a reversal as hard as the withdrawal.** The withdrawal reached the index; the reversal
  did not, and for a day the index listed as established two numbers measured against a boundary
  condition HotSpot does not use. The index is what gets cited.
* **An experiment whose every outcome leads to the same next action should not be run.**

## Governance, currently behind

`ccfa.yaml` still reports stage `v7_transient_locality` with `active_contract:
docs/V6_DIRECTION_DECISION.md`, and `README.md` still leads with "thermal half withdrawn". Both
predate the fixed-geometry decision and the cell-endpoint result. **They should be synced before the
round is published, not before it continues** -- syncing a state machine mid-round invites the same
propagation gap this round just paid for, in the other direction.
