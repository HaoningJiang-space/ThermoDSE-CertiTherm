# GPU collision proposer test plan

Status: **gate failed; excluded from method-freeze-v3.1**. No scientific
verdict originates here. The retained implementation is a reproducible
negative-result prototype, not a claim-path backend.

The CUDA solver is an approximate proposal engine. Every feasible point and
infeasibility ray is independently rechecked by `collision_proof.py`; a failed
or numerically marginal check becomes CPU-HiGHS fallback.

## Correctness matrix

- FP64 CPU HiGHS is the independent status reference.
- Batch tails: 1, 7, 31, 32, 33, 127, 128, 129, and the production-like 541.
- Both feasible and infeasible cells occur in every nontrivial batch.
- Tampered primal points, rays, non-finite values, malformed dimensions, and
  equality/bound contradictions are unit-tested.
- `compute-sanitizer --tool memcheck` must pass the 33-cell partial-warp case.
- Repeat runs must have identical accepted/fallback classifications.

## Performance and admission

After synthetic parity, a real collision corpus is captured from the dev
operators. Admission requires zero incorrect accepted cells, at least 5x
collision-solver throughput over sequential HiGHS, at most 10% fallback, at
least 3x DSOS-round speedup, and peak device memory below 20 GB. Failing any
gate retains the CPU v3.1 scheduler and excludes GPU separation from claims.

The initial kernels use 256 threads. The spec-row reduction has one block per
cell, coalesced variable-major primal reads, and a 256-double (2 KiB) shared
array. Actual registers, resident blocks, occupancy, tail efficiency, and
memory throughput are recorded from ptxas/occupancy/Nsight before changing the
launch or adding asynchronous staging.
