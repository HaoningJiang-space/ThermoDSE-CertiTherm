# Module granularity needs a core data-model change, not a reframing

ANALYSIS 2026-07-30, worked out before any implementation. NON-CLAIM.

## Why the direction is attractive

`docs/TRACTABILITY_FRONTIER.md` measures exact synthesis proving optimality up to about 40
blocks and collapsing at 48. Real dev candidates carry 181-237 blocks, 5-6x beyond it, and
every run against them is UNRESOLVED. But the same candidates carry **10 modules**, 4 region
groups and 0-4 chiplets, and the block-to-module mapping already exists in committed code --
`measurements._module_labels` derives it from block names and the module-level measurement
actions already depend on it.

Ten evaluation points against a forty-point frontier is comfortable margin, and it is the
granularity at which the decision is actually made: ThermoDSE ranks chiplet ARCHITECTURES by
EDYP, a stage that has no block-level floorplan. Per-block post-route extraction belongs to a
later stage.

So the hypothesis was that the method is fine and the granularity is wrong.

## Why it is not free

Coarsening replaces 227 per-block evaluation points with 10 per-module ones, and a module's
row must summarise its blocks. Two summaries are available and they point opposite ways:

| envelope | relation to the true peak | sound for |
| --- | --- | --- |
| elementwise **max** over the module's rows | **>=** true peak | **SAFE** -- "envelope below the limit" implies every block is |
| elementwise **min** over the module's rows | **<=** true peak | **REJECT** -- "envelope above the limit" implies some block is |

Verified numerically on a three-block module: true peak 4.1450, upper envelope 4.5285, lower
envelope 2.1620.

Using the upper envelope for REJECT is fail-OPEN -- an envelope above the limit does not mean
any block actually exceeds it, so the method would certify against worlds that cannot occur.
Using the lower envelope for SAFE is fail-open the other way.

**So SAFE needs one response array and REJECT needs a different one.** `ThermalFamily` carries
exactly one, `response_k_per_w`, and both `robust_safe_cell_rows` and `reject_cell_rows`
derive from it. The asymmetry is not expressible.

### The lazy option does not rescue it

Using the upper envelope for both is tempting because SAFE stays sound. It fails on the other
side: the coarse SAFE set is a SUBSET of the true one (the envelope is stricter), so coarse
collisions do not cover true collisions, and separating every coarse collision does not imply
separating every true one. That yields neither a valid lower bound nor a valid sufficient
plan.

## What this is an instance of

The same structural coupling that invalidated the per-cell decomposition
(`docs/PER_CELL_DECOMPOSITION_RETRACTED.md`): SAFE and REJECT are derived from one object, so
any operation intended to touch one touches both. There it was restricting cells; here it is
coarsening rows. `reject_specs` solved the first case by moving the restriction to the scan
rather than the family. There is no analogous move here, because coarsening changes the rows
themselves.

The difference worth recording is when it was found. The per-cell error survived four commits
and five reported numbers before a test caught it. This one was found by working out the
soundness before writing any code.

## What it would take

`ThermalFamily` would have to carry separate SAFE and REJECT response arrays -- upper and
lower envelopes of the same underlying operator -- with `robust_safe_cell_rows` and
`reject_cell_rows` reading their own. That is a change to the frozen core data model and to
the two functions every collision LP is built from, so it is tier-2 or tier-3 work: reviewed
before running, not after.

The frontier argument is untouched by any of this and still holds: ten points against a
forty-point frontier. The direction remains the most promising one measured in this session.
It is simply a method change rather than a reframing, and it should be entered as one.

## Scope

Analysis plus a numerical check of the two envelope inequalities. No implementation, no
measurement on real instances, nothing claimed.
