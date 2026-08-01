# Preregistration: certifying the ThermoDSE submitted archive against an independent solver

FROZEN 2026-08-01, **before any archive design has been run through this project's pipeline**.
Nothing below may be edited after the first census run; a change requires a new freeze ID and a new
document.

Freeze ID: `archive-census-v1`.

## The claim

> Under the **measured** HotSpot-vs-FEM model-form band, at a declared per-block activity span of
> 0.30, the fraction of the declared candidate set that is robust-feasible is **>= X = 20 %**, and
> the EDYP price of the cheapest certified design relative to the evaluator-indistinguishable
> nominal-optimal set is **<= Y = 30 %**.

X and Y are fixed here. If the census returns `X < 20 %` **or** `Y > 30 %`, the claim as stated
fails and is reported as failed. The numbers are not re-tuned to the outcome, and no additional
uncertainty set, span or reference is introduced after seeing the result.

## Why these numbers, and why they can lose

From the archive's own reported peak temperatures (a screen, not our certificate — see "the two peak
numbers are different quantities" below):

* 11 916 distinct designs; **35.2 %** have a reported peak <= 330 K.
* Within the top-64 by EDYP of that subset: reported peak **min 327.0 K, median 329.2 K, max
  330.0 K**. Only **39 %** are <= 329.0 K, **17 %** <= 328.5 K, **11 %** <= 328.0 K.

From this project's development split, at span 0.30 with the FEM band folded in:

* the polytope excursion above the nominal map is **0.47 - 1.38 K**;
* the model-form band `sup_p [T_FEM - T_grid512]` is **0.25 - 1.06 K**;
* margin plus linearisation is **0.06 K**.

So a design needs roughly **0.8 - 2.5 K** below 330 K to certify. Against a candidate set whose
median reported peak is 329.2 K, most of the top will fail. **X = 20 % is a real bet**: it loses if
our pipeline's peaks track the archive's, and it wins comfortably only if they run cooler.

`Y = 30 %` corresponds to the cheapest certified design sitting at about rank 40 of 64; rank 32 is
+25.7 % and rank 48 is +32.9 %, so **Y loses if nothing below rank ~40 certifies**.

## The declared candidate set

* **Source**, pinned by content, in the `ThermoDSE` submodule at `51c1506`:

  | file | sha256 (first 16) |
  | --- | --- |
  | `ThermoDSE/tools/results_new/archs_348_300_2.txt` | `2c36a68ca28ca678` |
  | `ThermoDSE/tools/results_new/archs_348_300_200.txt` | `57fb92d290e38d79` |
  | `ThermoDSE/tools/results_new/archs_348_300_300.txt` | `164c2f69fa6fdbb3` |
  | `ThermoDSE/tools/results_new/archs_348_300_400.txt` | `3e85ef30bf834127` |

* **Parser**: `sys_info:(\[[^\]]*\])` paired with the following
  `area:...,\s*peak temperature is\s*...\s*K,\s*Yield:...,\s*EDYP:...` line. Transcribed from
  `ChipletOrchestrationRegret/eval/k0_ranking_margin.py` (`SYS_INFO_RE`, `METRIC_RE`), which is the
  existing verified reader for this format. Provenance recorded rather than re-derived: an earlier
  attempt in this session invented `Area:` / `Peak temp.:` and silently parsed **zero** rows.
* **Duplicate policy**: keyed on the exact `sys_info` string; the last occurrence wins. 11 916
  distinct designs across the four files.
* **Selection**: designs with reported peak <= 330.0 K (4 196), sorted ascending by EDYP, **top 64**.
  Ties broken by the `sys_info` string, ascending, so the set is a deterministic function of the
  four files.
* **Denominator**: **64**, fixed. A design whose capture, operator or FEM build fails counts as
  **UNRESOLVED and stays in the denominator.** Dropping it would remove exactly the hard cases and
  inflate X.
* **Unit**: one design-workload pair, `resnet50` only. Adding `transformer` would double the cost and
  the claim is stated per workload; `resnet50` is declared here as *the* workload for this census.

## The certificate, fixed

`sup_p T_grid512(p) + sup_p [T_FEM(p) - T_grid512(p)] <= 330.0 - 0.05 - 0.01`

* **Reference**: HotSpot `grid512-avg`, block-average rows, built through `fine_operator.py` on GPU.
* **Model-form band**: `one_sided_containment_bounds(grid512, fem-dolfinx, ...)`, one-sided, so the
  band can only make certification harder.
* **Linearisation term**: `MODEL_ERROR_LIMIT_K = 0.01 K`, **retained** — it measures replay against
  impulse superposition, a different error source from disagreement between operators.
* **Margin**: `0.05 K`.
* **Uncertainty set**: `activity_bounded_power_space` at **span 0.30**, the primary and only endpoint
  for X and Y. `content_upper_bounds` is reported alongside as the permissive endpoint but is **not**
  part of the claim: it contains genuinely infeasible power maps (measured 337-386 K on dev) and
  refuses everything for reasons that are not model error.
* **Curve**: the same census re-evaluated at spans 0.05, 0.10, 0.20, 0.30, 0.50, 0.80, 1.20. The
  curve is a reported deliverable; X and Y are judged at 0.30 only.
* **Tolerances, fail-closed**: FEM energy balance, per-impulse power error and zero-solve offset each
  <= 1e-6; GPU/CPU operator parity <= 1e-6 K/W. Any breach makes that design UNRESOLVED.

## The two peak numbers are different quantities

The archive's reported peak comes from ThermoDSE's own HotSpot invocation under its own 348 K / 300
mm^2 convention and carries the known evaluator defects (`core/statistic.py:200` and the rest). This
census re-derives everything: floorplan, power map, operator, certificate. The archive's peak is used
**only** to define the candidate set, never as an input to a verdict. Its role is declared here so
that a later reader cannot mistake the screen for the measurement.

## Explicit non-goals, restated

No speedup. No search-algorithm change. No repair of ThermoDSE's evaluator defects — they are inputs
to the decision, not claims of this work. No place-and-route. **No use of the frozen held-out splits**:
the archive is a separate population and `arch_d` through `arch_l` remain untouched.

## Rollback

The band is parameterised. Setting the model-form term to zero and the linearisation term back to
0.01 K reproduces the pre-existing behaviour exactly. Nothing here is irreversible.

## What a failure means

`X < 20 %` does **not** by itself kill the direction: it converts the deliverable from "a robust
frontier and its price" into "the submitted archive's EDYP-optimal region is not certifiable at 330 K
once model form is budgeted, and here is how much colder a design must run to be certifiable" — which
is a quantified, positive statement about what the search would have to target. That reformulation is
declared **now**, so that choosing it later is not a post-hoc rescue.
