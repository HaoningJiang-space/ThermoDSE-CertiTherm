# V6.1 claim-grade factorial, schema 3

`v61_manifest.json` is the complete manifest of the second claim-grade run of the 15-subset
`grid64-max` factorial, from a clean tree at commit `74e36a7` on `moe-server` (66.3 min,
`complete=true`, `gate.passed=true`).

**Superseded in turn by `../v61_cg4_schema4/`.** The pipeline now requires schema 4 and refuses
this manifest, so it too is history rather than a renderable input: it records DERIVED tie
scalars (a runner-up and a tie list) instead of the per-block temperature vectors those claims
have to be recomputed from. A producer-reported tie list can name any block, because nothing in
it is tied to a temperature -- which is why schema 4 stores the vectors and derives the ties.
`../v61_claimgrade/` (schema 2) is one step further back and carries neither.

Do not migrate these manifests forward. They were produced under their original contracts, and
rewriting them into schema 4 would manufacture fields that were not recorded at execution time.

Two facts worth reading off it directly:

- Every one of the 15 steady and periodic peaks is bit-identical to the schema-2 run's, at a
  different commit. The binary is byte-identical in both, so this confirms the provenance
  chain, not the physics.
- 11 of the 15 rows have a periodic argmax **tied** with at least one other block, most at
  exactly 0.000e+00 K. The crossing row's `mtxu_16` is tied with `ubuf_16`. One row's reported
  label (`core-nop`) differs from the schema-2 run purely because the argmax tie-break order
  changed, with every temperature unchanged -- which is why the reported hottest-block name
  carries no spatial claim.

Raw HotSpot outputs and traces are NOT archived here; only their SHA-256s inside the manifest.
