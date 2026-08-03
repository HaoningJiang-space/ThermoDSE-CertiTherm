# The incumbent method's own designs do not survive their own activity envelope

RESULT 2026-08-04, `moe-server`, `/data/ziheng/ThermoDSE-CertiTherm` clean at the commits named in
the log. NON-CLAIM. Pinned HotSpot `sha256 b0040b3e…`, `grid128-avg`, endpoint `tool_compatible`,
routed trace (every source placed where its route puts it). **No external review** — Codex
quota-locked to 2026-08-08.

## The measurement

Six architecture–workload points from ThermoDSE's own frozen registry, certified over an activity
envelope rather than evaluated at a point. `radius` is the largest envelope half-width the design
tolerates: the design remains feasible for **every** power map in `p_nom (1 ± radius)` with the total
preserved, and fails for some map beyond it.

| design | nominal peak | dist to ceiling | **robustness radius** | mean power | status |
| --- | ---: | ---: | ---: | ---: | --- |
| `arch_a`/resnet50 | 325.6499 | +4.2901 | 0.9699 | 28.22 W | RADIUS |
| `arch_b`/resnet50 | 327.4570 | +2.4830 | **0.5268** | 44.79 W | RADIUS |
| `arch_c`/resnet50 | 325.1430 | +4.7970 | 1.1605 | 28.91 W | RADIUS |
| `arch_a`/transformer | 327.1950 | +2.7450 | 0.6048 | 40.26 W | RADIUS |
| **`arch_b`/transformer** | **329.9732** | **−0.0332** | **0.0000** | 57.18 W | **REFUTED AT NOMINAL** |
| `arch_c`/transformer | 327.5475 | +2.3925 | **0.4884** | 46.06 W | RADIUS |

**One of six is infeasible at its own nominal power map**, before any envelope is considered:
329.9732 K against a 329.94 K ceiling. The other five stop certifying once block activity can vary by
**49 % to 116 %**.

## Why this is a statement about the incumbent method and not about six numbers

These are not adversarial designs. They are the architectures the pinned ThermoDSE submodule itself
produces and the ones this project's frozen registry declares, evaluated through ThermoDSE's own
trace with **nothing removed** — the routed lowering places the DRAM, NoP and NoC energy the legacy
ptrace omits or lumps, and its source and route receipts reconcile to `< 1e-9` relative.

The incumbent method reports one number per design: the nominal peak. On that number all six look
safe or marginal, and the ordering it induces is **not** the ordering of robustness — over the 60
archive designs the rank correlation between distance-to-ceiling and radius is **+0.465**
(`THREE_LEGS_STATUS.md`), and the tightest design by nominal peak there has the *maximum* radius.

So the failure mode is not "the incumbent is sloppy". It is that **a point evaluation cannot express
the quantity that decides feasibility under workload variation**, and the guard band that stands in
for it has no source (`G2_REPAIR_THE_WINDOW_IS_ONE_DIMENSIONAL.md`, `PEAKCERT_OPERATOR_PREREGISTRATION.md`).

## The population matters, and the archive census is the control

The same certificate over the 60 archive designs under `resnet50` finds **nothing** in the separator
band: distance to ceiling 4.94-9.17 K, radius 0.95-2.00, zero refusals. Those designs draw
**5.5-18.5 W** against **28-57 W** here. So the frontier is a property of the operating point, and
the archive census — selected on the archive's own non-reproducible peak column and on a low-power
workload — sits far from it. Reporting both is what makes the six-point table a finding rather than a
selection.

## What is NOT claimed

* **That ThermoDSE is wrong to produce these designs.** Its own cap is 348 K and is documented as
  unsupported; the 330 K limit is this project's frozen registry value, and
  `CertiTherm/frozen_limits.py` still gives it no provenance. What is measured is the behaviour
  **against the declared limit of this study**, and a different limit moves every row.
* **That the envelope is the right one.** `activity_bounded_power_space` is a box with a total-power
  equality. A radius of 0.49 means "±49 % per block with the total preserved", which is a specific
  and declared uncertainty model, not the only one.
* **A pointwise peak.** The certified quantity is a max of cell averages; `H¹ ⊄ L^∞` in 3D.
* **A model-form band.** None is folded in. Folding it in lowers every peak by 0.25-1.43 K, which
  moves `arch_b`/transformer further from feasible and every radius down.
* **The other half of the comparison.** "Ours does not violate, at no EDYP cost" requires a search
  whose feasibility test is this certificate; that is `certified_search.py` and it is reported
  separately.
