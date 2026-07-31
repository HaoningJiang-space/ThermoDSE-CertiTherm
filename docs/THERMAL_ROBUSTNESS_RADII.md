# EDYP-optimal chiplet DSE selects a design that is dominated on every robustness axis

RESULT 2026-07-31. Measured on the ThermoDSE dev registry (3 architectures x 3 packages x 2
workloads) using ThermoDSE's own latency, energy and yield outputs. No place-and-route, no
sign-off flow: everything here is computable at DSE time from a power map, a linear thermal
operator, and the registered yield model.

## The finding

ThermoDSE minimises EDYP = latency x energy / yield subject to a peak-temperature constraint. The
constraint enters as a pass/fail test on the NOMINAL power map. Nothing in the objective or the
constraint expresses how much power-model error the decision survives.

Two orthogonal directions of power-model error give two computable radii:

* **tau\*** -- uniform total-power under-prediction. Scaling `p -> (1+tau) p` gives
  `T = ambient + (1+tau)(peak - ambient)`, so `tau* = (floor - rise) / rise` per cell, minimised
  over cells. Closed form, no solver.
* **S\*** -- redistribution at a fixed total. The smallest per-block activity span at which some
  admissible map reaches a reject floor, by bisection on one LP per cell. Peer review supplied the
  structure: with `Delta_j = f_j - r_j.q` and `H_j = max{ r_j.z : 1.z = 0, |z| <= q }`,
  `S* = min_j Delta_j / H_j` -- a margin divided by a redistribution sensitivity.

Measured, `default` package:

| architecture | workload | nominal peak | tau\* | S\* | yield | EDYP |
| --- | --- | --- | --- | --- | --- | --- |
| arch_a | resnet50 | 321.89 K | 217.9% | 4.65 | 0.855 | 5.095 |
| arch_b | resnet50 | 324.60 K | 84.2% | 1.59 | 0.927 | **3.376** |
| arch_c | resnet50 | 322.12 K | 199.4% | 3.62 | 0.953 | 5.073 |
| arch_a | transformer | 324.99 K | 73.8% | 1.69 | 0.855 | 20.968 |
| arch_b | transformer | 329.05 K | **9.0%** | **0.18** | 0.927 | **13.579** |
| arch_c | transformer | 325.42 K | 63.6% | 1.20 | 0.953 | 17.942 |

**On both workloads EDYP selects arch_b, and arch_c dominates arch_b on every axis that is not
latency:** yield 0.953 > 0.927, thermal margin, redistribution robustness S\*, and total-power
robustness tau\*. On transformer the selected design sits 0.997 K from the reject floor, tolerates a
9% total-power under-prediction, and has the highest redistribution sensitivity in the registry;
the design it outranks tolerates 63.6%.

The mechanism is visible in the numbers rather than inferred: arch_b wins on LATENCY alone
(0.393 ms against 0.607 for resnet50, a 1.54x advantage) and loses on energy and yield. EDYP's
multiplicative form lets that latency win absorb a 2.8% yield loss, and the thermal constraint --
being a nominal pass/fail -- charges nothing for spending 90% of the margin.

## The selection actually changes, at a defensible uncertainty level

Peer review set the falsification gate: a ranking flip is not required and counting flips is the
wrong study. What matters is whether a declared robustness requirement changes the SELECTION, at an
uncertainty radius one can defend, under an uncertainty geometry that is not the one the effect was
discovered in, with non-negligible regret.

Declaring a total-power model accuracy `tau_req` and keeping only architectures with
`tau* >= tau_req`:

| workload | tau_req | robustly feasible | selection | cost of robustness | worst-case regret |
| --- | --- | --- | --- | --- | --- |
| resnet50 | 5–30% | a, b, c | unchanged (arch_b) | — | — |
| transformer | 5% | a, b, c | unchanged (arch_b) | — | — |
| transformer | **10%** | a, c | **changes to arch_c** | **+32.1% EDYP** | **+4.00 K** |
| transformer | 20% | a, c | changes to arch_c | +32.1% EDYP | +4.36 K |
| transformer | 30% | a, c | changes to arch_c | +32.1% EDYP | +4.73 K |

Ten percent is inside the accuracy an architecture-stage power model is normally credited with, so
this is not a flip hiding at an implausible radius. The geometry is the total-power band, which is
the one direction the redistribution model deliberately excludes -- so the effect is not an artifact
of the model it was found in. The regret is 4.00 K against a total power-driven rise of 10.9 K, or
37% of it. And the robust choice is also the higher-yield one, 0.953 against 0.927.

The honest other half: **resnet50 shows no disagreement anywhere up to 30%.** The effect is
workload-dependent, and one workload of two is not a general claim.

## Why area is the shared variable

The registered yield model is `Y(A) = (1 + A D0 / alpha)^(-alpha)` with `D0 = 0.08 cm^-2`,
`alpha = 10` at 14 nm (`ThermoDSE/core/gen_hw_setting.py`). Yield falls with die area; power density
and therefore peak temperature fall as area grows. **Area is the variable both pull on, in opposite
directions**, and EDYP multiplies them.

The registry's three dev architectures differ exactly in how they cut it:

| architecture | tile grid | cut | dies | total area | per-die area | yield |
| --- | --- | --- | --- | --- | --- | --- |
| arch_a | 7 x 3 | 1 x 1 | 1 | 2.628 cm^2 | 2.628 | 0.812 |
| arch_b | 4 x 5 | 2 x 1 | 2 | 2.804 cm^2 | 1.402 | 0.895 |
| arch_c | 4 x 4 | 2 x 2 | 4 | 3.928 cm^2 | 0.982 | 0.925 |

More dies buy yield and cost total area through D2D overhead. What they do to the thermal margin is
NOT monotone in die count -- arch_b, with two dies, has less margin than either the one-die or the
four-die design -- which is why the thermal side has to be measured rather than reasoned from the
partition.

## Correction 2026-07-31: two different radii were reported under the name `beta*`

`geometries.py:radius_l1` solves the exact L1 transfer body `|p - q|_1 <= 2 b Q` with the lifted
program `p = q + u - v`. `architecture_sweep.py:radii` and `threshold.py` instead measure the **box**
`|p_i - q_i| <= b Q`, which is an L-infinity ball and a strict **superset** — it lets every block
take the full allowance at once, admitting an L1 distance of `n b Q` rather than `2 b Q`. On
`arch_a`/`default`/`resnet50` the box reaches a reject floor at **2.637 %** where the exact L1 body
needs **4.1 %**. Those are two quantities, and the 0.5–4.3 % range quoted above is the L1 one.

The box radius is now `epsilon_star` and the L1 one keeps `beta_star`. The consequence for the
certified observation requirement is more serious and is recorded in
`docs/BLIND_DIRECTION_BOUND.md`: a **lower** bound on minimum observation cost proved on a superset
does not transfer to the subset, so the 1440 reported at "5 % relocation" is a bound for the
deviation set, not for relocation. `CertiTherm/measurements.py` now provides both sets under names
that say which is which, and the inscribed box `2 b Q / n` is the one whose bounds transfer.

## The objective is not invariant to the yield composition, and the radii are

`ThermoDSE/core/chiplet_eva.py:162-165` composes the yield term of EDYP as an area-weighted
arithmetic **mean** of the per-die yields. The weights sum to one over that Cartesian double loop,
so it is a genuine weighted mean — and under a refinement of a fixed tile grid every child die is
smaller than its parent while `Y` decreases in area, so the mean can only **rise** as the design is
cut, at any parameter values. Nothing in it grows with the die count.

That is a statement about the objective, not an accusation about the implementation. The canonical
chiplet cost model (Chiplet Actuary, DAC 2022) uses the *same* per-die negative-binomial yield
(`exploration.py:51`) and then composes it two ways, neither an average: yield as a per-die cost
divisor under known-good-die screening (`chip.py:50`), and an assembly loss that is
**multiplicative** in the chip count (`package.py:209`, `y2 = bonding_yield ** chip_num()`), with
wasted material scaling as `1/(y2 y3) - 1`. The count-dependent penalty is exactly the term a mean
cannot have, and it is why that paper finds a die-area *crossover* rather than a monotone preference
for more chiplets.

`research/triangle/robustness/yield_composition.py` reports the same designs under all three
assumptions from the recorded die geometry, and refuses unless its recomputed mean reproduces the
evaluator's own `die_yield`. The point is not that one composition is correct — that needs
fabrication, test and redundancy assumptions this project does not have — but that **the preferred
chiplet count is not invariant across them**, so it cannot be certified from the objective value.

`tau*` and `epsilon*` are computed from the power map and the linear thermal operator alone: no
yield model, no cost model, no latency. Whatever a reader believes about composition, the radii are
unchanged.

## What this does NOT say

* **tau\* and S\* rank identically to the nominal peak on all 18 dev instances.** Zero inversions
  among same-workload, same-package pairs. The claim "thermal-aware DSE selects on the wrong
  statistic" is NOT supported by this registry: the nominally cooler design also happens to
  concentrate power more slowly. What IS supported is that the SPREAD is large and invisible to the
  objective -- 9.0% against 73.8% on the same workload -- and that EDYP's selection is dominated on
  the non-latency axes.
* **The reject floor is not the 330 K limit.** These radii are measured against
  `limit + margin - error - ambient`, the registered fail-closed threshold. "The limit is
  unreachable" would need a separate raw-temperature statement; what is established is that no
  SAFE/REJECT collision exists.
* **The uncertainty models are stress tests, not validated power-error models.** `S*` fixes the
  workload total exactly, which excludes systematic under-prediction -- peer review's point, and the
  reason `tau*` is reported beside it rather than instead of it. Independent per-block intervals
  admit combinations no workload phase produces; leakage does not fall to zero at large spans; a
  single steady-state map ignores phases and temperature-dependent leakage feedback.
* The power maps come from a ThermoDSE evaluator with documented defects (`e_tot` subtracts compute
  energy, NoP energy is smeared over the interposer, HotSpot leakage feedback is disabled).
* **"Inside the evaluator's error band" is not an argument available here, in either direction.**
  An earlier draft dismissed sub-2 % EDYP differences by citing the sibling study's 0.5–5 % plateau.
  Those three defects are directional modelling biases, not a calibrated error distribution, and a
  plateau measured on a different registry is not an uncertainty interval for these points. Peer
  review was right that it cuts both ways: the same argument that stops EDYP from discriminating
  also stops any claimed cancellation from being physically meaningful. Small EDYP differences are
  therefore reported as **unresolved**, never as equal and never as a priced difference.
* A design-space statement here is a **finite-sample** statement. "No design in the swept space
  survives a 1 % requirement" is a fact about the points generated, not about the parameterised
  space, which was not exhausted.

## The observation requirement is a function of the uncertainty set

`docs/BLIND_DIRECTION_BOUND.md` reports a certified lower bound of 1312.0 on the minimum-cost
observation set for arch_a/default/resnet50 -- read as "at least 164 of 237 blocks require
post-route per-block extraction". **That headline is withdrawn as a physical requirement.** Under
per-block activity-bounded redistribution the reject floor is unreachable through span 1.0, no
collision exists, and the requirement is zero.

Both numbers are correct for their own uncertainty set, and the pair is the more informative result:

> Under unrestricted nonnegative redistribution preserving the workload total, the certified
> observation requirement is 1312. Under redistribution bounded by a per-block activity span through
> s = 1, it is zero.

That is what makes the radii the primary quantity. The observation requirement is not a property of
the design alone; it is a property of the design and the power-model uncertainty one is willing to
assume, and the radii say where the transition lies.
