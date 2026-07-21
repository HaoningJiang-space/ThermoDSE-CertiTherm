# Custom CUDA HotSpot test and launch contract

## Independent references and tolerance

The custom kernel solves the exact sparse system exported by pinned HotSpot,
but correctness is measured against a different executable: the normal
`SUPERLU=0` CPU HotSpot multigrid binary. Comparisons use FP64 throughout and
must satisfy the already frozen end-to-end bound
`max(abs(T_gpu - T_cpu)) <= 0.01 K`. The CUDA solver separately requires the
true residual `norm(b-Gx)_2 <= 1e-12 + 1e-11 norm(b)_2`; a recurrence residual
alone is insufficient.

Required physical inputs are zero power, every one-watt block impulse, placed
power, bounded uniform power, and deterministic bounded-random powers. Required
grid shapes are 64x64 and 128x128. Synthetic sparse fixtures additionally cover
1, 7, 13, 31, 32, 33, 127, 128, 129, and 1009 nodes with 1, 7, 31, 32, 33,
and 181 right-hand sides. Invalid CSC pointers, missing diagonals,
non-symmetric coefficients, non-positive curvature, NaN/Inf, truncated files,
and iteration exhaustion must fail visibly without output admission.

## CUDA layout and access audit

The dense batch layout is `value[node][rhs]`, with `rhs` contiguous. A 32-lane
warp owns one sparse row and 32 right-hand sides:

| Access | Warp pattern | Result |
|---|---|---|
| CSR row pointer | broadcast | one cached value per row boundary |
| CSR column/value | broadcast | all lanes reuse the same sparse coefficient |
| search vector | stride 1 across RHS | coalesced 256-byte FP64 footprint |
| output vector | stride 1 across RHS | coalesced |
| reduction vectors | stride 1 across RHS | coalesced |

No `double2` vector load is used because `nrhs = nblocks + 1` is not guaranteed
even, so successive node rows are not guaranteed 16-byte aligned. Scalar FP64
loads preserve coalescing without an unsafe alignment assumption.

The first reduction kernel uses `double partial[8][32]`. Warp `w`, lane `l` writes
element `32w+l`; for each 32-bit bank half, lanes map one-to-one to banks.
Warp 0 then reads `partial[w][l]`, again one address per lane/bank. No padding
or `cp.async` is justified: sparse indirection has no reusable rectangular
global tile, and the only shared data are 2 KiB reduction partials.
Each row block writes a distinct coalesced partial vector. A second kernel sums
those vectors in ascending row-block order, so dot products are reproducible;
no scheduling-dependent floating-point atomic reduction is admitted.

## Launch contract

- block: `(32, 8, 1)` = 256 threads;
- grid Y: `ceil(nrhs/32)`, with tail lanes guarded;
- grid X: `min(ceil(nodes/8), 4 * SM_count)` for the system and the analogous
  mapped-output row count;
- dynamic shared memory: zero;
- static shared memory: 2048 bytes only in the dot kernel;
- no cooperative launch or cross-block synchronization;
- `threadIdx.x` always indexes the stride-one RHS dimension.

The A800 SM80 build uses at most 32 registers/thread in the SpMM/update path;
the reduction uses 22 registers/thread and 2 KiB static shared memory. `ptxas
-v` reports no spills. With the SM80 65536-register file, 2048-thread limit,
and 32-block limit, every candidate launch below reaches the architectural
thread limit; neither registers nor shared memory lower occupancy.

| Threads/block | Register-limited blocks | Shared-memory-limited blocks | Thread-limited blocks | Occupancy |
|---:|---:|---:|---:|---:|
| 64 | 32 | >=32 | 32 | 100% |
| 128 | 16 | >=16 | 16 | 100% |
| 256 | 8 | >=8 | 8 | 100% |
| 512 | 4 | >=4 | 4 | 100% |

The selected 256-thread block amortizes one sparse row across a full RHS warp
while permitting eight resident blocks at the measured register bound. For
181 RHS, the last RHS tile has 21 active lanes (65.6% utilization in that tile,
94.3% over all six tiles). Grid X uses persistent row strides, so arbitrary
node counts and partial final row groups are covered.

## Remote-only commands

```bash
make gpu-bootstrap
make gpu-parity

compute-sanitizer --tool memcheck --error-exitcode=99 \
  .build/hotspot-cuda/certitherm_hotspot_cuda \
  SYSTEM.bin OUTPUT.bin STATS.tsv 0 1e-11 1e-12 10000

compute-sanitizer --tool racecheck --error-exitcode=99 \
  .build/hotspot-cuda/certitherm_hotspot_cuda \
  SYSTEM.bin OUTPUT.bin STATS.tsv 0 1e-11 1e-12 10000
```

All timing uses CUDA events for device work and synchronized wall time for the
complete export-transfer-solve-map-output path. The primary performance metric
is end-to-end operator-build speedup over the existing parallel CPU HotSpot
impulse path. Kernel time, effective sparse bytes/s, iterations, register use,
occupancy, L2 hit rate, and DRAM throughput are diagnostic metrics only.

Known initial exclusions are non-average grid mapping, natural-convection
iteration, leakage feedback, microfluidic/non-symmetric matrices, and GPUs
older than FP64 atomic-add support. Each exclusion routes to CPU HotSpot or
`UNRESOLVED`; it is not silently approximated.
