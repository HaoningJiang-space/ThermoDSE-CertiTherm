# V6.1 causal isolation — which power sources produce the grid-max crossing

Generated from a validated manifest by `research/triangle/v61_render_evidence.py`; no
number here is hand-transcribed. The generator refuses to run unless the manifest has
`complete: true` **and** `gate.passed: true`.

## Provenance

- commit `842e3ffdd3c8`, working tree CLEAN
- provenance re-verified at end of run: `provenance_stable = True`
- candidate `transformer` / `arch_b`, model `grid64-max`, requested step 0.5 us, ambient 318.15 K, limit 330.0 K
- host `hpclab03`, Linux-5.15.0-71-generic-x86_64-with-glibc2.29, Python 3.8.10, NumPy 1.24.4
- every input staged read-only and hashed as read; re-verified after each replay
  - `config` `b5956b0d44880986…`
  - `floorplan` `97fd0c067b9d7b3a…`
  - `hotspot` `b0040b3ecb82897e…`
  - `materials` `d958a3263b196659…`
- all rows fresh (no reuse): `True`
- superposition identity, subset == sum of singletons: worst `0.000e+00` W

## Source energy ledger

| source | energy (mJ) | share |
| --- | ---: | ---: |
| `core` | 12.747382 | 55.033% |
| `dram` | 5.550965 | 23.965% |
| `noc` | 3.619128 | 15.625% |
| `nop` | 1.245560 | 5.377% |
| **total** | **23.163035** | 100% |

## All 15 non-empty source subsets

| subset | time-mean steady (K) | periodic (K) | uplift (K) | steady hottest | periodic hottest | cycles | status |
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

Classification is quantisation-aware: HotSpot reports transient temperatures to 0.01 K, so a row within one quantum of the limit is `indeterminate` and is excluded from the coalition analysis rather than counted as crossing. Indeterminate rows this run: none.

In 3 of 15 subsets the hottest block MOVES between the two semantics, so time structure relocates the peak and does not merely raise it:
- `core-dram-nop`: steady `ubuf_13` -> periodic `mtxu_16`
- `core-nop`: steady `ubuf_13` -> periodic `mtxu_16`
- `dram`: steady `dram_x0_y4` -> periodic `dram_x0_y0`

This is an observation, not a mechanism: it is not the crossing mechanism (the crossing row's hottest block is unchanged) and no source-identity cause has been tested for it.

## Gate

- decision (steady < 330.0 and periodic >= 330.0): **True**
- periodic value within one output quantum of the registered 330.19 K: **True**
- hottest block equals registered `mtxu_16`: **True**
- steady delta from the registered value: `0.000000` K (reported, **not** gated — no repeatability-derived tolerance exists; reported, not enforced)

**The gate binds names and temperatures, NOT the registered instance** (`binds_instance_hashes = False`). It verifies that this pipeline reproduces the documented crossing at the documented location; it does **not** verify that the registry, power trace or routing are unchanged, so a changed registry under the same workload/architecture names could still pass. Closing that needs a canonical trace hash preregistered from a run that is itself claim-grade. Open gap.

## Result

- **minimal crossing coalitions:** `core+dram+noc+nop`
- **leave-one-out** — is each source necessary given the others?

| removed source | periodic (K) | margin to limit (K) | status |
| --- | ---: | ---: | --- |
| `core` | 324.47 | +5.53 | below → conditionally necessary |
| `noc` | 328.61 | +1.39 | below → conditionally necessary |
| `nop` | 329.78 | +0.22 | below → conditionally necessary |
| `dram` | 328.51 | +1.49 | below → conditionally necessary |

## Scope

Evidence grade: **provenance-controlled, single-capture HotSpot evidence for the registered candidate and discretisation; no independent thermal-model validation**

Conditional necessity is bounded to THIS fixed trace, fixed routing and timing, an additive deposition intervention, and the HotSpot model. It is not general physical causality and says nothing about temperature-dependent power feedback.

Explicitly NOT established: that any source alone suffices; that periodic uplift is baseline-independent (the uplift/steady-rise ratio spans roughly 1.9–5.0% across the 15 subsets and is resolution-sensitive where the rise is small, so any source-identity effect is `UNTESTED`); generalisation to other candidates, thermal models or discretisations; or agreement with any independent thermal model.

`grid128-max` has NOT been run as a factorial. Its registered hottest block is `ubuf_13` (steady) / `ubuf_16` (periodic) — different from this run's `mtxu_16` **and moving between the two semantics** — so a grid128 factorial would be a distinct discretised causal result requiring its own preregistration, not a resolution cross-check of this one.

Manifest: `artifacts/v61_cg2_grid64/v61_manifest.json` (run id `842e3ffd-grid64-max-0.5us-1784993896`)
