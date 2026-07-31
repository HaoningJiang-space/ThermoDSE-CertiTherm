# Held-out result, `method-freeze-radii-v1`: the ordering claim is refuted, the diagnosis survives

One run, opened once, scored by `research/triangle/robustness/heldout_verdict.py` which was committed
**before the split produced a single point**. Predictions and kill conditions in
`docs/HELDOUT_PROTOCOL_RADII.md`, unmodified since.

**6 PASS, 2 FAIL of 8.** Both failures are kill conditions, and both are applied below.

## Execution

| | |
| --- | --- |
| architectures declared | 18 |
| **refused** | **6** — all three cuts of both `0.0040 m` spacing grids |
| evaluated | 12 (the four aspect-ratio grids x three cuts) |
| points | 24, in 8 decision groups |
| refusal ceiling | 9; below it, so the run is reportable on the remainder |

The six refusals are a **design error of mine, not a method failure**. ThermoDSE's
`nop_setting_gen` guards `ics < 0.5 or ics > 3.5` mm, so the preregistered 4.0 mm spacing is outside
the pinned evaluator's validity domain and was correctly rejected. Its message says "ranges from
0.5mm to 5mm" while the guard and the comment above it both say 3.5 — a message/guard mismatch in the
pinned dependency, reported here and not fixed, since it is read-only.

The spacing axis is therefore **untested**, and the held-out split reduces to four new aspect ratios:
`2x6`, `2x8`, `6x2`, `8x2`. Re-picking the spacing and re-running would be post-hoc tuning of a
preregistered design and was not done.

## The two failures

### P1 — `beta*_reject` is NOT strictly monotone in the die count

| group | `n=1` | `n=2` | `n=4` |
| --- | --- | --- | --- |
| `2x8` / resnet50 | 3.568 % | 9.685 % | **9.656 %** |
| `2x6` / resnet50 | 3.818 % | 10.365 % | **10.237 %** |

Development: strictly monotone in 10 of 10 groups. Held out: 2 of 8 groups reverse between `n=2` and
`n=4`. The reversals are small — 0.03 and 0.13 percentage points — but the prediction was declared as
strict monotonicity and it is false.

### P2 — the three operators do NOT induce a common ordering

**6 of 8 groups** contain an operator that orders the cuts differently from the family minimum;
development had 0 of 10. The disagreements are not near-ties resolved arbitrarily — the smallest
adjacent separation in the failing groups is `2.2e-4` to `2.2e-3`, against radii of 2–10 %:

| group | `block` | `grid64-avg` | `grid128-avg` |
| --- | --- | --- | --- |
| `6x2` / resnet50 | 1 < 2 < 4 | **4 < 1 < 2** | **4 < 1 < 2** |
| `8x2` / resnet50 | 1 < 2 < 4 | **4 < 1 < 2** | **4 < 1 < 2** |
| `2x8` / resnet50 | **1 < 4 < 2** | 1 < 2 < 4 | 1 < 2 < 4 |
| `6x2` / transformer | 1 < 2 < 4 | **1 < 4 < 2** | 1 < 2 < 4 |

On the two `Nx2` grids the four-die design has the **smallest** radius under both grid operators and
the **largest** under `block` — a reversal of the whole ordering, not a perturbation of it.

## What is withdrawn

> **The claim that the relocation radius orders chiplet cuts stably is WITHDRAWN.**

This was one of the two central claims, and the preregistered kill condition for P1/P2 is explicit
that it admits no partial credit. Every statement of the form "the radius rises monotonically with
the die count in 10 of 10 groups and selects `n = 4` unanimously" is now a **development-set
observation on compact, near-square grids**, and it does not survive elongated ones. The
per-operator agreement that was offered as evidence the ordering is not a modelling artefact is,
on this evidence, **evidence that it can be exactly that**.

The most likely mechanism, offered as a hypothesis and not a finding: on a `2xN` or `Nx2` die the
block-average and grid-average operators resolve lateral spreading very differently, because a
two-tile-wide die has an edge-to-area ratio far outside the range the development grids covered. A
`grid256` convergence study would test it, and is calibration-only rather than certified.

## What survives, and it is the diagnosis rather than the prescription

| | held out | development |
| --- | --- | --- |
| P3 the all-dies-good product prefers `n = 1` | **8 of 8** | 10 of 10 |
| P4 the transcribed recurring cost prefers `n = 1` | **8 of 8** | 9 of 10 |
| P5 the cost-optimal and robustness-optimal cuts **disagree** | **8 of 8** | 9 of 10 |
| P6 no cut owns the joint parameter box | **8 of 8** | 10 of 10 |
| P7 the deviation box is contained in the L1 body, per point | **24 of 24** | 30 of 30 |
| P8 the `n=1`/`n=2` root lies outside `(0, 1]` | **8 of 8** | 10 of 10 |

So the part of the work that generalises is the **negative, diagnostic half**: the chiplet-count
decision is not determined by the objective, under any composition or cost parameterisation tried,
and no cut owns the plausible parameter box. The part that does not generalise is the **positive,
prescriptive half**: using `beta*` as a stable ordering over cuts.

P7 passing on all 24 points is worth separating out. It is a mathematical containment rather than an
empirical regularity, so a single violation would have meant an implementation was wrong; it holds,
which is a check on the geometry split rather than a discovery.

## Consequence for the claim status

The instrumentation bracket, the two radii, the closed forms and the containment discipline are
unaffected — none of them asserts an ordering. What is affected is every sentence that used the
ordering to argue the radius is a better decision variable than the objective. Those are corrected
in `docs/DECISION_SUFFICIENT_INSTRUMENTATION.md` and `README.md` in the same commit as this file.

**No tag.** A central claim was refuted on held-out data in the run that was supposed to confirm it.
The honest position is that this round produced a refutation and a surviving diagnosis, not a
DAC-ready positive result, and the split is now burned for `method-freeze-radii-v1`.
