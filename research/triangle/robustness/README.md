# Robustness probes

Two generations live here and they are not interchangeable.

## Current — parameterised, documented, reproducible

| file | what it produces |
| --- | --- |
| `l1_body.py` | the exact L1 relocation body: reachability by lifted LP, and the radius in closed form |
| `grid_convergence.py` | `grid256` against the certified family, the study that found the operators unconverged |
| `per_model_radii.py` | the radius per thermal operator, which showed the ordering was one operator's artefact |
| `chiplet_cost.py` | transcribed organic-substrate recurring cost, conformance-checked against the upstream program |
| `cost_crossover.py` | the crossover in bonding yield, exact root plus a joint six-factor sweep |
| `yield_composition.py` | the three yield compositions and the refinement-monotonicity proposition |
| `heldout_verdict.py` | the eight preregistered predictions, scored |
| `budget_impact.py` | whether budgeting the discretisation error moves any robustness argmax |
| `threshold.py` | the instrumentation tier as a function of the uncertainty radius, per geometry |
| `yield_composition.py` | the three yield compositions from recorded die geometry, and the bonding phase boundary |
| `architecture_sweep.py` | fresh architecture points and their radii, over three declared grids |
| `relocation_radii.py` | adds the exact relocation radius to a sweep captured before it existed |

Each takes its artifact root and options on the command line, states its usage in its docstring, and
is exercised by tests under `CertiTherm/tests/`.

## Deleted

`sstar.py`, `taustar.py`, `regret.py`, `yieldprice.py` were removed on 2026-08-01. They produced
`S*`, `tau*`, the selection-change table and the yield-price table quoted in
`docs/THERMAL_ROBUSTNESS_RADII.md`, and they were kept through an earlier cleanup on the grounds
that deleting the sole implementation behind a published number is a provenance hole.

**That reason expired when the numbers did.** Every claim they supported belongs to the thermal half
withdrawn in `docs/BUDGETED_REGISTRY_DOES_NOT_CERTIFY.md`: with the operator's discretisation error
budgeted, the registry those tables describe largely stops certifying, and the tables are recorded
as withdrawn rather than as results. Keeping four unrunnable scripts -- each hardcoding an absolute
path to one scratch directory on one host, none taking arguments -- to reproduce withdrawn numbers
is not provenance, it is clutter. The withdrawal itself, and the measurements behind it, stay in
`docs/`.

`attr.py`, `edyp.py`, `reachcheck.py`, `transition.py` were **deleted on 2026-07-31**. They shared
the hardcoded path and had no docstring, usage line or CLI, and their capability is now covered:
`reachcheck` and `transition` both maximised `r . p - floor` over a polytope's reject cells, which
`threshold.reject_reachable` and `l1_body` do properly and with the geometry named; `attr` measured
the class-aggregate attribution, whose corrected conclusion is recorded in the radii document; `edyp`
printed the EDYP domination table, which is in the same document and which
`yield_composition.py` now derives from geometry instead of from a composed scalar. Their findings
stay in `docs/`; only the unrunnable scripts are gone.
