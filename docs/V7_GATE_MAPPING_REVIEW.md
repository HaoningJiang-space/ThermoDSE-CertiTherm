# V7 stack mapping v1 — review outcome: REJECTED, do not run

Reviewed before use, as the preregistration requires. The mapping specification
`docs/registration/v7_gate_stack_mapping.json`
(`sha256 b1e35686cf5be8a2d38a728d6d60d5a22ef6863f20dad32397f3fd665cab885a`) is **not** to be used.
It is kept unedited, because the whole point of hashing it is that it cannot be revised in place;
a corrected mapping is a new preregistered attempt with its own hash.

The gate itself is unaffected and is now *more* likely to be answerable than when it was
preregistered — see §3.

## 1. The finding that would have invalidated the run

3D-ICE passive layers share one global footprint, so v1 put HotSpot's spreader (50 mm square) and
sink (60 mm square) at the **chip** footprint of 21.6962 × 17.95 mm. Their one-dimensional
through-thickness resistance therefore rises:

| slab | R at chip footprint | R at true footprint | excess |
| --- | ---: | ---: | ---: |
| spreader, 1.0 mm Cu | 6.419 mK/W | 1.000 mK/W | 5.419 mK/W |
| sink, 6.9 mm Cu | 44.294 mK/W | 4.792 mK/W | 39.502 mK/W |
| | | **total** | **44.921 mK/W** |

At the instance's 57.18 W average dissipation that is **≈ 2.57 K hotter**, ignoring lateral
spreading, which makes the true gap larger rather than smaller. The steady margin under test is
0.095133 K — **27× smaller**.

So `S_3dice ≥ 330` was close to certain, and the preregistered `STEADY_CLASSIFICATION_DISAGREES`
outcome would have been produced by a known limitation of the mapping rather than by any
disagreement between the two models. The gate would have run cleanly and answered nothing.

Both the reviewer and I reached the same resistances independently.

## 2. Three errors in v1, all mine, all verified

**Robustness member B was internally inconsistent.** I described it as spreader and sink "folded
into the top boundary condition at the same total conductance". Deleting the copper slabs while
keeping `h·A = 10 W/K` does not fold them in — it *deletes* their resistance. Folding them in at
DC gives `R_eff = 0.100 + 0.00642 + 0.04429 = 0.15071 K/W`, i.e. `h ≈ 17.0 kW/(m²K)` and
6.64 W/K, not the 25.68 kW/(m²K) and 10.00 W/K v1 specifies. And even that would preserve only a
chosen DC series resistance, not the transient impedance — B moves the ambient-facing boundary
from the top of 7.9 mm of copper to just above a 20 µm TIM, which is exactly the kind of change
that can move a sub-millisecond uplift.

**"Affects warm-up and absolute level" is wrong about `c_convec`.** A capacitance does not change
the DC steady level at all; it changes convergence *time*. `S` is invariant to `c_convec` for a
converged steady solve. The ratio `r·c / period ≈ 34 658` does suggest the node moves little
within one period, but a ratio alone does not bound its periodic excursion — that also depends on
the trace's harmonics and the RC topology. v2 must derive a numerical bound on that excursion from
the frozen trace and fold it into the `P` interval.

**"Preserves the heat path exactly" overstates the HTC derivation.** The arithmetic is right —
`h = (1/r_convec)/A_chip = 25 677.4 W/(m²K)` does reproduce the 10 W/K `r_convec` edge over the
represented area, and the rejected per-area alternative would indeed have left only 1.08 W/K. But
it preserves *that edge only*; the truncated slabs differ in through-thickness resistance, lateral
spreading, heat capacity and boundary admittance. Similarly, "the mesh reproduces HotSpot's grid
EXACTLY, which makes the observation operators comparable" was unsupported: equal cell sizes do
not prove 3D-ICE uses HotSpot's outward `ceil`/`floor` touched-cell convention.

## 3. What the review found that I had missed — the package *is* representable

The global footprint is a free field. Setting it to the sink's 60 mm with the die centred and
**zero power outside the die** represents the real package, which removes the 2.57 K artefact
entirely. At the matched 339.003 × 280.469 µm cell that is ~177 cells per side, ≈ 31 k cells —
a cost, not a representability barrier. (The spreader is 50 mm and the sink 60 mm, and passive
layers share one footprint, so one of them is still approximated — but by 1.2×, not 6.4×.)

The review also supplied the identity that rescues the observation operator, which is stronger
than v1's claim. The verdict uses a **global** maximum over blocks, and

> `max_b max_{c ∈ C_b} T_c = max_c T_c` whenever the blocks collectively cover every cell.

The 233 blocks cover all 4096 cells — already proved geometrically in
`research/triangle/v61_tie_mechanism.py` — so in HotSpot the global block maximum *is* the global
cell maximum, and block-boundary ownership cannot change it. If 3D-ICE's `MAXIMUM` likewise
returns a cell maximum over a covering association, the two operators agree on the quantity the
gate actually uses. That has to be established by a conformance test, not assumed.

## 4. What v2 must add before it may be frozen

1. Global footprint at the package scale, die centred, zero power outside the die.
2. Member B removed or replaced. It is not an admissible member of an all-members guard as
   written, and A and B are not ordered approximations of one system, so "both reproduce" shows
   robustness to two constructions and nothing more.
3. **Power rasterisation, which v1 left unspecified and which matters more than output
   membership.** Touched-cell replication, equal division, area-weighted overlap and
   power-density integration all change `S` and `P`. Specify the convention and test
   per-block, per-timestep power conservation, including at the refined mesh.
4. Source semantics established by an analytic one-cell slab fixture rather than assumed:
   `source_thickness_um = 150` is a chosen correspondence, not a fact forced by the HotSpot
   config.
5. Executable numeric fields, not descriptive strings — `integration_step_s` currently reads
   "matched … via rte's exact Fraction timing" and must be a number.
6. The interval as a stated formula covering quantisation, solver residual, periodic residual,
   mesh-pair and timestep-pair discrepancy, operator/source semantic discrepancy, and the
   `c_convec` excursion bound. Two mesh results need not bracket the continuum value, so this is
   a conservative uncertainty band unless enclosure is argued.
7. Every remaining structural assertion labelled a hypothesis or a sensitivity assumption rather
   than a determination.

## 5. Status

`ccfa.yaml`'s `INDEPENDENT-MODEL-GATE` moves to `mapping_rejected_pending_revision`. The
preregistered decision rule, observables and guards are untouched and still stand — the rejection
is of the mapping, not of the gate. No gate output has been produced or examined.
