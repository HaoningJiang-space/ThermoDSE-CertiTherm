# V6.1 source-subset isolation under a fixed additive power trace

Recomputed from the manifest rows by `research/triangle/v61_render_evidence.py`: the subset enumeration, every row's classification, the crossing coalitions, the leave-one-out table, the energy ledger, convergence, cross-row provenance, and the gate verdicts (against the pinned registration `docs/registration/v61_grid64_counterexample.json`, not the manifest's own copy of them). Any disagreement is a refusal. **Producer-reported, and not independently re-derivable here:** the temperature scalars themselves, the superposition residual, the execution receipts, and the scope sentence.

## Provenance

- commit `74e36a79f1cc`, working tree CLEAN at start and end (`provenance_stable = True`)
- candidate `transformer` / `arch_b`, model `grid64-max`, requested step 0.5 us, ambient 318.15 K, limit 330.0 K
- host `hpclab03`, Linux-5.15.0-71-generic-x86_64-with-glibc2.29, Python 3.8.10, NumPy 1.24.4, schema 3
- run `74e36a79-grid64-max-0.5us-1785050668`, wall 66.3 min
- every input staged read-only, hashed as read, re-verified after each replay:
  - `config` `b5956b0d44880986…`
  - `floorplan` `97fd0c067b9d7b3a…`
  - `hotspot` `b0040b3ecb82897e…`
  - `materials` `d958a3263b196659…`
- superposition identity, subset == sum of singletons: worst `0.000e+00` W (producer-reported)

**This run is not an independent numerical confirmation of the registered numbers, and nothing here should be read as one.** The staged HotSpot binary is byte-identical to the one used by the earlier transient work (`docs/GPU_HOTSPOT_EVIDENCE.md:86`). With the same binary, inputs, code and platform, agreement to the last printed digit — including the `1.245e-07` K steady residual against a value quoted to six decimals — is what arithmetic requires. It evidences a reproducible build and an intact provenance chain; it evidences nothing about the physics and nothing about whether a solver ran.

### Execution receipts (producer-generated audit receipts, not proof of execution)

Every row records that its directory and HotSpot workspace did not exist beforehand, its PID, a wall window inside the run's, this run's nonce, its HotSpot invocation count, and a SHA-256 of every workspace file. Across 15 rows: **54 HotSpot invocations**, **54 HotSpot output files** and 54 driver-written `.ptrace` inputs, all hashed. The invocation count is checked against the count implied by each row's converged cycle count, and the expected output filenames must be present — so an inconsistent producer is caught. A *dishonest* producer is not: these fields are self-attested and nothing here re-hashes the artefacts at render time. That is the remaining gap, and it is the reason this section is not called proof.

| subset | invocations | HotSpot outputs | wall (s) | cycles |
| --- | ---: | ---: | ---: | ---: |
| `core` | 3 | 3 | 139.7 | 8 |
| `noc` | 3 | 3 | 130.9 | 8 |
| `nop` | 3 | 3 | 122.0 | 8 |
| `dram` | 4 | 4 | 348.4 | 16 |
| `core-noc` | 3 | 3 | 131.2 | 8 |
| `core-nop` | 3 | 3 | 137.2 | 8 |
| `core-dram` | 4 | 4 | 364.7 | 16 |
| `noc-nop` | 3 | 3 | 131.8 | 8 |
| `dram-noc` | 4 | 4 | 341.4 | 16 |
| `dram-nop` | 4 | 4 | 345.9 | 16 |
| `core-noc-nop` | 4 | 4 | 346.7 | 16 |
| `core-dram-noc` | 4 | 4 | 355.3 | 16 |
| `core-dram-nop` | 4 | 4 | 364.4 | 16 |
| `dram-noc-nop` | 4 | 4 | 343.2 | 16 |
| `full` | 4 | 4 | 354.8 | 16 |

## Source energy ledger

Reproduced exactly by all 15 rows: each row's retained energy equals the sum of its components' entries here, to 1e-15 J.

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
| `core-nop` | 326.768648 | 326.95 | +0.18 | `ubuf_13` | `ubuf_13` | 8 | below |
| `core-noc` | 327.799962 | 328.12 | +0.32 | `mtxu_16` | `mtxu_16` | 8 | below |
| `core-dram` | 327.975129 | 328.20 | +0.22 | `mtxu_16` | `mtxu_16` | 16 | below |
| `core-noc-nop` | 328.198340 | 328.51 | +0.31 | `mtxu_16` | `mtxu_16` | 16 | below |
| `core-dram-nop` | 328.412897 | 328.61 | +0.20 | `ubuf_13` | `mtxu_16` | 16 | below |
| `core-dram-noc` | 329.506452 | 329.78 | +0.27 | `mtxu_16` | `mtxu_16` | 16 | below |
| **full** | 329.904867 | 330.19 | +0.29 | `mtxu_16` | `mtxu_16` | 16 | **CROSSING** |

HotSpot reports transient temperature to 0.01 K, so with a 330.0 K limit a row is `crossing` iff `periodic >= 330.01` K, `below` iff `periodic <= 329.99` K, and `indeterminate` otherwise — exactly 330.0 K is **not** a crossing. Indeterminate rows: none. Every row converged to within its 0.01 K tolerance, which equals the output quantum: convergence is at the observability floor, not below it.

## Gate

Recomputed against `docs/registration/v61_grid64_counterexample.json`, whose registered tuple the manifest must match exactly:

- decision — steady < 330.0 K **and** the full row classifies as `crossing` under the same quantisation rule as every other row: **True**
- periodic value within one 0.01 K quantum of the registered 330.19 K: **True**
- reported argmax equals the registered `mtxu_16`: **True**

**The location check is not a location claim.** The full row's top-two gap is `0.00` K — its argmax is tied with `ubuf_16` at the reported resolution. `mtxu_16` is in the tie set (**True**), which is the most that can be asserted; exact argmax equality holds only because of how the tie is broken, and a change of tie-break order would flip it and fail this gate for no physical reason. **This has already happened**: refactoring the argmax from a flat maximum over (sample, block) to a per-block maximum changed one row's reported label with every temperature unchanged. The driver still gates on exact equality; making it gate on tie-set membership is an open item.

**The gate binds names and temperatures, NOT the registered instance** (`binds_instance_hashes = False`, `canonical_trace_sha256 = None`). It does not verify that the registry, power trace or routing are unchanged, so a changed registry under the same workload/architecture names would still pass. Closing that needs a canonical trace hash preregistered from a run that is itself claim-grade. Open gap.

## Result

The 15 rows exhaust every non-empty subset of {`core`, `dram`, `noc`, `nop`} with no indeterminate row, and exactly one of them crosses: **`core+dram+noc+nop`** is the unique minimal crossing coalition in this factorial. That is a statement about this trace, this candidate and this discretisation — not about candidates, traces or discretisations in general.

### Leave-one-out is an arithmetic consequence, not a second finding

The full set crosses by only **+0.19 K** (330.19 K against a 330.0 K limit). Every removal costs at least a full 0.01 K quantum more than that excess (smallest: +0.41 K for `nop`), so once the exhaustive factorial shows the full set is the only crossing subset, all 4 leave-one-out verdicts follow with no further information. This is **Boolean threshold necessity within a fixed factorial**, not a measure of physical causal importance.

| removed source | periodic (K) | removal delta (K) | delta / excess | margin to limit (K) | status |
| --- | ---: | ---: | ---: | ---: | --- |
| `core` | 324.47 | +5.72 | 30.1x | +5.53 | below → necessary in the grand coalition |
| `dram` | 328.51 | +1.68 | 8.8x | +1.49 | below → necessary in the grand coalition |
| `noc` | 328.61 | +1.58 | 8.3x | +1.39 | below → necessary in the grand coalition |
| `nop` | 329.78 | +0.41 | 2.2x | +0.22 | below → necessary in the grand coalition |

The informative row is the smallest. `nop` carries 5.377% of the dissipated energy yet its removal drops the periodic peak by 0.41 K — 2.2x the excess and 41x the 0.01 K quantum. Energy share does not predict which source decides the threshold; the deltas do, and they are what a paper table should carry rather than the necessity label.

## Appendix — the reported argmax block is mostly not resolvable

In **11 of 15** subsets the periodic argmax is tied with at least one other block at the reported resolution, and in most of those the top-two gap is exactly 0.000e+00 K — far below quantisation, i.e. the two blocks are assigned the same temperature by the model, not merely rounded to it. Under `grid64-max` a block's temperature is the maximum over the grid cells covering it, so two blocks sharing the hottest cell receive identical values; that is the leading explanation and it is **UNTESTED** here.

2 subsets report a different argmax label for the two semantics:

| subset | steady argmax | periodic argmax | steady gap (K) | periodic gap (K) | periodic tie set | relocation? |
| --- | --- | --- | ---: | ---: | ---: | --- |
| `core-dram-nop` | `ubuf_13` | `mtxu_16` | 0.00 | 0.00 | 2 | NO — a tie broken differently |
| `dram` | `dram_x0_y4` | `dram_x0_y0` | 0.00 | 0.00 | 4 | NO — a tie broken differently |

A label change counts as a relocation only if BOTH endpoints are resolvable: the old block outside the new tie set, the new block outside the old one, and both gaps above one quantum. 2 of 2 fail that test (`core-dram-nop`, `dram`), so they are not evidence that a peak moved.

## Scope

Evidence grade: **run-provenance-controlled, registry-instance-unbound, single-capture HotSpot evidence with producer-attested execution receipts.** The staged hashes establish integrity within this execution; `binds_instance_hashes = False` leaves the identity link to the originally registered trace and routing open; no independent thermal model has validated any number here. (The run recorded its own grade as "provenance-controlled, single-capture HotSpot evidence for the registered candidate and discretisation; no independent thermal-model validation" — producer-reported, superseded by the above.)

Bounded to: this fixed trace; this fixed routing and timing; an additive deposition intervention; the HotSpot model, candidate and discretisation; and the **fixed decomposition of 23.163 mJ into `core`, `dram`, `noc`, `nop`** — a different assignment of the same total would change every row, and that assignment is an artefact of the routed-trace lowering, not a measurement. Says nothing about temperature-dependent power feedback. NOT established: that any source alone suffices; that periodic uplift is baseline-independent (as a fraction of the steady rise above ambient it spans 1.89% for `dram-nop` to 5.02% for `noc`, and the 0.01 K quantum is already 0.37% of `noc`'s rise, so any source-identity effect is `UNTESTED`); generalisation to other candidates, models or discretisations; or agreement with any independent thermal model.

`grid128-max` has not been run as a factorial. Its registered argmax (`ubuf_13` steady / `ubuf_16` periodic, `docs/V6_PHYSICAL_TRACE_GATE.md:149`) differs from this run's `mtxu_16`, but given how few argmax labels here are resolvable that difference cannot currently be read as a spatial finding. A grid128 factorial would need its own preregistration and is only required if the paper claims resolution robustness or a spatial mechanism.

Manifest: `artifacts_receipts/v61_cg3_schema3/v61_manifest.json`
