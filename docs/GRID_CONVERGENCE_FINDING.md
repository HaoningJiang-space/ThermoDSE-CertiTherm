# The frozen error contract certifies linearity, not grid convergence — and that is what failed

Follow-up to `docs/HELDOUT_RESULT_RADII.md`, which recorded that 6 of 8 held-out decision groups
contained a thermal operator ordering the chiplet cuts differently from the family minimum, and
withdrew the ordering claim. That left one question: are the registered grid operators converged at
these aspect ratios, or is `block` the outlier?

**Neither. The registered grid operators are not converged, and the contract that admits them cannot
see it.**

Calibration-only, `grid256-avg` against the certified family, on the six `2x6` and `6x2`
architectures where the inversion was complete. `CertiTherm.experiments.MODELS` is frozen and was not
touched; `research/triangle/robustness/grid_convergence.py` builds its own family from the sweep's
exact config and floorplan.

## The measurement

`beta*_reject`, per operator:

| architecture | workload | grid | `grid64` | `grid128` | `grid256` | `｜g128−g256｜/g256` |
| --- | --- | --- | --- | --- | --- | --- |
| `..._06` | resnet50 | 2x6 | 12.584 % | 12.473 % | 11.847 % | 5.3 % |
| `..._07` | resnet50 | 2x6 | 15.307 % | 13.444 % | 13.391 % | 0.4 % |
| `..._08` | resnet50 | 2x6 | 15.729 % | 13.941 % | 13.878 % | 0.5 % |
| `..._09` | resnet50 | 6x2 | 10.236 % | 7.304 % | **6.229 %** | **17.3 %** |
| `..._10` | resnet50 | 6x2 | 10.507 % | 7.789 % | **6.454 %** | **20.7 %** |
| `..._11` | resnet50 | 6x2 | 8.074 % | 7.056 % | 7.781 % | 9.3 % |
| `..._09` | transformer | 6x2 | 2.497 % | 1.677 % | **1.374 %** | **22.0 %** |
| `..._10` | transformer | 6x2 | 2.957 % | 2.119 % | **1.696 %** | **24.9 %** |

On `2x6` the last refinement moves the radius by 0.4–10.2 %. On `6x2` it moves it by **9.3–24.9 %**,
and the `4 < 1 < 2` inversion that `grid64` and `grid128` both produced **disappears at 256**:
`grid256` returns `1 < 2 < 4` in **4 of 4** groups.

## The contract cannot detect this, and the reason is structural

`experiments.py` calibrates each operator by replaying a power vector through **the same
`model_id`** and comparing against that model's own linear prediction:

```python
direct    = replay_power(HOTSPOT, config, floorplan, materials, model_id, blocks, power, ...)
predicted = family.ambient_k[model_index] + family.response_k_per_w[model_index] @ power
error     = max|direct - predicted|          # PASS if <= MODEL_ERROR_LIMIT_K
```

That is a test of **linearity at a fixed discretisation**. An operator that is perfectly linear and
badly under-resolved passes with an error near zero, because both sides of the comparison share the
same grid. Measured on `heldout_radii_09`: `grid128-avg` passed with a worst calibration error of
**0.0027 K**, 27 % of the 0.01 K budget — while its radius differs from a 4x finer grid by **17 %
relative**.

So the frozen `0.01 K` band is doing exactly what it says and nothing more. Nothing in the pipeline
ever compares an operator against a finer one, and the held-out P2 failure is the first thing that
made that visible.

## Mechanism, offered as a hypothesis

HotSpot's grid is square — `grid_rows == grid_cols` — laid over a floorplan that is not. A `6x2` tile
arrangement is roughly three times wider than tall, so a 128x128 grid resolves the short axis with
about a third of the cells per unit length that the long axis gets. The `2x6` cases, where the same
refinement moves the answer far less, differ from `6x2` only by transposition, which is consistent
with an axis-dependent resolution effect and inconsistent with a workload or a power-map effect.
Testing it needs anisotropic grids, which the registered model-id vocabulary (`gridN-avg`, one size)
cannot express.

## What this does and does not license

* **It does not un-withdraw the ordering claim.** The `method-freeze-radii-v1` split is burned. That
  `grid256` recovers `1 < 2 < 4` in 4 of 4 groups is evidence about the *instrument*, measured on
  architectures already seen, and using it to restore the hypothesis would be exactly the post-hoc
  move the preregistration exists to prevent.
* **It does not establish that `grid256` is right.** There is no `grid512` here. `g128` and `g256`
  agreeing in 3 of 4 groups is the convergence test that was run; in the fourth they disagree, so
  `grid256` is the odd one out there and nothing distinguishes "converged" from "differently wrong".
* **It covers 4 decision groups**, `2x6` and `6x2` only. `2x8` and `8x2`, which also failed P2, were
  not run.
* **It does establish** that two operators in the certified family disagree by up to 25 % with a
  finer grid on geometries the frozen error contract admitted without complaint.

## The method change this earns

A **grid-convergence gate** beside the linearity gate: refuse a `gridN` operator unless
`max|response(N) − response(2N)|` is under a registered bound, in the same fail-closed style as the
`0.01 K` band. That converts the finding above from a post-hoc discovery into a precondition, and it
would have refused the `6x2` operators before they produced an ordering.

**The gate is implemented** in `CertiTherm/grid_convergence_gate.py`, pinned by ten tests, and
deliberately in its CHEAP form. Rebuilding a full `grid2N` impulse-response operator costs one
HotSpot solve per block per model; what the contract actually needs is not a second operator but
evidence that the temperature FIELD is resolved, and that needs one extra replay per calibration
vector — five solves per grid model instead of one per block.

    coarse = replay_power(..., "gridN-avg",  ..., power)
    fine   = replay_power(..., "grid2N-avg", ..., power)
    drift  = max|coarse - fine|                    PASS if <= GRID_DRIFT_LIMIT_K

The bound is registered separately from `MODEL_ERROR_LIMIT_K` and a test requires them to differ:
one bounds discretisation and decides whether an operator may be built, the other bounds
linearisation and is folded into every SAFE/REJECT row. Registering them as one number would make a
change to either silently move the other, and the measured case is why — 0.0027 K of linearity error
alongside kelvins of discretisation drift.

Two limits are stated in the module rather than left to a reader. A PASS is a Richardson-style
agreement between two successive refinements on five power maps, not a proof of convergence. And
`block` has no refinement parameter, so it is reported as `ungated` rather than passed — it was the
outlier in one of the four groups measured and nothing here would catch it.

**It is not wired into `experiments.py`**, which is frozen under `method-freeze-radii-v1`. Adopting
it is a method change requiring a new freeze ID and a fresh development run — the same rule that
sent this round to a new split rather than reusing `method-freeze-v1`. The ordering claim cannot be
retested until it is adopted, because until then the family cannot be trusted to order anything on a
geometry outside the development aspect-ratio range.
