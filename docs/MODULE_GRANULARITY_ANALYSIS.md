# Module granularity is closed: the sound envelope is too weak to decide anything

ANALYSIS 2026-07-30, closed the same day, before any implementation. NON-CLAIM.

Outcome: **do not enter.** The coarsening is sound in the direction claimed and still useless,
which no soundness argument would have revealed. Two independent lines of evidence agree — a
measurement (below) and a peer review that derived the same conclusion from set inclusion.
Pinned by `CertiTherm/tests/test_module_envelope_properties.py` (18 tests).

## The direction, and why it looked attractive

`docs/TRACTABILITY_FRONTIER.md` measures exact synthesis proving optimality up to about 40
blocks and collapsing at 48. Real dev candidates carry 181-237 blocks and every run against
them is UNRESOLVED. The same candidates carry **10 modules**, and coarsening 227 per-block
evaluation points to 10 per-module ones would put the instance back inside the frontier — at
the granularity where ThermoDSE actually ranks architectures, a stage with no block-level
floorplan.

The hypothesis was that the method is fine and the granularity is wrong.

## The envelopes are sound, in opposite directions

A module's row must summarise its blocks, and the two available summaries point opposite ways:

| envelope | relation to the true peak | sound for |
| --- | --- | --- |
| elementwise **max** over the module's rows | **>=** true peak | **SAFE** — "envelope below the limit" implies every block is |
| elementwise **min** over the module's rows | **<=** true peak | **REJECT** — "envelope above the limit" implies some block is |

`ambient_k` needs the same treatment in the same opposite directions: it is per (model, point),
so coarsening points coarsens it too. SAFE subtracts it, so the tightest constraint takes the
module's LARGEST ambient; REJECT subtracts it, so the hardest threshold takes the SMALLEST.
`error_k` needs no envelope — it is per model and broadcast over points.

None of this is in doubt. It is also not the problem.

## What kills it: the sound REJECT envelope is nearly empty

The lower envelope is elementwise `min`, so it sits far below any single row. Measured across
six random four-block modules, its temperature rise is a **median 47% of the true peak rise**
(0.35–0.57 over the six):

|  seed | true peak rise | upper envelope | lower envelope | lower/true |
| --- | --- | --- | --- | --- |
| 0 | 5.943 | 6.440 | 2.077 | 0.35 |
| 1 | 4.897 | 5.458 | 2.402 | 0.49 |
| 2 | 4.867 | 6.049 | 2.191 | 0.45 |
| 3 | 4.969 | 5.897 | 2.681 | 0.54 |
| 4 | 5.871 | 7.193 | 3.320 | 0.57 |
| 5 | 5.321 | 6.444 | 2.194 | 0.41 |

A power map would need roughly **twice** the power it actually takes to reject before the
envelope agreed. Under a bounded power polytope the coarse REJECT set is then empty: over 2 000
sampled worlds per module with the limit placed at the median achievable peak, truly rejecting
worlds exist and the lower envelope rejected **none of them**. No reject worlds means no
collisions, means a coarsened instance that returns cost 0 while proving nothing.

This is what the test suite found. The property was first checked by an ad-hoc script that
reported "0 violations" — technically true, and uninformative, because the violation count of a
predicate that never fires is zero. The test's non-vacuity guard is what turned that into a
finding.

## Peer review reached the same place from set inclusion

Reviewed at tier 2 before implementation (Codex, `gpt-5.6-sol`, medium). Verdict: **not
established as a sound replacement; conditionally viable only as a lower-bound relaxation.**
Four of its findings correct this analysis, not just confirm it.

**1. Both envelopes are inner, so the coarse instance can never certify the registered
decision.** With `S_in ⊆ S` and `R_in ⊆ R`, the collision sets satisfy `C_in(A) ⊆ C_true(A)`.
Absence of coarse collisions therefore does **not** imply absence of registered collisions. The
coarsening enlarges the undecided region; a coarse plan certifies only "distinguishable under
the affine envelopes", not the registered 330 K per-block decision. `C*_in <= C*_true` still
holds, so an exact coarse optimum is a valid **lower bound** — and the measurement above shows
that bound is ~0, far below production's existing 22.8–88.3. The review's own registered kill
condition ("kill if the exact inner optimum does not exceed the existing production lower
bound") is met, measured, before any migration.

**2. The reason for rejecting "upper envelope for both" was incomplete.** This document
previously argued only that the coarse SAFE set is a subset, so true collisions can vanish.
That shows the upper/upper collision set is not a superset; it does not show it is not a subset
either. The missing half is that the upper envelope also **invents** reject worlds that no
block rejects. With both halves the sets are incomparable in either direction — strictly
stronger than the original argument. Both are now tested.

**3. `_module_labels` is not a registered module map.** It is
`re.sub(r"\d+$", "", block.split("_", 1)[0])` (`CertiTherm/measurements.py:13`) — a private
name heuristic. Its existing use for measurement actions does not establish that its ten groups
equal ThermoDSE's architectural module identity, and this analysis had treated "the mapping
already exists in committed code" as if it did.

**4. The blast radius was understated as "`ThermalFamily` plus two row builders".** The review
enumerated roughly twelve affected sites: `ThermalFamily` validation and dimensional identity,
all three constraint builders including `reject_cell_floor`, `_CollisionProblem` and the
collision LP construction, `certificate.validate_collision`, the thermal kernel's flat reject
indices and binding digest, the kernelized oracle, `_thermal_digest`, the NPZ
`save_family`/`load_family` schema, calibration and replay (which compares a per-block vector
against a same-shaped prediction and cannot compare ten modules to 227 blocks elementwise),
decision reporting, and spectral diagnostics.

**5. The frontier comparison was not like-for-like, so "comfortable margin" is withdrawn.** The
tractability probe reduced response rows, response columns, the power-polytope dimension, and
the action library together. Module coarsening reduces SAFE rows and REJECT LPs while leaving
181-237 power variables and roughly the full action library intact. It does not put the
instance into the measured ten-block regime, and this document's claim that it did is
unsupported. Separately, the envelopes are derived from one block-level HotSpot operator and
floorplan, so they are not architecture-stage quantities unless invariance over admissible
intra-module floorplans is proved.

## What this is an instance of

The same structural coupling that invalidated the per-cell decomposition
(`docs/PER_CELL_DECOMPOSITION_RETRACTED.md`): SAFE and REJECT derive from one object, so an
operation intended to touch one touches both. There it was restricting cells; here it is
coarsening rows, and `reject_specs` has no analogue because coarsening changes the rows.

The difference worth recording is the cost. The per-cell error survived four commits and five
reported numbers before a test caught it. This one cost one analysis and one test file, and was
closed before a line of the data model moved — because the load-bearing premise was written as
a test with a non-vacuity guard instead of as prose.

## What would reopen it

Nothing in the near term. If it is ever revisited it is as a separately typed, receipt-bound
**inner relaxation** that leaves the per-block family authoritative — used for lower bounds or
candidate-plan proposals, with every plan validated by the unchanged full per-block oracle
before any verdict — and not as a replacement for the registered decision semantics. It would
need the affine-envelope lemma covering response, ambient, error and numerical margin; a
registered block-to-module map asserted against actual block IDs; and the artifact schema
migration above. It would still have to clear the kill condition that the measurement in this
document currently fails.

## Scope

Analysis, a numerical measurement of the envelope gap on six synthetic modules, and one tier-2
peer review. No implementation, no run on real instances, nothing claimed.
