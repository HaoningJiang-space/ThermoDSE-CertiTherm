# GPU HotSpot Backend Round

## Boundary

- Claim under test: a batched, double-precision CUDA steady-state backend can
  construct the registered HotSpot grid operators faster without changing a
  CertiTherm decision.
- Active gate: implementation and physical-parity gate before any GPU result is
  admitted to the dev or held-out evidence.
- CPU authority: the pinned, patched UVA HotSpot binary remains the independent
  reference and the only direct-replay backend.
- In scope: registered `grid64-avg` and `grid128-avg` operators, fixed package
  parameters, one or more non-fluid power layers, average grid-to-block mapping,
  deterministic FP64 solves, and CPU fallback.
- Out of scope: transient temperature traces, leakage feedback, natural
  convection iteration, microfluidic/non-symmetric systems, and replacement of
  the registered block model.

## Reuse record

| Field | Value |
|---|---|
| Repository | `https://github.com/yuhc/gpu-rodinia.git` |
| Commit | `9c10d3ea16ddba2ba057cc3951a9efc4c2cc18a4` |
| Source path | `cuda/hotspot/hotspot.cu` |
| Owner | University of Virginia / Rodinia contributors |
| License | redistribution and modification permitted with retained notice and disclaimer (`Rodinia/LICENSE`) |
| Reuse mode | pinned Git submodule and algorithmic provenance; CertiTherm supplies a new FP64 batched steady-state solver |
| Semantic delta | Rodinia's single-layer explicit transient stencil is replaced by the exact sparse conductance system exported by pinned HotSpot |
| Release status | upstream archived; CertiTherm does not modify the submodule |

The exporter also pins SuperLU `v5.2.1` at commit
`b86f1388fc9c362ac9bfa4ed3a6d6e02c98b6544` as a build-only submodule. Its
BSD-style license is retained in `SuperLU/License.txt`. SuperLU supplies the
HotSpot sparse-matrix container/assembly dependency; it is built from an
exported clean tree and does not solve or validate the CUDA result.

## First-principles mechanism

For every fixed HotSpot grid model, the steady temperature satisfies

\[
G T = q_0 + Bp, \qquad t_{block}=MT.
\]

HotSpot constructs `G`, the ambient right-hand side `q0`, the block-to-grid
power map `B`, and the grid-to-block average map `M`. The GPU backend exports
those exact objects once, then solves all zero/one-watt right-hand sides in one
batch. A custom FP64 Jacobi-preconditioned conjugate-gradient implementation
uses node-major/right-hand-side-minor storage so each warp reads and writes 32
contiguous right-hand sides while sharing the same sparse row.

The solver is not its own validator. Registered powers and every final witness
are replayed through the separate CPU HotSpot executable.

## Acceptance and kill conditions

The backend is admitted only when all of the following pass on `moe-server`:

1. `compute-sanitizer` memcheck and racecheck report no CUDA error.
2. Every solve reaches its declared true-residual tolerance; NaN, indefinite
   curvature, timeout, unsupported physics, or non-convergence fails closed.
3. For zero, all unit impulses, placed power, bounded uniform power, and frozen
   random powers, `max(abs(T_gpu - T_cpu)) <= 0.01 K` for every registered grid
   model.
4. CPU and GPU produce identical thermal feasibility and ordered DSE outcomes.
5. End-to-end grid-operator construction, including export, transfer, solve,
   mapping, and parsing, is faster than the existing parallel CPU path on the
   same clean commit and machine.

Failure of conditions 1--4 disables the GPU backend. Failure of condition 5
keeps it as a non-paper engineering prototype and leaves CPU as the default.
Held-out inputs may reject the frozen backend but may not loosen its tolerance.

## Baselines and evidence

- CPU HotSpot grid multigrid, current parallel impulse construction.
- Rodinia transient CUDA executable, provenance/performance baseline only.
- Custom batched CUDA PCG, proposed implementation.
- Ablations: FP32 versus FP64, scalar-RHS versus batched RHS, no preconditioner
  versus Jacobi, and kernel-only versus end-to-end time.

Raw logs and binaries remain outside Git. Committed evidence consists of a TSV
manifest, timing table, parity table, environment/digest record, and negative
results.

## Reviewer dissent registered at start

| Severity | Objection | Closing evidence | Status |
|---|---|---|---|
| Critical | The GPU code may solve a simplified Rodinia RC model rather than HotSpot's package system. | Export and digest `G,q0,B,M` from the pinned HotSpot model; no fitted conversion. | OPEN |
| Critical | A small residual may still exceed 0.01 K after an ill-conditioned solve. | Direct CPU replay over impulses and independent development powers. | OPEN |
| Major | Kernel speedup may disappear after model export and host/device transfer. | Same-machine end-to-end wall-clock benchmark with warm and cold runs. | OPEN |
| Major | PCG is invalid for non-symmetric microfluidic systems. | Explicit capability check and fail-closed CPU fallback. | OPEN |
| Major | A GPU backend could compromise fresh-clone reproducibility. | Recursive submodule bootstrap, pinned CUDA build target, clean-clone CI instructions. | OPEN |
