# The cross-solver difference is set by the power map, not by the package

RESULT 2026-08-02. Reading declared before the operators were built
(`~/.claude/plans/fixed-geometry-thermal-scheduling.md` step 4). Producer:
`research/triangle/robustness/package_sweep_band.py`, which calls the same
`one_sided_containment_bounds` `robust_frontier.py` uses, so the band definition cannot drift.
12 of 12 points, 0 skipped.

## Why this test existed

Every model-form number in this project was measured on `packages.tsv:default`, so **"HotSpot reads
colder than an independent FEM on all six points" could have been a property of that one package**
rather than of HotSpot's lumped centre-plus-trapezoid spreading network. `standard` and `enhanced`
move `r_convec` from 0.10 to 0.07 and 0.05, the spreader from 50 to 30 mm, and the sink from 60 to
100 mm — they change the total resistance *and* the spreading area, which is exactly the axis that
network approximates. If the band is about that network, it must move with them.

**This was the cheapest thing that could still have refuted the headline**, which is why it was run
before scaling anything.

## Result

`sup_p [T_FEM − T_grid512]` over the activity set at span 0.30, per row, one-sided:

| arch | workload | `standard` | `enhanced` | package change | `min u_j` (std/enh) | rows `u_j < 0` |
| --- | --- | --- | --- | --- | --- | --- |
| `arch_a` | resnet50 | 0.7731 | 0.8032 | +3.9 % | −0.1196 / −0.0805 | 7 / 4 |
| `arch_a` | transformer | 1.3633 | 1.4332 | +5.1 % | −0.1932 / −0.1223 | 2 / 2 |
| `arch_b` | resnet50 | 0.7256 | 0.6971 | −3.9 % | +0.1273 / +0.1630 | 0 / 0 |
| `arch_b` | transformer | 1.2541 | 1.2006 | −4.3 % | +0.2591 / +0.3157 | 0 / 0 |
| `arch_c` | resnet50 | 0.3116 | 0.2997 | −3.8 % | +0.0482 / +0.0763 | 0 / 0 |
| `arch_c` | transformer | 0.5259 | 0.5278 | +0.4 % | +0.2174 / +0.2595 | 0 / 0 |

## The three preregistered outcomes, and which one fired

* **sign flips on some package → withdraw "HotSpot systematically underestimates".**
  **Did not fire.** The value at the nominal map is positive on **12 of 12**, ranging +0.2398 to
  +1.0082 K. The one-signed reading survives a test that could have killed it.
* **band tracks the package → the finding is about the spreading network and generalises.**
  **Did not fire.**
* **band does not move → the finding is weaker but still real.** **This one.** The package moves the
  band by **0.4–5.1 %** (median 3.9 %), and not even consistently in sign, against a 29 % cut in
  `r_convec` and a 67 % larger sink.

## What actually sets the band, which is the positive result

| factor | effect on the band |
| --- | --- |
| package (`r_convec` −29 %, sink +67 %) | **0.4 – 5.1 %** |
| workload (resnet50 → transformer) | **1.73×** |
| architecture (`arch_c` → `arch_a`) | **4.8×** |

**The disagreement between HotSpot and an independent FEM is a property of the spatial power map,
not of the package.** That is a stronger and more useful statement than the one this test was built
to defend: it means the band has to be measured per design rather than assumed from a package
characterisation, and it explains why a single package-level guard band cannot be right for every
architecture.

**It also widens the reported range.** The `default`-only figure was 0.251–1.061 K; across packages
it is **0.2997–1.4332 K**, so the top of the band is **43 % larger** than previously reported and
the 25–106× ratio against the frozen 0.01 K contract becomes **30–143×**.

## What this does not license

* Nothing about *which* solver is right. This measures disagreement between two discretisations, one
  of which — the FEM — has its own unquantified spatial error. See the naming rule in the plan:
  report it as a **measured cross-solver difference**, not as "model form", until an operator-level
  convergence envelope exists.
* Nothing about packages outside the three in `experiments/packages.tsv`.
* Nothing at the cell endpoint: these are block-average rows.
* The negative `u_j` rows on `arch_a` (2–7 per case, down to −0.1932 K) still never bind, because the
  reported scalar is `max_j u_j`, which is positive everywhere. They become live the moment per-row
  budgets are used, which is step 0 of the plan.
