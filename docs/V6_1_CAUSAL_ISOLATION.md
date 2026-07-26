# V6.1 source-subset isolation under a fixed additive power trace

Every number and every classification below is **recomputed from the manifest rows** by
`research/triangle/v61_render_evidence.py`, which refuses to emit anything unless the
manifest has `complete: true` and `gate.passed: true` **and** its own recomputation of
the subset enumeration, the quantisation-aware classification, the minimal crossing
coalitions, the leave-one-out table and the energy ledger agrees with the manifest's
`summary`. The two facts that are not in the manifest (this run's binary versus the
earlier one, and the grid128 registered blocks) are read out of the committed documents
cited beside them, and a source that no longer states the value is a refusal.

## Provenance

- commit `842e3ffdd3c8`, working tree CLEAN
- provenance re-verified at end of run: `provenance_stable = True`
- candidate `transformer` / `arch_b`, model `grid64-max`, requested step 0.5 us, ambient 318.15 K, limit 330.0 K
- host `hpclab03`, Linux-5.15.0-71-generic-x86_64-with-glibc2.29, Python 3.8.10, NumPy 1.24.4
- run id `842e3ffd-grid64-max-0.5us-1784993896`, wall 66.2 min
- every input staged read-only and hashed as read; re-verified after each replay
  - `config` `b5956b0d44880986…`
  - `floorplan` `97fd0c067b9d7b3a…`
  - `hotspot` `b0040b3ecb82897e…`
  - `materials` `d958a3263b196659…`
- superposition identity, subset == sum of singletons: worst `0.000e+00` W

The HotSpot binary staged here is **byte-identical** to the one used by the earlier transient work (`docs/GPU_HOTSPOT_EVIDENCE.md:86` records the same SHA-256). The build is therefore reproducible — but it also means this run cannot be an *independent numerical* confirmation of the earlier numbers: identical inputs through an identical binary are arithmetically determined to agree. What it confirms is the provenance chain, not the physics.

**Fresh execution is asserted by policy, not proven by this document.** `summary.all_rows_fresh = True` echoes the driver's no-reuse constant; the manifest carries no per-row process receipt (no command line, PID, exit status, start/end time, or hash of the raw HotSpot output). Nothing here would distinguish 15 solver executions from 15 reads of a cache. Closing it needs per-row invocation and raw-output evidence, which is an open gap.

## Source energy ledger

Reproduced exactly by every one of the 15 rows: each row's retained energy equals the sum of its components' entries here (checked to 1e-15 J).

| source | energy (mJ) | share |
| --- | ---: | ---: |
| `core` | 12.747382 | 55.033% |
| `dram` | 5.550965 | 23.965% |
| `noc` | 3.619128 | 15.625% |
| `nop` | 1.245560 | 5.377% |
| **total** | **23.163035** | 100% |

## All 15 non-empty source subsets

| subset | time-mean steady (K) | periodic (K) | uplift (K) | steady argmax | periodic argmax | cycles | status |
| --- | ---: | ---: | ---: | --- | --- | ---: | --- |
| `nop` | 320.326022 | 320.42 | +0.09 | `blockX_1` | `blockX_1` | 8 | below |
| `noc` | 320.854258 | 320.99 | +0.14 | `ubuf_0` | `ubuf_0` | 8 | below |
| `noc-nop` | 321.676057 | 321.79 | +0.11 | `blockX_1` | `blockX_1` | 8 | below |
| `dram` | 322.857876 | 322.95 | +0.09 | `dram_x0_y4` | `dram_x0_y0` | 16 | below |
| `dram-nop` | 323.233830 | 323.33 | +0.10 | `dram_x0_y0` | `dram_x0_y0` | 16 | below |
| `dram-noc` | 323.965729 | 324.08 | +0.11 | `dram_x0_y0` | `dram_x0_y0` | 16 | below |
| `dram-noc-nop` | 324.341685 | 324.47 | +0.13 | `dram_x0_y0` | `dram_x0_y0` | 16 | below |
| `core` | 326.268802 | 326.54 | +0.27 | `mtxu_16` | `mtxu_16` | 8 | below |
| `core-nop` | 326.768648 | 326.95 | +0.18 | `ubuf_13` | `mtxu_16` | 8 | below |
| `core-noc` | 327.799962 | 328.12 | +0.32 | `mtxu_16` | `mtxu_16` | 8 | below |
| `core-dram` | 327.975129 | 328.20 | +0.22 | `mtxu_16` | `mtxu_16` | 16 | below |
| `core-noc-nop` | 328.198340 | 328.51 | +0.31 | `mtxu_16` | `mtxu_16` | 16 | below |
| `core-dram-nop` | 328.412897 | 328.61 | +0.20 | `ubuf_13` | `mtxu_16` | 16 | below |
| `core-dram-noc` | 329.506452 | 329.78 | +0.27 | `mtxu_16` | `mtxu_16` | 16 | below |
| **full** | 329.904867 | 330.19 | +0.29 | `mtxu_16` | `mtxu_16` | 16 | **CROSSING** |

Classification is quantisation-aware, with the boundary stated exactly. HotSpot reports transient temperatures to 0.01 K, so with a 330.0 K limit a row is `crossing` iff `periodic >= 330.01` K, `below` iff `periodic <= 329.99` K, and `indeterminate` otherwise — a value of exactly 330.0 K is **not** a crossing. Indeterminate rows this run: none. Every status in the table above was recomputed from `periodic_peak_k` by this rule, not read from the manifest.

## Gate

- decision (steady < 330.0 and periodic >= 330.0): **True**
- periodic value within one output quantum of the registered 330.19 K: **True**
- reported argmax block equals registered `mtxu_16`: **True**
- steady delta from the registered value: `1.245e-07` K (reported, **not** gated — no repeatability-derived tolerance exists; reported, not enforced)

The steady delta is `1.245e-07` K, i.e. the registered value is quoted to 6 decimals and the residual sits at that quoting resolution. **Near-exact agreement is not repeatability evidence.** With the same code, binary, inputs and platform, agreement to the last printed digit is what arithmetic requires; it does not distinguish a fresh solver run from a reused result. It would only be *suspicious* if presented as proof that the solver ran.

**The gate binds names and temperatures, NOT the registered instance** (`binds_instance_hashes = False`, `canonical_trace_sha256 = None`). It verifies that this pipeline reproduces the documented crossing at the documented location; it does **not** verify that the registry, power trace or routing are unchanged, so a changed registry under the same workload/architecture names could still pass. Closing that needs a canonical trace hash preregistered from a run that is itself claim-grade. Open gap.

## Result

- **minimal crossing coalitions:** `core+dram+noc+nop`
- the 15 rows exhaust every non-empty subset of {`core`, `dram`, `noc`, `nop`} with no indeterminate row, so `core+dram+noc+nop` is the **unique minimal crossing coalition in this factorial**. That is a statement about this trace, this candidate and this discretisation — not about candidates, traces or discretisations in general.

### Leave-one-out is an arithmetic consequence, not a second finding

The full set crosses by only **+0.19 K** (330.19 K against a 330.0 K limit).
Every source's removal costs more than that excess (smallest: +0.41 K for `nop`), so once the exhaustive factorial shows the full set is the only crossing subset, all 4 leave-one-out verdicts follow with no further information. This is **Boolean threshold necessity within a fixed factorial**, not a measure of physical causal importance.

| removed source | periodic (K) | removal delta (K) | delta / excess | margin to limit (K) | status |
| --- | ---: | ---: | ---: | ---: | --- |
| `core` | 324.47 | +5.72 | 30.1x | +5.53 | below → necessary in the grand coalition |
| `dram` | 328.51 | +1.68 | 8.8x | +1.49 | below → necessary in the grand coalition |
| `noc` | 328.61 | +1.58 | 8.3x | +1.39 | below → necessary in the grand coalition |
| `nop` | 329.78 | +0.41 | 2.2x | +0.22 | below → necessary in the grand coalition |

The informative row is the smallest one. `nop` carries 5.377% of the dissipated energy yet its removal drops the periodic peak by 0.41 K — 2.2x the +0.19 K excess, and 41x the 0.01 K output quantum. Energy share alone does not predict which source decides the threshold; the deltas do, and they are the quantity a paper table should carry rather than the necessity label.

## Appendix — reported-argmax changes (observations, not a mechanism)

In 3 of 15 subsets the **reported argmax block label** differs between the two semantics:
- `core-dram-nop`: steady `ubuf_13` → periodic `mtxu_16`
- `core-nop`: steady `ubuf_13` → periodic `mtxu_16`
- `dram`: steady `dram_x0_y4` → periodic `dram_x0_y0`

This says the argmax label changed. It does **not** establish that a physically meaningful peak relocated: periodic temperatures are reported only to 0.01 K, and the manifest records no second-hottest temperature, no top-two gap and no tie set, so a change between two blocks within one quantum of each other is indistinguishable from a tie broken differently. `dram_x0_y4` versus `dram_x0_y0` in particular may be a symmetry. These rows stay in this appendix and support no claim until the full temperature vector, the top-two gap and the tie-breaking rule are recorded. The crossing row's argmax is unchanged, so this is not the crossing mechanism either way.

## Scope

Evidence grade recorded by the run: **provenance-controlled, single-capture HotSpot evidence for the registered candidate and discretisation; no independent thermal-model validation**

Qualified by what the manifest itself states, the accurate grade is **run-provenance-controlled, registry-instance-unbound, single-capture HotSpot evidence**: the staged hashes establish integrity *within this execution*, while `binds_instance_hashes = False` leaves the identity link to the originally registered trace and routing open, and no independent thermal model has validated any number here.

Conditional necessity is bounded to THIS fixed trace, fixed routing and timing, an additive deposition intervention, and the HotSpot model. It is not general physical causality and says nothing about temperature-dependent power feedback.

One bound that sentence omits: the conclusions also depend on the **fixed decomposition of power into `core`, `dram`, `noc`, `nop`** given in the ledger above. A different assignment of the same 23.163 mJ to those four names would change every subset row, and that assignment is an artefact of the routed-trace lowering, not a measurement.

Explicitly NOT established: that any source alone suffices; that periodic uplift is baseline-independent — the uplift as a fraction of the steady rise above ambient spans **1.89% (`dram-nop`) to 5.02% (`noc`)** across the 15 subsets, computed here from the rows, and is resolution-sensitive where the rise is small (the 0.01 K quantum is 0.37% of `noc`'s rise), so any source-identity effect is `UNTESTED`; generalisation to other candidates, thermal models or discretisations; or agreement with any independent thermal model.

`grid128-max` has NOT been run as a factorial. Its registered hottest block (`ubuf_13` steady / `ubuf_16` periodic, per `docs/V6_PHYSICAL_TRACE_GATE.md:148` — externally supplied, not from this manifest) differs from this run's `mtxu_16` **and moves between the two semantics**, so a grid128 factorial would be a distinct discretised result requiring its own preregistration, not a resolution cross-check of this one. It is only needed if the paper claims resolution robustness, a spatial mechanism, or general source necessity; for the bounded grid64 existence claim made here it is not. A single grid128 full-trace row would not be an adequate causal cross-check either way.

Manifest: `artifacts_receipts/v61_claimgrade/v61_manifest.json` (run id `842e3ffd-grid64-max-0.5us-1784993896`)
