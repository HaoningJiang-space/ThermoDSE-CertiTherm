# What the missing half of the dissipated energy would do to the verdicts

RESULT 2026-08-02. NON-CLAIM sensitivity, computed from operators and captures already committed.
**No frozen thermal input was changed and no new ground truth was produced** — that change is Tier 2
under `CLAUDE.md` and is the owner's decision, not this analysis's.

## The method, which the audit itself proposed

`docs/THERMODSE_ENDPOINT_AUDIT.md` §4: *"A sensitivity envelope over non-negative nuisance heat loads
can test robustness (a linear passive thermal network is monotone in applied heat)."* That is exactly
the machinery this project already has — every operator is affine `T = R p + a`, so adding heat is a
matrix-vector product, not a re-solve.

The audit's own closure fixes the magnitude: dissipated `9.2218 mJ` against `4.6118 mJ` reaching
HotSpot, so **the missing energy is 0.9996x the arriving energy** — the trace carries almost exactly
half the heat.

Two placements bracket it:

* **adversarial** — all missing power on the block that heats the hottest row most. Valid but
  vacuous: it gives rises of 37.8–208.5 K. Reported so the bracket is honest, not to be used.
* **proportional** — the missing DRAM and NoP spread like the existing map. By linearity this is
  exactly a scaling of `p` by 1.9996, and it is the physically motivated case: DRAM and NoP are
  distributed sources, not point loads.

## Result, proportional placement, `grid512` operators, `standard` package

| case | peak now | peak x1.9996 | slack now | verdict |
| --- | ---: | ---: | ---: | --- |
| resnet50/`arch_a` | 321.192 | 324.233 | +8.808 | ok |
| resnet50/`arch_b` | 323.392 | 328.631 | +6.608 | ok |
| resnet50/`arch_c` | 321.161 | 324.171 | +8.839 | ok |
| transformer/`arch_a` | 323.540 | 328.928 | +6.460 | ok |
| **transformer/`arch_b`** | 327.011 | **335.868** | +2.989 | **REFUSED by 5.87 K** |
| transformer/`arch_c` | 323.701 | **329.250** | +6.299 | ok by **0.75 K** |

## What this means for the headline, and it is not what it first looks like

**The `arch_b -> arch_c` switch does NOT reverse.** `arch_b` is refused either way, and harder.

**But the decision stops being resolvable.** `arch_c`'s slack falls from +6.299 K to **+0.750 K**,
and the measured cross-solver difference on these operators is **0.2997–1.4332 K**
(`docs/PACKAGE_SWEEP_RESULT.md`). **The surviving alternative's margin is smaller than the band it
must clear.** Under the corrected energy the correct verdict for `arch_c` is not "certified" but
`UNRESOLVED` — which is the fail-closed outcome, and it means the `+32.1 %` price is quoted for a
switch to a design that may not itself be feasible.

## Why this is the argument for fixing the trace, not for ignoring it

The missing energy does not merely shift numbers by a few tenths. It consumes **89 %** of the tightest
surviving margin. Any master fitted to the current trace would optimise against headroom that does
not exist — and would do so *plausibly*, which is the audit's own explanation for why the omission
survived undetected.

**So the trace correction is a prerequisite for the MILP, established quantitatively rather than
asserted.** It is also Tier 2: placing DRAM power on floorplan units changes frozen thermal inputs
and invalidates committed results, so it needs the owner's decision and pre-review before it runs.

## Scope

* Proportional placement is an assumption, not a measurement. DRAM is physically off-die and NoP is
  interconnect; neither distributes like the compute map. The true placement could be better or
  worse, and the adversarial bracket shows how much worse it *could* be.
* `standard` package, `grid512`, block-average rows, nominal map — not the cell endpoint and not a
  polytope supremum, both of which would move the numbers further in the refusing direction.
* This does not license any statement about physical feasibility. It licenses one statement:
  **the current thermal inputs omit enough heat to change verdicts, so they must be corrected before
  anything is built on them.**
