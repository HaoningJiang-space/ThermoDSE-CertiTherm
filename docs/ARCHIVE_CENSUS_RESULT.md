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

For the archive's 329.7 K on `arxv017` the implied total thermal resistance is 2.3 K/W against this
pipeline's 0.76 K/W on the same design -- a factor of **3**.

### What has been ruled out, by measurement

* **The package is NOT the explanation.** `ThermoDSE/test/test.config` and `packages.tsv:default`
  agree item for item: `r_convec` 0.1, `s_sink` 0.06, `t_sink` 0.0069, `s_spreader` 0.05,
  `t_spreader` 0.001, `t_interface` 2.0e-05, `ambient` 318.15, `t_chip` 1.5e-4. An earlier revision
  of this document proposed a package mismatch as the leading hypothesis; **that is withdrawn.**
* **The power map is NOT obviously under-counted.** On `arxv017` the capture's own
  `energy_mj / latency_ms` is 4.73 W against a placed-map total of 5.633 W -- a 19 % peak-versus-mean
  spread, not a missing component.
* **The grid mapping is NOT the explanation.** ThermoDSE runs `model_type block` with
  `grid_map_mode avg`, the same convention this pipeline certifies against.

### What is left, and it is geometric

The floorplan this pipeline receives is **mostly zero-power filler**:

| | blocks | powered area | zero-power filler |
| --- | --- | --- | --- |
| `arxv017` | 23 (18 powered) | 17.33 mm^2 (42 %) | **24.29 mm^2 (58 %)** |
| `arxv008` | 23 (10 powered) | 18.91 mm^2 (28 %) | **49.04 mm^2 (72 %)** |
| `arch_b` (development) | 227 (180 powered) | 152.33 mm^2 (54 %) | 128.05 mm^2 (46 %) |

The filler is `eblk*`, `blockX`, `blockY`. It conducts and spreads but generates nothing, and the
census designs carry proportionally far more of it than the development registry -- their floorplan
bounding box is **2.2 - 2.4x the chiplet area** recorded in the capture's own `die_w_list_m` /
`die_h_list_m`. The same watts over more silicon run cooler, which is the sign and roughly the
magnitude of the gap.

### Five hypotheses, all refuted by measurement

`arxv000`, archive line: **329.9 K**, EDYP **810.7**.

| hypothesis | test | result |
| --- | --- | --- |
| different package | item-by-item config comparison | **refuted**, identical |
| under-counted power map | `energy/latency` 4.73 W vs placed 5.633 W | **refuted**, 19 % peak-vs-mean |
| different functional (cell max vs block average) | both read off the **same retained run**, 64 designs | **refuted**: +0.21 K median, +0.76 K max -- 40x too small |
| six-workload set vs one | run with `nets` set to the six `chiplet_eva` defaults | **peak 322.20 K**, only +0.30 K. Refuted for temperature |
| `thermal_map` / `wkld_idpdt` flags | all four combinations, six workloads | 322.2 - 323.0 K. Refuted |

**The EDYP scale IS explained by the workload set**: six workloads give EDYP **971.22** against the
archive's **810.7**, while one gives 15.95. That closes the ~51x EDYP discrepancy and leaves the
temperature one open.

### The temperature gap is UNEXPLAINED, and that is the operative conclusion

Every reproducible knob has been tried. What remains are provenance-level candidates that the
current tree cannot settle -- a different HotSpot build, a different generated config or floorplan
revision at the time the archive was produced, or a stale stored value. Peer review is right that
source reading cannot establish the provenance of numbers stored months ago.

**So the decision-relevant answer is not the mechanism, it is this: the archive's reported peak
temperatures are not reproducible from the pinned submodule at its current revision, to within 7 K.**
The archive remains usable as a source of *design vectors* -- the design under test reproduces
exactly, area `5.7887e-05` to the digit -- but **its thermal column cannot be used to select or screen
a population**, which is precisely what `archive-census-v1` did and precisely why the census was
non-informative.

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
