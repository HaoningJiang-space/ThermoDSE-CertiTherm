# Preregistration: held-out evaluation of the robustness-radii method

**Freeze ID `method-freeze-radii-v1`. Written and committed BEFORE the held-out architectures were
generated or evaluated.** The commit that adds this file contains no held-out data, and the commit
that adds the data does not modify this file. That ordering is the only thing that makes the
predictions below falsifiable rather than descriptive.

## Why a new split rather than the existing one

`docs/HELDOUT_PROTOCOL.md` freezes a dev/held-out split under `method-freeze-v1` whose registered
endpoints are the v1 DSOS query results. The method evaluated here — relocation radii, the
instrumentation bracket, and the yield-composition comparison — is not among those endpoints, so
running it on that split would be reinterpreting held-out cases outside the protocol they were
frozen under, which `CLAUDE.md` forbids. The same rule states the correct route: **post-freeze
method change requires a new freeze ID and a new split.** This is that new split. The
`method-freeze-v1` held-out split is untouched and remains unopened for its own endpoints.

## What is frozen

As of this commit, no further change to any of:

* `research/triangle/robustness/l1_body.py` — the radii, exact and closed-form
* `research/triangle/robustness/chiplet_cost.py` — the transcribed OS recurring-cost model
* `research/triangle/robustness/yield_composition.py` — the three yield compositions
* `research/triangle/robustness/cost_crossover.py` — the crossover and the sensitivity design
* `research/triangle/robustness/per_model_radii.py` — the per-operator ordering
* `research/triangle/robustness/architecture_sweep.py` — capture, operator build, radii
* `CertiTherm/measurements.py` — the three uncertainty geometries
* `CertiTherm/thermal_constraints.py` — the SAFE and REJECT rows
* the registered margin `0.05 K`, the frozen limit `330.0 K`, the `0.01 K` error band
* the cost parameters and the sensitivity ranges in `cost_crossover.SENSITIVITY`
* `BONDING_GRID`, `JOINT_SAMPLES = 4000`, `JOINT_SEED = 20260801`

A defect found after this point is reported and the affected prediction is marked UNRESOLVED. It is
not fixed and re-run against this split; that would be post-hoc tuning and needs another freeze ID.

## The held-out design, declared in full

Six tile grids **none of which appears in the development sweep**, crossed with cuts
`(1,1)`, `(2,1)`, `(2,2)`. Every cut divides its grid evenly, so all dies are equal and the
per-die product is exactly recoverable.

| purpose | grids | spacing |
| --- | --- | --- |
| new aspect ratios, including strongly elongated | `2x8`, `8x2`, `2x6`, `6x2` | 0.0017 m |
| new spacing, an axis never varied in development | `4x4`, `6x4` | **0.0040 m** |

18 architectures x 2 workloads (`resnet50`, `transformer`) = **36 points, 12 decision groups**.
Development used `4x4`, `4x6`, `6x4`, `6x6`, `8x4` at 0.0017 m only, so both the aspect-ratio rows
and the spacing rows are out of the development regime.

An architecture refused by the `0.01 K` linearisation-error contract is **recorded as refused and
excluded**, exactly as three `8x6` points were in development. Refusals are data, not failures, and
their count is reported. If more than 9 of 18 architectures are refused the run is declared
UNRESOLVED rather than reported on the remainder.

## Predictions, with the development value each is drawn from

| # | prediction | development |
| --- | --- | --- |
| P1 | `beta*_reject` rises **strictly monotonically** with die count in every decision group | 10 of 10 |
| P2 | all three operators, under **both** radii, induce the family cut ordering in every group | 10 of 10 |
| P3 | the all-dies-good product composition prefers `n = 1` in every group | 10 of 10 |
| P4 | the transcribed recurring-cost model prefers `n = 1` in **at least 9 of 12** groups | 9 of 10 |
| P5 | the cost-optimal and robustness-optimal cuts **disagree** in at least 9 of 12 groups | 9 of 10 |
| P6 | no cut wins all 4 000 joint samples in any group | 10 of 10 |
| P7 | the deviation-box radius is `<=` the exact L1 radius on **every** point | 30 of 30 |
| P8 | the `n=1` vs `n=2` exact root lies **outside** `(0, 1]` in every group | 10 of 10 |

## Kill conditions

* **P1, P2 or P7 fails anywhere** — the claim that the radius orders designs stably, or that the
  geometries nest as stated, is **withdrawn**. These are load-bearing and admit no partial credit:
  P7 in particular is a mathematical containment, so a single violation means an implementation is
  wrong, not that the world is noisy.
* **P3 or P8 fails in more than 2 of 12 groups** — the composition claim is downgraded from "in
  every group" to a measured fraction, and the document is corrected.
* **P4 or P5 falls below 7 of 12** — the disagreement between the cost and robustness axes is
  reported as workload- or geometry-dependent rather than general.
* **P6 fails in any group** — "no cut owns the parameter box" is withdrawn and replaced by the
  measured shares.

## Rollback

Failure of any kill condition corrects `docs/DECISION_SUFFICIENT_INSTRUMENTATION.md` and `README.md`
in the direction of the measurement, and the held-out numbers are retained in the tree whatever they
say. Negative results are not deleted; two headline withdrawals from earlier this round are already
recorded rather than removed.

## Requested dissents

1. Elongated grids (`2x8`, `8x2`) may make the thermal problem qualitatively different rather than
   merely new — a two-tile-wide die has a very different aspect ratio and edge-to-area ratio, and a
   failure there may say more about the floorplan generator than about the method.
2. The spacing rows change total interposer area, which enters the substrate cost term that the
   sensitivity analysis already identified as the most influential — so P4 and P5 are being tested
   on the axis most likely to move them, which is either the strongest possible test or an unfair
   one depending on one's view.
3. Predictions P4 and P5 are counts over 12 groups with no variance model; "at least 9 of 12" is a
   threshold chosen to match the development fraction, not a statistical test.

## Execution

One run, on `moe-server`, from a clean worktree at the commit that adds this file plus the driver
invocation. No tuning between generation and reporting. The output directory must not exist.
