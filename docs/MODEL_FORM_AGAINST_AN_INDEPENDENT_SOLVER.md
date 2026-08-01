# The model-form error, measured against an independent solver

> **THE BAND IS PARTLY THE BOUNDARY REALISATION, NOT MODEL FORM.** Measured 2026-08-02: driving the
> sink towards the isothermal limit -- which is what HotSpot's *lumped* sink-to-ambient node is --
> moves the FEM peak **-0.734 K** (sink conductivity x10, energy balance 2.07e-07, admissible; x100
> and x1000 were refused by the gate at 2.4e-06 and 5.3e-06, with x1000 reading -0.834 K before it
> was refused). The measured model-form band is 0.251-1.061 K in the direction "FEM hotter than
> HotSpot". **A boundary-realisation term of the same sign and comparable magnitude sits inside it**,
> so the band as reported is an upper bound on model form and not an estimate of it. The other two
> declared equivalences are safe: source depth moves the peak +0.0201 K and the void filler +0.0000 K.
>
> **PROVISIONAL pending the cell-level certificate.** Every number below is computed on
> **block-average rows**, and on this same FEM a unit impulse puts the domain maximum **2.06 K** above
> the hottest block average (0.18 K inside HotSpot). That term is reported here and **not** folded
> into the certificate. The tightest point on the frontier has **0.31 K** of slack, so folding it in
> can be expected to break at least that point. **Do not quote `+32.1 %` or "5 of 6 certify" outside
> this repository until the cell-level certificate lands.** The three independent routes that agree
> on +32.1 % share the block-level assumption, so their agreement does not cover this gap.

RESULT 2026-08-01. Development split (`arch_a`, `arch_b`, `arch_c`) x 2 workloads, `default`
package. The three held-out splits are untouched.

Every error band this project had measured was **within HotSpot** — `block` against `grid128`,
`grid128` against `grid512`. Grid refinement bounds HotSpot's own discretisation error and cannot
bound its model-form error, because every member of that family shares the same structural
assumptions and the whole family can agree while being wrong together in the same direction. This is
the first measurement against a solver that does not share them.

## Why an FEM reference is cheap, which is a property of the physics

Steady conduction with temperature-independent conductivity and Robin cooling is **linear in the
power vector**, so the FEM map is affine, `T = R p + a`, exactly like HotSpot's. Three consequences,
none of which is an engineering trick:

* The operator is built by `n + 1` impulse solves, not by sampling power maps.
* **The stiffness matrix does not depend on the power map**, so all `n + 1` solves share one
  factorisation. On one A800 through cuDSS: **182 solves in 30 s** for a 181-block architecture.
* **`one_sided_containment_bounds` and `peak_over_polytope` apply unchanged.** The whole polytope
  machinery built for cross-grid comparison transfers to cross-solver comparison without
  modification, because linearity is a property of the PDE and not of HotSpot.

3D-ICE could not supply this reference: its layer spec carries no per-layer footprint while the chip
dimensions are global, so a package with die, spreader and sink at three different footprints cannot
be represented, and truncating them inserts ~2.57 K of series copper against a 0.095 K margin.
DOLFINx can, because `BoxRegion` carries explicit three-dimensional bounds per region.

## The result: model form dominates discretisation, and it has a sign

Polytope-wide, per row, one-sided, at a declared per-block activity span of 0.30:

| architecture / workload | refinement tail `grid128 -> grid512` | **model form `grid512` vs FEM** | ratio |
| --- | --- | --- | --- |
| `arch_a` / resnet50 | 0.051 K | **0.535 K** | 10.4x |
| `arch_a` / transformer | 0.084 K | **0.984 K** | 11.8x |
| `arch_b` / resnet50 | 0.225 K | **0.612 K** | 2.7x |
| `arch_b` / transformer | 0.339 K | **1.061 K** | 3.1x |
| `arch_c` / resnet50 | 0.186 K | **0.251 K** | 1.4x |
| `arch_c` / transformer | 0.300 K | **0.467 K** | 1.6x |

**Model form is 1.4 to 11.8 times the complete refinement tail.** Refining the grid is not where the
error is. This was predicted from first principles before the run: HotSpot's spreader and sink are a
lumped resistance network that decomposes spreading into a centre block plus peripheral trapezoids,
which is a *structural* assumption no amount of grid refinement can expose, while within the 150 um
die at a 130:1 aspect ratio a 2-D lateral network is a good approximation.

**The disagreement has one sign.** At the nominal power map, `T_FEM - T_grid512` is
**+0.20 to +0.86 K on all six points** — the FEM reads hotter everywhere. HotSpot **systematically
underestimates**, which is independently what Fetis and Seznec reported (WDDD 2006). It is also the
worst direction for a certificate: an optimistic thermal model produces optimistic feasibility.

Against the frozen `0.01 K` contract the model-form term is **20-86x at the nominal map** and
**25-106x over the polytope**. The contract measures direct HotSpot replay against impulse
superposition — a linearisation residual of one operator — and never contained this term at all.

## The re-anchored frontier, which is the deliverable

Certificate: `sup_p T_grid512(p) + sup_p [T_FEM(p) - T_grid512(p)] <= 330.0 - 0.05 - 0.01`. The
model-form band is folded in **one-sidedly**, so it can only make certification harder. The
linearisation term is retained rather than replaced, because it is a different error source.

| per-block activity span | resnet50 | transformer | cheapest certified | price |
| --- | --- | --- | --- | --- |
| 0.05 - 0.10 | 3 of 3 | 3 of 3 | `arch_b` (the EDYP optimum) | **+0.0 %** |
| **0.20 - 1.20** | 3 of 3 | **2 of 3** | `arch_c` (transformer) | **+32.1 %** |

**The frontier is non-empty: 5 of 6 points certify against the independent solver**, and the price of
robustness is **+0.0 %** for resnet50 and **+32.1 %** for transformer. The breakpoint moves from a
span of 0.36 (HotSpot-only budget) to between 0.10 and 0.20 once model form is budgeted, and the
answer is then **stable across a 6x range of declared power-model accuracy**.

`+32.1 %` is now the same figure from **three independent routes**: forward budgeting with
within-HotSpot bands, a backward robustness radius (`tau*`), and forward budgeting with an
independent-solver model-form band. The three share the architecture switch (`arch_b -> arch_c`)
as well as the price.

## What was checked, because a mismatched stack would have looked like model-form error

`_assert_matches_hotspot_inputs` parses the real template and materials file and refuses on drift.
Per solve: energy balance **4.0e-9**, impulse power error **4.5e-14 W**, zero-solve offset from
ambient **4.9e-10 K**. Geometry is validated before any GPU time: every mesh cell owned by exactly
one region, all 181 die blocks owning cells.

**One real geometry error was caught by peer review before the first run.** The TIM was sized to the
spreader; `temperature_block.c:119` builds one interface node per floorplan unit from
`flp->units[i].width/height`, so HotSpot's interface layer is the **die** footprint. A
spreader-sized TIM would have laid a 20 um k=4 sheet under the whole overhang, changed the spreading
path, and the difference would have been reported as HotSpot's model-form error.

**Energy balance is a numerical check, not a physics-matching check.** A closed but wrong geometry
conserves energy exactly. What guards the matching is the input parsing above plus the explicit
ledger of what was assumed equivalent.

## Two corrections from peer review, neither of which moved a number

**The class-total constraints were being dropped at the call site.** `activity_bounded_power_space`
returns a `PowerPolytope` carrying per-content-class aggregate caps in `a_ub`/`b_ub`, and the callers
passed only `lower_w` and `upper_w`. Maximising without them bounds a LARGER set, which is sound --
it can never certify something that should be refused -- but it inflates every band and depresses the
certified fraction. The bound now solves the full polytope by LP.

**The measured effect is zero, and there is a reason.** `upper = min(placed * (1 + span),
content_upper_bounds) <= placed * (1 + span)`, so each class's members already sum to at most
`class_total * (1 + span)`, which is exactly `b_ub`. The caps are implied by the box. Measured:
`b_ub - a_ub @ upper` is zero to machine precision at spans 0.05, 0.30 and 1.20, and the LP agrees
with the greedy to **1.07e-9 K** across every peak and band on the development split. This is a
property of the current construction and not a theorem about the method, so it is pinned by a test
whose failure message says the LP path has become load-bearing.

**The FEM mesh was sized by the package, not by the die.** The box is 60 mm on a side regardless of
how large the die is, so a small die gets proportionally fewer cells. Refining it on the smallest
archive die (5.72 x 11.88 mm) moves the model-form band **0.6093 -> 0.6673 -> 0.6905 K** for cell
counts 80 -> 160 -> 320 per axis, contracting by a factor of 2.5 per doubling (observed order
`p ~ 1.32`, Richardson limit ~0.706 K). **A coarse mesh UNDERSTATES the band**, which makes
certification easier, so this is the optimistic direction and it was corrected before any verdict
was read. The preregistration fixes the FEM tolerances but not the mesh, so raising it is not a
protocol change; and because it can only enlarge the band it could never have been a rescue.

## What this does NOT establish

* **3 architectures, 2 workloads, one package.** Six points.
* **The FEM is a reference, not ground truth.** Its mesh convergence is now measured on one design
  (order ~1.32, Richardson tail ~0.015 K at the finest mesh) but not on all of them; its
  operator NPZ carries `error_k = NaN` deliberately, so any attempt to certify *against* it through
  the normal machinery refuses rather than silently succeeding.
* **Three assumptions are declared equivalent, not matched**, and each is falsifiable by a
  sensitivity run not yet done: block power volumetric over the full die thickness (matching
  HotSpot's lumped element, not the physically thin active layer); the void outside each plate
  filled with still air rather than a stepped domain; and `r_convec` realised as a uniform Robin
  coefficient over the sink top rather than as HotSpot's lumped sink-to-ambient node.
* **The rows are block averages.** On the FEM, a unit impulse puts the domain maximum **2.06 K**
  above the hottest block average, so a certificate over block averages does not imply one over the
  physical peak. This is the independent-solver analogue of the 0.18 K understatement measured
  inside HotSpot, and it is reported rather than folded in.
* **The activity span is declared, not measured.**
