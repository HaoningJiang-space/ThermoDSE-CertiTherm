# Held-out v3 development rehearsal ledger

This ledger records method-freeze-v3 rehearsals on the development registry.
They are non-claim runs and cannot open or tune the held-out split. Raw bundles
remain on moe-server; their immutable manifests are bound below.

## R1 — infrastructure pass, endpoint-population failure

- Producer commit: `5370512387d62c0bbfc7c0c1e9b39365dedb8bc7`
- Profile / registry: `dev_v3` / `dev`
- Host / Python: `hpclab03` / `3.8.10`
- Budget: 150 seconds per method; deliberately not a frozen-budget result
- Fresh-clone checks: 147 tests passed; CPU HotSpot smoke and GPU parity passed
- Physical evidence: 9/9 operators, 270 direct replays, maximum residual
  0.00149192487 K against the frozen 0.01 K bound
- Schema evidence: 6/6 query rows and all 45 registered result columns
- Method outcome: 0/6 certified U, 0/6 finite L, 0 false certificates, and
  0 unexpected failures. All query methods ended by the declared timeout.
- Decision: **does not close precondition 3**. The run validates launch,
  deadline, physical, receipt, and serialization paths, but not value-bearing
  Anytime endpoints. Repeat the unchanged method on dev at the protocol's
  actual 1800-second budget; do not alter costs, ordering, thresholds, or the
  held-out registry.

Artifact bindings:

- `SHA256SUMS`: `cbd0c97e03f1fa29bfeee49429eb469c1a6269d71874dbc146d0bda98f476989`
- `results.tsv`: `75b927a2e951179a56ab861105d85e5bddbe69a457560a7be327f0353641d96b`
- `ARTIFACTS.tsv`: `e0c039b14d07feafcbda57a3bde80be7952de8783c0bdb8365a32b028e72c77e`
- Manifest verification: 47/47 files passed `sha256sum -c`
