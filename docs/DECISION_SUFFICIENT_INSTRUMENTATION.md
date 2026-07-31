# The chiplet-count decision is not identifiable from the objective, and here is what is

RESULT 2026-07-31. Development registry plus freshly generated architecture points; the frozen
held-out split was not opened. No place-and-route, no sign-off flow: everything here is computable at
DSE time from a power map, a linear thermal operator, and a stated manufacturing assumption.

Method in `CertiTherm/`, `research/triangle/robustness/{l1_body,threshold,yield_composition,
architecture_sweep}.py`. Pinned by 651 tests. Nine adversarial peer-review rounds; the corrections
that survived review are recorded here, including the two that withdrew earlier headlines.

---

## 1. The problem with ranking chiplet counts by a scalar yield

Thermal-aware chiplet DSE minimises an objective of the form `latency x energy / yield` under a
peak-temperature constraint. The chiplet **cut** — how the compute area is divided into dies — is
the decision that distinguishes a chiplet design from a monolithic one, and yield is the term that
is supposed to price it.

**Proposition (refinement-monotone aggregates cannot price chiplet count).** Let a design be cut into
dies of areas `a_1..a_n` summing to `A`, let `Y` be any strictly decreasing function of die area, let
`c >= 0` be a per-die overhead, and let the yield term be the area-weighted arithmetic mean

    G = sum_i (a_i / A) * Y(a_i + c)

Split one die of area `a` into `a'` and `a''` with `a' + a'' = a`. Then

    (a'/A) Y(a'+c) + (a''/A) Y(a''+c)  >  (a/A) Y(a+c)

since both new terms exceed `Y(a+c)` while the weights still sum to `a/A`. **`G` strictly increases
under every refinement, at every parameter value.** An objective dividing by `G` therefore inherits
no count risk from its yield term: whatever trade appears must come from the other factors, and the
yield term can only ever argue for cutting further.

This is a property of the **aggregation**, not of any one tool. It is the thing to check in any
thermal-aware chiplet DSE that reports a scalar yield. `ThermoDSE/core/chiplet_eva.py:162-165` is one
instance of it — the weights sum to one over that Cartesian double loop, so it is a genuine weighted
mean — and the proposition is executed against the implementation in
`CertiTherm/tests/test_yield_composition.py` rather than argued in prose.

The two standard alternatives fail refinement-monotonicity, which is exactly why they can price the
decision. The canonical chiplet cost model (Chiplet Actuary, DAC 2022,
`github.com/Yinxiao-Feng/chiplet-actuary`) uses the same negative-binomial per-die yield
(`exploration.py:51`) and then composes it as a per-die **cost divisor** under known-good-die
screening (`chip.py:50-51`, `N_KGD = N_die_total * die_yield`; `chip.py:62-63`,
`cost_KGD = Cost_Wafer_Die / N_KGD`) together with an assembly loss that is **multiplicative in the
chip count** (`package.py:209`, `y2 = bonding_yield ** chip_num()`; `package.py:214`,
`cost_wasted_chips = (...) * (1/(y2 y3) - 1)`).

Two qualifications peer review required. The count-multiplicative bonding term appears in that
model's organic-substrate and chip-last paths, not in every path (`chip_last == 0` does not use
`y2`). And that model carries several other count-dependent costs — wafer utilisation, scribe loss,
bump and interposer area, test, NRE — so "the missing bonding term is *why* it finds a crossover"
would be overstated. The defensible statement is narrower and still sufficient: **an arithmetic-mean
yield aggregate cannot itself create the die-yield-versus-chip-count trade, and the standard models
contain mechanisms that can.**

## 2. Measured: the preferred chiplet count moves with the composition

Computed exactly from die geometry now recorded in every capture (`die_h_list_m`, `die_w_list_m`,
`nop_area_m2`), so unequal dies are handled exactly rather than through a `Y_mean ** n` shortcut that
is only valid for cuts dividing the tile grid evenly. A **fatal self-check** requires the recomputed
area-weighted mean to reproduce the evaluator's own `die_yield`; it does, exactly, and the probe
refuses to report anything if it does not — because the product and KGD columns are built from the
same edge lists and a geometry misread would corrupt them with no other symptom.

`4x4` tile grid, `resnet50`, equal dies, cut `1 -> 2 -> 4`:

| dies | `Y` mean (evaluator) | `Y` product | KGD silicon m²/good system | `E·D` |
| --- | --- | --- | --- | --- |
| 1 | 0.882492 | 0.882492 | 1.7997e-04 | 4.4335 |
| 2 | 0.940892 (**+6.6 %**) | 0.885277 (+0.32 %) | 1.6568e-04 (**−7.9 %**) | 4.7363 |
| 4 | 0.970015 (**+9.9 %**) | 0.885348 (+0.32 %) | 1.6361e-04 (**−9.1 %**) | 4.9177 |

The reported yield gain from cutting is **+9.9 %**; under the all-dies-good product it is **+0.32 %**.
Carried into the objective, the preferred cut differs: the product composition prefers the monolithic
die decisively, the KGD silicon proxy prefers `n = 2`.

**The phase boundary, so this is decision analysis rather than a disagreement of proxies.** Fixing
one model and varying one manufacturing-policy parameter, two cuts `m < n` tie under the KGD proxy at

    y_b* = ( E·D(n) · S(n) / E·D(m) · S(m) ) ^ (1 / (n - m)),    S(n) = sum_i (a_i + c) / Y(a_i + c)

in closed form. `yield_composition.py` reports `y_b*` for every adjacent pair against the 0.99
organic-substrate bonding yield the cost model registers, so a reader can see whether the boundary
sits inside the plausible range or far outside it.

**What this is not.** `kgd_silicon` is an explicitly defined silicon-area proxy, not that paper's
cost: it omits wafer utilisation, scribe loss, bumps, interposer and substrate cost, test and NRE.
The `product` column now also carries bonding loss (`yield_product_with_bonding`) so that comparing
it against the KGD column isolates the **screening policy** instead of changing screening, bonding,
units and normalisation at once — peer review found the earlier comparison confounded in exactly
that way.

**Small objective differences are reported UNRESOLVED, never as a price.** An earlier draft dismissed
sub-2 % EDYP differences by citing a sibling study's 0.5–5 % plateau. That is withdrawn: the
evaluator's three documented defects are directional modelling biases, not a calibrated error
distribution, and the argument cuts both ways — it removes the objective's discrimination and any
claimed cancellation together.

## 3. The thermal robustness radii do not depend on any of this

`tau*` (uniform total-power under-prediction) and the redistribution radii are computed from the
power map and the linear HotSpot operator **only**: no yield model, no cost model, no latency.
Whatever a reader believes about composition, they are unchanged. On the twelve-point cut sweep the
redistribution radius rises monotonically with the die count in **4 of 4** tile grids, while the
reported objective moves by at most 2.8 % across the same comparisons.

That is the substantive claim of this section: the quantity that is invariant to the modelling choice
which flips the baseline's answer is also the quantity that orders these designs stably.

## 4. Three uncertainty geometries, and which conclusions may be carried between them

This is where an earlier version of this work was wrong twice, so the rule is stated before any
number.

| set | definition | relation to the L1 body |
| --- | --- | --- |
| deviation | `|p_i − q_i| <= b·Q` for every block, total conserved | **superset** |
| L1 relocation | `|p − q|_1 <= 2 b·Q`, total conserved | the physical statement |
| inscribed | `|p_i − q_i| <= b·Q / floor(n/2)`, total conserved | **subset** |

The L1 body **is** a polytope over `p` alone — `sum_{i in S}(p_i − q_i) <= b·Q` for every subset `S`,
once the total is conserved, with a one-line separation oracle. The obstacle is an exponential facet
count, not impossibility; a compact lifted `(p, t)` encoding also exists. An earlier docstring claimed
it could not be written over `p` at all, contradicting this repository's own `l1_body.py`.

**Containment transfers asymmetrically, and this is the load-bearing rule:**

| claim | from a SUBSET | from a SUPERSET |
| --- | --- | --- |
| a REJECT map exists | **transfers** | no |
| a coarse-blind SAFE/REJECT pair exists | **transfers** | no |
| minimum observation cost is at least `c` | **transfers** | no |
| no REJECT map exists | no | **transfers** |
| coarse reports suffice for every map | no | **transfers** |
| no measurement is needed | no | **transfers** |

Existence and lower bounds travel **up** from a subset; universal safety and upper bounds travel
**down** from a superset. Use the outer set to prove a design safe and the inner set to prove
instrumentation necessary, and the true answer is bracketed from both sides.

**Two withdrawals follow from that table.**

*A certified bound of 1440 was reported at "5 % relocation".* It was computed on the box implied by a
transfer budget, which is the **superset**, while the quantity is a **lower** bound on minimum
observation cost — which does not travel down. The number is a bound for a per-block deviation set
and is no longer quoted as a relocation requirement anywhere. See `docs/BLIND_DIRECTION_BOUND.md`.

*"No measurement needed under relocation" was read off the inscribed box.* Absence of a REJECT map on
a subset proves nothing about the set containing it, and the concentrated relocations the inscribed
box drops — the whole budget onto one block — are precisely the ones that make a hotspot, so the
omission was adversarially selected against the conclusion. Withdrawn as an L1 claim.

Neither withdrawal costs the result, because the reachability breakpoint is computable **exactly**.

## 5. What is established, per uncertainty model

### Model A — bulk relocation (`|p − q|_1 <= 2 b Q`)

The first tier needs only reachability, and reachability is a maximisation of one linear form. No
approximation, no transfer argument, no surgery on the certified path — and **no solver**: nothing
bounds `p` from above inside this body, so all received power goes to the single largest-coefficient
block while donations are taken cheapest-first capped by each block's own power, making the gain
increasing, concave and piecewise linear in the transferred amount. The smallest amount reaching a
floor is therefore read off directly.

    beta* = min over reject cells of  t*(cell) / Q,
    t*(cell) = smallest t with  sum over donors ascending in r of min(q_i, .) (r_max - r_i)  >=  floor - r.q

The lifted LP remains the oracle. The two implementations are deliberately unlike — one inverts a
sorted greedy, the other solves a linear program — and a randomised test requires them to agree,
because a second implementation that merely reproduced the first's bug would agree too.

| candidate | workload | exact `beta*` | reading |
| --- | --- | --- | --- |
| arch_a | resnet50 | 4.133 % | no measurement needed below 4.133 % relocation |
| arch_b | resnet50 | 2.144 % | |
| arch_c | resnet50 | 4.035 % | |
| arch_a | transformer | 1.540 % | |
| arch_b | transformer | **0.548 %** | the tightest design in the registry |
| arch_c | transformer | 1.497 % | |

**The containment holds on the real instances, not only on the unit fixture.** The deviation box is a
superset of the L1 body, so it must reach a reject floor no later — measured, 2.637 ≤ 4.133,
1.573 ≤ 2.144, 3.376 ≤ 4.035 and 0.778 ≤ 1.540. Three independent implementations (a box greedy, a
lifted LP, an inverted transfer greedy) agree in the order their containments force, which is the
check that would have caught the two withdrawn claims before they were written down.

Above `beta*` the tier is **OPEN** under this model: deciding whether coarse reports suffice needs the
collision oracle over the exact body, which means either the lifted program or lazy generation of the
subset rows inside the collision LP. Both are real changes to the certified path and neither is done.
Reported as open rather than approximated.

### Model B — independent per-block deviation (`|p_i − q_i| <= b Q`, total conserved)

A superset of Model A, so its safety verdicts also hold under relocation, and a legitimate uncertainty
model in its own right: each block's power is independently mispredicted by at most a fraction of the
chip total. Here the full three-tier structure is measured.

All six instances, probed on the declared ladder `{0.5, 1, 2, 5, 10, 25} %`:

| candidate | workload | `e_reach` (proof) | per-block established at | gap left UNRESOLVED |
| --- | --- | --- | --- | --- |
| arch_a | resnet50 | 2.637 % | 5 % | 2.637 – 5 % |
| arch_b | resnet50 | 1.573 % | 5 % | 1.573 – 5 % (2 % unresolved) |
| arch_c | resnet50 | 3.376 % | 10 % | 3.376 – 10 % (5 % unresolved) |
| arch_a | transformer | 0.778 % | 5 % | 0.778 – 5 % (1 %, 2 % unresolved) |
| arch_b | transformer | **0.196 %** | 5 % | 0.196 – 5 % (0.5, 1, 2 % unresolved) |
| arch_c | transformer | 1.198 % | 5 % | 1.198 – 5 % (2 % unresolved) |

Read as a decision procedure, and note that only two of the three tiers are established:

    b < e_reach     NO measurement at all. Every admissible map is SAFE, the empty plan certifies,
                    and this direction is a proof rather than a measurement. ESTABLISHED, exactly,
                    for every instance.
    b >= 5 % (10 %) POST-ROUTE PER-BLOCK extraction is required. A SAFE/REJECT pair exists that the
                    entire coarse library reads identically, so no plan built from it certifies at
                    any price. ESTABLISHED by an exactly recomputed witness.
    in between      UNRESOLVED.

**The middle tier is defined but was never established.** A "coarse reports suffice" verdict requires
the collision search to complete AND every returned collision to be separated by a coarse action
under exact recomputation. That verdict (`separable`) does not appear once in the six ladders: every
probe above `e_reach` came back either `blind` or `unresolved`. So this registry supports a two-sided
BRACKET on where per-block extraction becomes necessary — not needed below `e_reach`, needed at 5 %
— and reports the interval between as unresolved rather than as a coarse-sufficient window. An
earlier draft of this section wrote the middle tier as measured; it is not.

This also explains an earlier isolated observation. A certified requirement of 0 at `b = 2 %` and
1440 at `b = 5 %` on `arch_a`/`default`/`resnet50` looked like a discontinuity; it is simply the
bracket, `e_reach = 2.637 %` below and an established blind pair at 5 % above, straddled by those two
probes.

**`UNRESOLVED` is a first-class verdict.** A collision search that times out, dies, or returns only
feasibility-boundary artifacts establishes nothing, and must not advance the "coarse suffices"
endpoint — doing so widens the interval over which cheap instrumentation is claimed sufficient, which
is the fail-open direction. Peer review found four such steps in the first version of this probe; all
four now refuse.

## 6. Scope, and what would refute this

* Development registry and freshly generated development points. The frozen held-out split was not
  opened; opening it to enlarge a sample is what the protocol exists to prevent.
* A design-space statement here is a **finite-sample** statement about the points generated, not
  about the parameterised space, which was not exhausted.
* Power maps come from an evaluator with documented defects (`e_tot` subtracts compute energy, NoP
  energy is smeared over the interposer, HotSpot leakage feedback is disabled, IO/PHY static power is
  absent). These affect `E·D` under **all three** compositions equally and are not corrected here.
* The thermal family is HotSpot-only and linear, with a frozen 0.01 K two-sided error band folded
  one-sidedly into every SAFE/REJECT row. Spatial correlation of power-model error, transient peaks
  and leakage-temperature feedback are outside the certificate.
* The uncertainty sets are stress tests, not validated power-error models. Model B admits per-block
  combinations no workload phase produces; Model A fixes the total exactly, which excludes systematic
  under-prediction — that is why `tau*` is reported beside it rather than instead of it.
* **Cheapest refutation.** Sections 1 and 2 fall if the recomputed area-weighted mean stops
  reproducing the evaluator's `die_yield` (the probe refuses in that case), or if a refinement is
  exhibited that lowers the mean. Section 5 falls if a REJECT map is exhibited below a reported
  `beta*` under the exact L1 budget, or if a coarse-blind pair below the established
  per-block radius survives exact recomputation of its cut. Section 5's middle tier is refuted the
  moment a `separable` verdict is produced anywhere, which would turn the bracket into a window.
