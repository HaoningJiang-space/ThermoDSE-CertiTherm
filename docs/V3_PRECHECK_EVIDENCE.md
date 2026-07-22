# Held-out v3 precheck evidence ledger

This ledger records every execution of the one permitted non-thermal v3
precheck. Raw bundles stay outside Git; their manifests and decisions are
bound here. No attempt may contain a temperature, thermal operator, DSOS
query, registry, or observation-contract result.

## Attempt A1 — unresolved, no replacement authorized

- Producer commit: `6b3cf11eecd635df2768e4771c0cc9225a53d963`
- Protocol at execution: `method-freeze-v3.0`, state `DEFINED_UNOPENED`.
  The physical split and this non-thermal evidence carry unchanged into v3.1;
  v3.0 was superseded before held-out opening only by the method scheduler.
- Host / Python: `hpclab03` / `3.8.10`
- Time: `2026-07-22T05:18:50Z`–`2026-07-22T05:18:51Z`
- Outcome: `UNRESOLVED`; 6/12 combinations completed, 0 invalid metrics,
  6 execution failures
- Common failure: the pinned `alex_net` and `lstm_gnmt` definitions call
  `Network.add(..., prevs=...)`, while the pinned implementation accepts the
  renamed `ifm_prevs` keyword. This is an upstream API-drift defect, not an
  architecture-feasibility result.
- Thermal guard: `hotspot_invocations=0`; the bundle contains no `.steady`,
  `.ptrace`, `.flp`, or `.npz` file.
- Raw `SHA256SUMS` digest:
  `638dcb9047d3b027f8ac84402446db9b241fcd65a70065a34886c086a53f0b2c`
- Execution-log digest:
  `454691693168edd0b52b77024c6102aaca4abb057906b15524f33f1ba7aebc75`

Decision: preserve the primary architecture set unchanged. Repair only the
documented keyword compatibility layer, commit it, rerun the identical check,
and retain A1 permanently as an unresolved attempt.

## Attempt A2 — unresolved, no replacement authorized

- Producer commit: `7728f0208858dd9bb0db958300def9efecac7c84`
- Outcome: `UNRESOLVED`; 9/12 combinations completed, 0 invalid metrics,
  3 execution failures
- A1 resolution: AlexNet completed for all three primary architectures.
- Remaining failure: all three GNMT evaluations reached the pinned
  `Network.traverese_layer` and stopped at its progress assertion. Diagnosis
  showed that this traversal seeds its satisfied set with only `__INPUT__`,
  even though the same class explicitly registers LSTM hidden/cell state as
  external input layers. Consequently no first recurrent layer is eligible.
- Thermal guard: `hotspot_invocations=0`; the bundle contains no `.steady`,
  `.ptrace`, `.flp`, or `.npz` file.
- Raw `SHA256SUMS` digest:
  `1bc21b4fb867d62afac928e9f7d6405d9222ed53544f0d1d29c9e4d48940754a`
- Execution-log digest:
  `04e9aedb524c7c793dc2fb655a3e0828dd8a6ea028790a704c1c44047c04a84a`

Decision: again preserve the primary set. Correct the traversal to seed every
registered external input, add a recurrent-network completeness regression,
commit, and rerun the identical check. This changes neither the workload nor
any observed metric.

## Attempt A3 — pass, primary set accepted

- Producer commit: `4f0b66112c49f3110c57def3aaa40cae04b19290`
- Host / Python: `hpclab03` / `3.8.10`
- Time: `2026-07-22T05:24:21Z`–`2026-07-22T05:24:23Z`
- Outcome: `PASS`; 12/12 combinations completed, 0 invalid metrics,
  0 failures
- Thermal guard: `hotspot_invocations=0`; the bundle contains no `.steady`,
  `.ptrace`, `.flp`, or `.npz` file.
- Raw `SHA256SUMS` digest:
  `b16599e89d21ad245fb8c995d96a4802b98e01e7bf4d06d2a3b95b2c23c3f799`
- Execution-log digest:
  `e60663a25e6e2b12a823fa90c28e5fb4c10049f84593dc719e073cc2784b18c2`

The permitted EDYP check fixed the following workload-specific orders:

| Workload | Ascending EDYP order | Minimum adjacent gap |
|---|---|---:|
| AlexNet | `arch_k`, `arch_j`, `arch_l` | 5.486% |
| GNMT-LSTM | `arch_k`, `arch_j`, `arch_l` | 14.017% |
| MLP-L | `arch_k`, `arch_j`, `arch_l` | 1.730% |
| VGG-16 | `arch_k`, `arch_j`, `arch_l` | 19.318% |

Decision: accept `(arch_j, arch_k, arch_l)` unchanged; the fallback set is not
activated. Subsequent DSE queries must consume the per-workload EDYP rank from
the capture stage, not registry or architecture-ID order. v3 remains unopened
until its dev-only value rehearsal and final artifact audit pass.
