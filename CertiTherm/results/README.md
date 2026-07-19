# Result Artifact Disposition

All result files committed before the 2026-07-19 integrity correction are
retained for forensic comparison. They are classified
`LEGACY_INVALIDATED_FOR_CLAIMS` and must not be quoted as paper evidence.

## Why they are invalid for claims

- The legacy spatial injector assumed six chip-major component columns, while
  ThermoDSE emits nine component types in type-major order.
- Synthetic multipliers changed component-total power, so temperature deltas
  mixed spatial redistribution with extra injected energy.
- A process-global backup ptrace could be reused across different designs.
- Some failed HotSpot runs were skipped or converted into an infeasible/feasible
  boolean instead of an explicit unresolved state.
- Files lack a content-bound run manifest, exact source commit, dependency
  versions, complete command, raw-input digests, and replay receipt.
- Several files contain failed rows, duplicated designs, null temperatures, or
  values inconsistent with other runs of the same design.

## File groups

| Files | Disposition | Permitted use |
| --- | --- | --- |
| `decision_flip_*.csv` | legacy invalidated | debug historical control flow only |
| `robust_dse_*.json` | legacy invalidated | debug historical sampling only |
| `robust_dse_eval_clean.json` | empty | none |
| `../theory/R_matrix_*` | incomplete pilot | inspect a partial operator only; no full-system bound |

## Requirements for new results

Write new raw outputs outside the Git worktree. A compact committed manifest
must bind source commit, config and input SHA-256 digests, DNN/architecture/
package identities, observation semantics, conservation checks, seeds, thermal
backend, command, exit status, sample completeness, wall time, peak RSS, and
output digest. Any missing simulation or proof is `UNRESOLVED`, never safe.

Use `T_sample_max` for finite synthetic sampling. Reserve `upper bound`,
`certificate`, and `robustly safe` for results with a replayable universal
argument over the registered admissible set.
