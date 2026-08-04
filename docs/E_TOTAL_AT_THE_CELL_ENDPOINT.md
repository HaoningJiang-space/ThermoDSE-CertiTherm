# P1: `e_total` at the cell endpoint is 1.98–4.99 K, and folding it in is 70× too conservative

RESULT 2026-08-04, `moe-server`. NON-CLAIM. FEM reference at `CERTITHERM_FEM_CELL_ENDPOINT=128`
against the `grid128-avg` HotSpot cell operators, same captures, span `0.30`, `default` package,
`one_sided_containment_bounds` — **the block-row band's own definition, inherited not re-invented**.
**No external review** — Codex quota-locked to 2026-08-08.

## The number that was missing

`G2_REPAIR_THE_WINDOW_IS_ONE_DIMENSIONAL.md` records `e_total` as *"appearing in no source file in
this repository"*, and `CELL_ENDPOINT_RESULT.md` records the cell-level band as not measured. Every
band measured so far is at **block** rows: `0.251 – 1.4332 K`. The certificate is evaluated at
**cell** rows. Those are different functionals and the substitution was never checked.

| case | **`e_total`** (row-wise, cell rows) | at the nominal map | block-row band, for scale |
| --- | ---: | ---: | ---: |
| `arch_c`/resnet50 | **1.9831** | 1.2143 | 0.251 |
| `arch_b`/resnet50 | **3.0124** | 1.5726 | — |
| `arch_b`/transformer | **4.9901** | 2.6316 | — |

**Eight to twenty times the block-row band.** Substituting one for the other was wrong by an order of
magnitude, in the permissive direction.

## And the quantity that actually moves a verdict is 70× smaller

`e_total = max_j sup_p (T_fem − T_hs)_j` gives every row its **own** adversarial power map and then
takes the worst row. What a verdict reads is `max_j sup_p T_j` — one map, then one max. The chain

    max_j sup_p T_fem,j  ≤  max_j ( sup_p T_hs,j + u_j )  ≤  max_j sup_p T_hs,j + max_j u_j

is sound, so `e_total` **is** the correct a priori bound. It is also enormously loose:

| case | HotSpot certified | FEM certified | **Δ certified** |
| --- | ---: | ---: | ---: |
| `arch_c`/resnet50 | 322.3138 | 322.2862 | **−0.0276** |
| `arch_b`/resnet50 | 325.4619 | 325.3932 | **−0.0687** |
| `arch_b`/transformer | 330.3018 | 330.3726 | **+0.0708** |

> **The two solvers disagree by up to 4.99 K on some cell, and by at most 0.071 K on the number a
> certificate reads.** On two of three cases the FEM is *cooler*. The looseness of the sound bound is
> a factor of **70**.

The mechanism is visible in the columns: the nominal peaks agree to `0.018–0.068 K` while
`at_nominal_max` reaches `2.63 K`, so **the cells the two models disagree about are not the hot
ones**, and each row's worst power map is a different map.

## What this does to the round, in both directions

**Against the method.** `e_total` is the edge of G2's separator window `margin + e_total ≤ dist < g`.
At `1.98–4.99 K` the window is **empty for any `g ≤ 5 K`** — and `g` is the incumbent guard-band
convention, 3–5 K. So the separator framing, already twice repaired, is **dead at the cell endpoint**:
a method that must fold in a 2–5 K band cannot beat a 3–5 K guard band by construction. That is a
sharper kill than the population argument and it does not depend on any candidate set.

**For the method.** Every certification in this round was computed with HotSpot, and the measured
solver disagreement on that quantity is `≤ 0.071 K` — an order of magnitude *below* the block-row
band that was previously assumed to threaten them. The found design's `+0.328 K` slack survives a
measured `Δ`; it does not survive a folded-in `e_total`.

**Both statements are true and they are about different objects.** `e_total` is what you need if the
claim is *"HotSpot's value bounds the FEM's at every cell"*. `Δ` is what you get if the claim is
*"the certified peak does not depend much on which solver computed it"* — but `Δ` is a **measurement
on three designs**, not a bound, and it must never be used as one for a design not measured.

## The bound tightened, and it does NOT rescue the headline

The looseness is that `hs_sup + e_total` takes two maxima **independently** — the hottest cell's
supremum plus the worst cell's error, even when those are different cells, which here they are. The
sound and strictly tighter bound takes one maximum:

    max_j T_fem,j(p)  <=  max_j ( sup_p T_hs,j + u_j )     for every admissible p

Both terms are already computed per row, so this costs nothing. Measured, with soundness (must
dominate the FEM's own certified peak) and tightness (must not exceed the loose bound) checked at run
time rather than argued:

| case | `e_total` | loose bound | **tight bound** | **effective band** | factor |
| --- | ---: | ---: | ---: | ---: | ---: |
| `arch_c`/resnet50 | 1.9831 | 324.2970 | 323.0639 | **0.7501** | 2.6 |
| `arch_b`/resnet50 | 3.0124 | 328.4743 | 326.5713 | **1.1095** | 2.7 |
| `arch_b`/transformer | 4.9901 | 335.2919 | 332.1197 | **1.8179** | 2.7 |

**A factor of 2.7, not the order of magnitude I expected, and the round's headline does not survive
it.** The composed result's slack is `+0.7738 K` (`CERTIFIED_MAPPING_AND_THE_UNIFICATION.md`) against
an effective band of `0.75–1.82 K` that **grows with power**, and the headline design is the hottest.

> **The headline table is `CERTIFIED` relative to HotSpot and `UNRESOLVED` model-agnostically.** That
> must be said in those words. Every thermal DSE in this field is implicitly the first kind — a
> verdict relative to whichever solver it ran — and the difference here is that the gap is measured
> rather than absent. But "we measure what others hide" is not the same claim as "certified", and the
> two must not be swapped.

The effective band also reconciles with the block-row band (`0.251–1.4332 K`) rather than exceeding it
by an order of magnitude, which is the consistency check the raw `e_total` failed.

**Owed and named:** these three are the *legacy* captures. The headline uses **routed** traces on the
DRAM-augmented floorplans, which are a different geometry and 12–38 % more power, so the band there is
not measured and the numbers above are an indication, not a substitution — the exact error this
document was written to stop.

## What would make the bound usable, and it is the next piece of work

The looseness is entirely in taking `max_j` over rows that cannot be the argmax. A bound restricted to
rows that can attain the maximum somewhere in the envelope — the *active* rows — would be sound and
far tighter. `CertiTherm/cross_grid_bound` already computes per-row suprema, so the candidate set is
`{ j : sup_p T_hs,j + u_j ≥ max_k sup_p T_hs,k }`, which is cheap and needs no new solve. **Not
done.**

## Scope

* Three cases, one package, `grid128` cells, span 0.30.
* The FEM is a reference, not ground truth; its operator carries `error_k = NaN` deliberately so it
  cannot be certified against through the normal machinery.
* Both cell operators passed their own gates: energy balance and unit-impulse power to `1e-6`, after
  two construction defects were caught by exactly those gates (midpoint power assignment inflated a
  unit impulse to 3.9 W; unsnapped cell areas left a 3.2e-6 W residue).
