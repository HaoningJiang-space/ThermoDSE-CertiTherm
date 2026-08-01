# `archive-census-v1`: the claim holds, and it holds vacuously

RESULT 2026-08-01. Protocol frozen at `658163a` before any archive design was run; X and Y were not
read until every operator was built. Run log: `docs/ARCHIVE_CENSUS_RUN_LOG.md`.

## The preregistered verdict

| | measured | threshold | |
| --- | --- | --- | --- |
| **X**, certified fraction | **100.0 %** (64 of 64) | >= 20 % | PASS |
| **Y**, EDYP price of the cheapest certified design | **+0.0 %** | <= 30 % | PASS |
| UNRESOLVED | 0 of 64 | — | — |
| frontier size vs span | 64 at every span from 0.05 to 1.20 | — | — |

**CLAIM HOLDS.** And that is not the result.

## Why it is not the result

A preregistered test that passes at 100 % across a 24x sweep of the uncertainty parameter, with
nothing moving anywhere in the sweep, did not measure what it was built to measure. The margins say
so directly:

| quantity, at span 0.30 | min | median | max |
| --- | --- | --- | --- |
| `sup_p T` under the reference operator | 319.6 K | 321.8 K | 323.4 K |
| model-form band (`grid512` vs FEM) | 0.179 K | 0.632 K | 1.226 K |
| **certified slack** | **+5.40 K** | +7.49 K | +10.08 K |

**The tightest design in the whole census clears the limit by 5.40 K while the largest band anywhere
is 1.23 K.** Even at span 1.20 the tightest slack is +2.41 K. No design could have failed, so the
census contains no information about where the frontier is.

## The reason, and it is the real finding

The candidate set was selected on the **archive's own reported peak temperature** (<= 330 K, then
top-64 by EDYP). Re-deriving the same designs through this pipeline gives a systematically different
answer:

| | archive reported | this pipeline, nominal |
| --- | --- | --- |
| peak temperature | 327.0 - 330.0 K (median 329.2) | **319.4 - 322.4 K (median 321.2)** |

**The gap is +5.9 to +10.1 K, median +8.1 K, and it has the same sign on all 64 designs.** So a
selection rule that picked the designs sitting closest to 330 K under ThermoDSE's evaluation picked
designs sitting 8 K below it under this one.

That number is **7 to 45 times the model-form band** measured against an independent FEM solver
(0.18 - 1.23 K) and **24 to 200 times the complete HotSpot refinement tail** (0.05 - 0.34 K). It is
the largest single disagreement found anywhere in this work, and it is **not a thermal-model
question** -- both sides run HotSpot.

### Where it comes from, as a hypothesis with a measurement behind it

The census designs draw far less power than the development registry:

| | blocks | total power |
| --- | --- | --- |
| development architectures | 181 - 237 | 13.7 - 23.2 W |
| **archive census designs** | **13 - 111** | **3.05 - 6.98 W** (median 4.83) |

EDYP is `energy x delay / yield`, so ranking the archive by EDYP selects small, efficient designs,
and those draw 3-5x less power. At 4.8 W through this package the rise over a 318.15 K ambient is a
few kelvin, which is exactly what the pipeline reports.

For the archive's 329 K on the same design the implied total thermal resistance is about 2.3 K/W --
roughly five times what this package model gives. **The hypothesis is therefore that ThermoDSE's
archive was searched under a different package than `packages.tsv:default`**, which is consistent
with its 348 K design constraint being a different convention entirely. This is checkable and is not
claimed as established here.

## What this does and does not license

**It licenses:** the statement that the archive's reported peak temperature and a re-derivation of
the same design cannot be treated as the same quantity, quantified at 5.9 - 10.1 K one-signed over 64
designs; and the observation that selecting a thermal-stress population by another tool's thermal
number does not produce a thermally stressed population.

**It does not license:** any statement about the robust-feasible frontier on the ThermoDSE archive.
The frontier was not located, because nothing in this population is near it. `X = 100 %` must not be
quoted as "the archive is robustly feasible" -- it means "this candidate set was chosen so far from
the limit that the certificate could not bind".

**It does not retroactively weaken** the development-split result
(`docs/MODEL_FORM_AGAINST_AN_INDEPENDENT_SOLVER.md`), where the margins are 0.31 - 8.4 K against
bands of 0.25 - 1.06 K and the certificate does bind: there, 5 of 6 points certify and one does not.

## What a v2 would have to change

The failure is in the **selection rule**, not the certificate. A discriminating census needs a
candidate set near *this* pipeline's limit, which requires a screen this pipeline produces. The
cheapest such screen already exists and costs one HotSpot solve per design: the nominal peak under
`block`, which is ~100x cheaper than the `grid512` operator and was measured today to sit within
0.6 - 1.1 K of it. Preregistering `v2` on "designs whose `block` nominal peak lies within 3 K of the
limit" would select a population where the band is comparable to the margin, which is the regime the
claim is about.

That is a new freeze ID and a new document. `archive-census-v1` is closed as **PASS, non-informative**.
