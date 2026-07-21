# Custom CUDA HotSpot evidence record

## Verdict and scope

The backend is **ADMITTED** for steady-state `grid64-avg` and `grid128-avg`
operator construction with fixed linear package physics. CPU HotSpot remains
the truth backend for calibration and witness replay. The block model remains
on CPU. Leakage feedback, natural-convection package iteration, microchannels,
non-average mapping, non-SPD systems, and non-convergence fail closed.

This is not the simplified Rodinia thermal stencil. Pinned HotSpot constructs
the conductance matrix, ambient right-hand side, block power basis, and
grid-to-block map. The custom FP64 CUDA implementation solves that exported
system for all zero/unit-power right-hand sides as one batch. Rodinia is pinned
only as licensed GPU-HotSpot provenance; no Rodinia material constant or fitted
power scale enters the result.

## Claim-grade result

The run used implementation commit `9b3f645d2d5a3160aa0a0e23bb81bff1cc340283`
on `hpclab03`, an NVIDIA A800 80GB PCIe (SM80), driver `570.133.20`, and CUDA
12.8 build `35404655_0`. It used the pinned 227-block ThermoDSE floorplan and
name-aligned placed-power trace. End-to-end GPU time includes HotSpot system
export, host/device transfer, FP64 solve, block mapping, and output parsing.

| Grid | CPU operator | GPU operator | Speedup | Worst temperature error | Decisions |
|---|---:|---:|---:|---:|---:|
| 64 x 64 | 22.2157 s | 0.8412 s | 26.41x | 0.0003752 K | 5/5 match |
| 128 x 128 | 71.7407 s | 3.0795 s | 23.30x | 0.0005318 K | 5/5 match |

Across zero ambient, all 227 one-watt impulses, zero, uniform, ramp, frozen
random, and placed power, all 14 checks pass the frozen `0.01 K` bound. The
ten direct-power cases also produce identical conservative
`SAFE`/`REJECT`/`NUMERICAL_GAP` states under the same `330 K` decision rule and
error allowance. Candidate ordering cannot change an ordered DSE outcome when
every candidate state is unchanged; full DSOS policy runtime is deliberately a
separate experiment.

The solver reached freshly recomputed true relative residuals of approximately
`5.0e-12`, below the declared `1e-11` tolerance. The 227-block batches contain
228 right-hand sides, including a partial final 32-wide tile.

## Correctness and determinism

- Remote Python suite: 75 passed.
- `compute-sanitizer --tool memcheck`: 0 errors.
- `compute-sanitizer --tool racecheck`: 0 hazards, 0 warnings.
- `ptxas`: at most 32 registers/thread and zero spills; the selected
  `(32, 8, 1)` block is not register- or shared-memory occupancy limited on
  SM80.
- Three complete 30-block CPU/GPU parity repetitions produced the same
  `parity.tsv` digest,
  `7f717c7287c4d2a0c1c5afc5b2ad7c15819cb086c3fb05a5f966bf17f8833296`.
- After excluding the intentionally variable 56-byte timing header, the three
  CUDA temperature payloads were byte-identical at each resolution:
  `6c98d2b3960e84beefa562516ec6dd3677186fc754889e827261b4ff456c933b`
  (64 x 64) and
  `16cb642c053e4633c5097b84901e4af662516d0faefc71ba1e201ce0f6ce2624`
  (128 x 128).

An earlier atomic-reduction implementation passed temperature parity but once
failed the true-residual gate near its threshold. That negative result was not
discarded. Commit `7443f01` replaced scheduling-dependent FP64 atomics with a
fixed-order two-stage reduction and added a recurrence-residual safety margin;
the final admission test still uses the original true-residual tolerance.

## Reproduction

From a recursive fresh clone on the GPU server:

```bash
make gpu-bootstrap
CUDA_VISIBLE_DEVICES=0 make gpu-check
CUDA_VISIBLE_DEVICES=0 make gpu-production-parity
```

The fresh-clone `gpu-check` completed with a clean superproject and clean
HotSpot, Rodinia, SuperLU, and ThermoDSE submodules. The raw benchmark systems,
temperatures, direct replays, sanitizer output, and build log remain outside
Git on the execution server.

Selected evidence digests:

| Artifact | SHA-256 |
|---|---|
| CPU HotSpot binary | `b0040b3ecb82897e4f95dc827de643d9b545ef6cca9a2e5c1bdc8a6d7a1c68f4` |
| HotSpot system exporter | `f36f40fb7ed7e8736de5594365b9d2d3d9dff927d27a6c34eac497909dc891ad` |
| Custom CUDA solver | `d6ccaddd921bda69e3f6884e4053ff056f4fae39d0479e9ac8b088fde0c19767` |
| 227-block floorplan | `2d5334b7488eabcd5eb58d8781a605b8071732ff83268a581c1c32cc62efa7d0` |
| Placed-power trace | `56b2367794eaed29ba7f7ae883a4720f9dd9e51e193954761d61b86bf57dfec4` |
| Final production parity TSV | `e8625c493497e8d541cf091bca066b17fda00d3adcc4255835da0e1eb50618aa` |
| Final production timing TSV | `7512c6ab58fdd1b992a44010ab59be6b529ee341a1bdb9b4cef05bdb08e83153` |

## Reviewer dissent at close

| Severity | Objection | Closing evidence | Status |
|---|---|---|---|
| Critical | The code may solve Rodinia's simplified single-layer stencil rather than the registered package model. | Exact `G,q0,B,M` export from pinned HotSpot plus CPU direct replay. | FIXED |
| Critical | A small recurrence residual may hide unacceptable temperature error. | Fresh true residual, all impulses, five direct powers, and maximum error below 0.000532 K. | FIXED |
| Major | GPU speed may disappear outside a 30-block toy case. | Same-machine 227-block end-to-end speedups of 23.30x--26.41x. | FIXED |
| Major | Floating-point atomics may make certificates nondeterministic. | Fixed-order reduction and three byte-identical payload repetitions. | FIXED |
| Major | PCG is invalid for nonlinear or non-symmetric physics. | Python and C capability checks; unsupported configurations fail visibly. | SCOPE-EXCLUDED |
| Major | GPU operator parity alone proves the full DSOS method is faster. | No such claim is made; dev/held-out DSOS timing remains a separate gate. | OPEN |

The next evidence owner is the experiment gate: run the frozen dev suite with
GPU operator construction, confirm all ordered decisions and certificates
against CPU direct replay, then run held-out without changing tolerances or
backend parameters.
