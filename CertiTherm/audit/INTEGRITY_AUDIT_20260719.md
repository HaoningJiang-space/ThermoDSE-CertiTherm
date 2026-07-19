# CertiTherm Claim Integrity Audit — 2026-07-19

Mode: full claim and numeric audit. No new experiment was run for this audit.

## Disposition

The existing Phase 1/2 outputs are useful pilot/debug artifacts but cannot
support a paper claim. The headline `17% flip`, `up to 51 K`, `robust by
construction`, `PAC bound`, and `0% flip` claims are withdrawn pending rerun
under the corrected observation-preserving implementation.

## Claim–evidence findings

| Claim | Finding | Severity | Evidence in repository | Safe disposition |
| --- | --- | --- | --- | --- |
| Synthetic patterns emulate real SAIF/placed power | Unsupported; no real activity or placed instance-power binding exists | Critical | injector docstrings and README vs. synthetic multipliers | Call them synthetic stress patterns |
| Spatial perturbations preserve total power | False in legacy implementation | Critical | legacy code multiplied selected columns without normalization | Rerun with per-component conservation |
| Each chip receives one multiplier across six block types | False schema interpretation | Critical | ThermoDSE generates nine types in type-major order | Parse identities, not positions |
| Centered-5x causes a `2/12 = 17%` flip rate | Denominator includes failed/incomplete rows; generator is invalidated | Critical | `decision_flip_centered5_final.csv` has failed and partial rows | Do not report a rate |
| Maximum delta is `+51 K` under spatial redistribution | Confounded by changed total power and possible state contamination | Critical | same CSV plus legacy injector | Do not report as physical evidence |
| `max(K samples)` is a worst-case/PAC bound | No valid theorem or coverage model is supplied | Critical | former `sample_worst_case.py` module text | Call it a sampled maximum only |
| Failed thermal evaluation is fail-safe | False; the constraint returned `0.0`, which means feasible | Critical | former `robust_target.py` constraint path | Raise/return unresolved; fixed in code |
| K-sample method yields 0% flip | Unsupported and circular without an independent population/oracle | Critical | INSIGHTS and finite legacy samples | Remove claim |
| Reported temperatures are reproducible | Contradicted by files for identical `sys_info` | High | e.g. min design appears near 325 K and 339 K | Require clean content-bound rerun |
| Eight-design K15 run is complete | False; duplicated cases and null cases exist | High | `robust_dse_K15.json` | Treat as incomplete |
| Partial `R` matrix supports full thermal bound | Unsupported; only twelve selected blocks are perturbed | High | `R_matrix_meta.json` and `derive_R.py` | Call it an incomplete operator pilot |
| Repository is portable | False | High | hard-coded machine paths and broken absolute HotSpot symlink | Replace with explicit dependency setup |

## Numeric consistency examples

- The minimum design reports roughly `325.19 K` in the centered-5x audit but
  `339.3 K` in K-sample JSON files.
- The `[4,5,2,1,...]` design reports `327.1 K` in the uniform audit and
  `332.25 K` in later decision-flip files.
- `robust_dse_K15.json` repeats the minimum and 3x3 designs, while two other
  entries have null temperatures.
- `robust_dse_eval_clean.json` is empty.

No causal explanation is inferred from these inconsistencies; the safe action
is a clean rerun after fixing state isolation and input binding.

## Corrective actions completed

- Parse the real ThermoDSE nine-component, type-major ptrace schema by identity.
- Preserve each obtainable component-total power observation by default.
- Use a local deterministic RNG and invocation-local backup state.
- Require every registered sample and successful HotSpot status.
- Restore the source ptrace in a `finally` path.
- Make thermal failure unresolved instead of feasible.
- Add remote unit tests for mapping, conservation, deterministic replay,
  malformed schema rejection, failure handling, and restoration.

These actions validate corrected mechanics only. Legacy numbers remain invalid.

## Remaining blockers

1. Real SAIF/VCD and placed instance-power provenance are absent.
2. ThermoDSE and HotSpot dependency revisions are not pinned in this repository.
3. No independent thermal backend has replayed a physical certificate/witness.
4. The exact G1 oracle is not yet migrated into this repository.
5. No claim-grade run manifest schema exists here yet.
6. No current related-work refresh has been performed for the final paper claim.

Next CCFA owner: experiment design for the G2 physical evidence matrix, followed
by another integrity audit. No-invention status: PASS.
