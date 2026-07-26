# V6.1 claim-grade factorial, schema 3

`v61_manifest.json` is the complete manifest of the second claim-grade run of the 15-subset
`grid64-max` factorial, from a clean tree at commit `74e36a7` on `moe-server` (66.3 min,
`complete=true`, `gate.passed=true`).

It supersedes `../v61_claimgrade/` (schema 2) as the input to
`research/triangle/v61_render_evidence.py`, which now refuses any schema below 3. The schema-2
manifest is kept as a historical artefact, not as a renderable input: it carries neither
execution receipts nor argmax tie evidence.

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
