# Package sensitivity of the cross-solver difference: bounded, and smaller than the design effects

RESULT 2026-08-02. Reading declared before the operators were built
(`~/.claude/plans/fixed-geometry-thermal-scheduling.md` step 4). Producer:
`research/triangle/robustness/package_sweep_band.py`, which calls the same
`one_sided_containment_bounds` `robust_frontier.py` uses, so the band definition cannot drift.
12 of 12 points, 0 skipped. **Corrected 2026-08-02 after peer review** -- the sign predicate, the
architecture ratio and the causal headline were all wrong in the first revision; see each section.

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
  **This has to be split into two claims, and they give different answers.** An earlier revision of
  this document tested `max_j (T_FEM − T_coarse) < 0`, which fires only when *every* row is negative
  and is therefore near-vacuous; peer review caught it and the corrected predicates are:

  | claim | predicate | result |
  | --- | --- | --- |
  | **the PEAK is colder** — what the scalar band uses | `max_j T_FEM − max_j T_coarse > 0` | **holds 12/12**, gap +0.1686 to +0.7924 K |
  | **every ROW is colder** — what per-row budgets need | `min_j (T_FEM − T_coarse) > 0` | **FAILS on 4/12**, all `arch_a` |

  So "HotSpot systematically underestimates" **survives as a statement about the peak and does not
  hold row-wise**. On `arch_a` the FEM is *colder* than HotSpot on 10–55 rows depending on the case.
  That is not a package effect — it happens on both — and it is the same structure as the negative
  `u_j` rows below.
* **band tracks the package → the finding is about the spreading network and generalises.**
  **Did not fire.**
* **band does not move → the finding is weaker but still real.** **This one.** The package moves the
  band by **0.4–5.1 %** (median 3.9 %), and not even consistently in sign, against a 29 % cut in
  `r_convec` and a 67 % larger sink.

## What moves the band more than the package does

| factor | effect on the band |
| --- | --- |
| package (`r_convec` −29 %, sink +67 %) | **0.4 – 5.1 %** |
| workload (resnet50 → transformer), paired | **1.73×** |
| architecture (`arch_c` → `arch_a`), **paired at fixed workload and package** | **2.48 – 2.72×** |

An earlier revision of this table reported **4.8×** for the architecture effect. That was wrong: it
compared `arch_a`/transformer against `arch_c`/resnet50 and so **changed the workload at the same
time**. Peer review caught it. Held properly paired the effect is 2.48–2.72×, still an order above
the package effect but not five-fold.

**Within the two non-default packages tested, package changes moved the band far less than workload
or architecture changes did.** That is the defensible form. The stronger causal reading — "the band
is set by the power map, not the package" — is **not supported by two packages**, and peer review was
right to reject it: `standard` and `enhanced` share a 30 mm spreader footprint, while `default` is the
only configuration with a 50 mm spreader and it was **not included in this sweep run**. Since the
spreader footprint is exactly the spreading-network axis the test was aimed at, the one perturbation
most likely to move the band is the one missing. Including `default` is the next run.

What the bounded observation still supports is the operational point: **the band must be measured per
design rather than assumed from a package characterisation**, because at fixed package it varies
2.5× across architectures and 1.7× across workloads.

**It also widens the reported range — and the three populations must be kept apart.**

| population | band | ratio to the frozen 0.01 K |
| --- | --- | --- |
| `default` only (as previously published) | 0.251 – 1.061 K | 25 – 106× |
| this sweep, `standard` + `enhanced` | 0.2997 – 1.4332 K | 30 – 143× |
| **combined, all three packages** | **0.251 – 1.4332 K** | **25 – 143×** |

The top of the band is **35 % larger** than the previously published maximum. Nothing already
published is invalidated **provided it stays scoped to the `default` package and its producing run**;
what is no longer admissible is quoting `1.061 K` or `106×` as a repository-wide upper limit.

## What this does not license

* Nothing about *which* solver is right. This measures disagreement between two discretisations, one
  of which — the FEM — has its own unquantified spatial error. See the naming rule in the plan:
  report it as a **measured cross-solver difference**, not as "model form", until an operator-level
  convergence envelope exists.
* Nothing about packages outside the three in `experiments/packages.tsv`.
* Nothing at the cell endpoint: these are block-average rows.
* The negative `u_j` rows on `arch_a` (2–7 per case over the polytope, down to −0.1932 K; 10–55 rows
  at the nominal map) **never attain the reported scalar maximum**, because that scalar is
  `max_j u_j` and it is positive everywhere. "Never bind" was the wrong phrase and is withdrawn: a
  negative per-row correction matters immediately once rows are used individually, where it *raises*
  that row's REJECT threshold. That is step 0 of the plan and it is now known to affect four of the
  twelve points measured here.
* The sweep trusts filenames rather than operator metadata, does not bind output-row identity
  independently of column order, and does not commit a content-addressed raw report. Those are open
  and are recorded here rather than fixed, because none of them can change the two verdicts above
  without also changing the block-id check that already passed.
