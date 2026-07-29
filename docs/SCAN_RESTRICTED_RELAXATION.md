# The repaired decomposition is sound, terminates, and does not help

MEASURED 2026-07-29, dev split, one candidate. NON-CLAIM.

`docs/PER_CELL_DECOMPOSITION_RETRACTED.md` withdrew a decomposition whose argument was false:
restricting the `ThermalFamily` to a few reject cells also drops their SAFE rows, and SAFE is
a conjunction over every (model, point), so the safe set GROWS and the restricted problem is
harder rather than easier. The retraction identified the repair -- restrict which cells the
oracle SCANS, leaving every SAFE row in place -- and this is that repair, measured.

## The property, checked before any number was taken from it

`reject_specs` restricts the scan only. Every SAFE row still binds, so the safe set is
unchanged and fewer reject options can only make separation easier:

    C*(whole)  >=  C*(scan-restricted)

`CertiTherm/tests/test_cell_subset_bound.py` checks this on small instances where synthesis
returns OPTIMAL, so both sides are exact: restricting the scan never raises the optimum across
five seeds and four subsets, widening the scan is monotone, and scanning every cell reproduces
the unrestricted optimum exactly. One test pins the contrast directly -- same instance, same
cell, the family restriction raises the optimum while the scan restriction does not.

That check is the difference between this and the retracted attempt, where the property was
asserted in prose across four commits and five numbers were reported before anything tested it.

## Measured on the real instance

`transformer` / `default` / `arch_b`: the real 227-block polytope, the real 243-action library,
the registered limit, 681 reject cells, of which the scan covers 1 or 2.

| scan width | status | certified bound | iterations | active cuts | seconds |
| ---: | --- | ---: | ---: | ---: | ---: |
| 1 | **OPTIMAL** | **24.0** (exact) | 1 021 | 994 | 186 |
| 2 | UNRESOLVED | 29.56 | 4 161 | 7 495 | 600 |

Two things worth separating.

**It terminates.** Scan width 1 returns OPTIMAL on the REAL instance in 186 s. Every other run
against a real 227-block candidate in this project's records is UNRESOLVED, including the full
1 800 s production runs. A scan-restricted relaxation is the first thing here to produce a
proof about the real problem rather than a bound.

**It does not help.** 24.0 and 29.56 both sit inside the production path's certified range of
22.8-88.3 for the same six dev queries. The bound rises with scan width, but tractability
collapses immediately -- width 1 proves in 186 s, width 2 does not resolve in 600 s -- so the
frontier is between one and two cells out of 681, and the reachable bounds are no better than
what the shipped method already reports.

## Why this also confirms the retraction

The invalid version reported 215, 260.73, 311.83 and 345.1 from restricting the family. The
valid version reports 24.0. The gap is not noise: restricting the family removed SAFE rows and
made the problem HARDER, so its optima were larger than the real instance's and the numbers
were inflated for exactly the reason that invalidated them. A correct relaxation must give a
SMALLER number, and it does.

## What this closes and what it leaves

Closed: cell-wise decomposition of the reject scan, done soundly, does not improve the
certified lower bound on this instance. The direction was worth testing and is now tested.

Left: the certified lower bound on the real instance is what the production path reports,
22.8 to 88.3. `reject_specs` remains in the codebase as a diagnostic -- it cannot certify that
no collision exists in the full instance, so `_collision` and `_collisions` keep their
certification semantics and do not expose it, and no default behaviour changed.

## Scope

One candidate, one package, one workload, dev split, scan widths 1 and 2, 600 s each. Nothing
here is claim-grade. Produced by `research/triangle/scan_restricted_bound_probe.py`.
