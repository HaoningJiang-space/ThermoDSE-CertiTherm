# Held-out v3 precheck evidence ledger

This ledger records every execution of the one permitted non-thermal v3
precheck. Raw bundles stay outside Git; their manifests and decisions are
bound here. No attempt may contain a temperature, thermal operator, DSOS
query, registry, or observation-contract result.

## Attempt A1 — unresolved, no replacement authorized

- Producer commit: `6b3cf11eecd635df2768e4771c0cc9225a53d963`
- Protocol: `method-freeze-v3.0`, state `DEFINED_UNOPENED`
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
