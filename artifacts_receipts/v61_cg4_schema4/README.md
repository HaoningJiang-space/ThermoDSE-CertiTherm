# V6.1 claim-grade factorial, schema 4 / gate policy 2

`v61_manifest.json` is the complete manifest of the **third** claim-grade run of the 15-subset
`grid64-max` factorial: clean tree at commit `56e77c2`, on `moe-server`, 66.2 min,
`complete=true`, `gate.passed=true`. It is the input from which
`docs/V6_1_CAUSAL_ISOLATION.md` is generated, and the test suite requires that document to
regenerate from it byte for byte.

It supersedes `../v61_cg3_schema3/` and `../v61_claimgrade/`, which are kept as history and are
now refused by the pipeline. Do not migrate them forward.

## What schema 4 changed, and why

It records the **raw observation** — per-block periodic and mean-steady temperature vectors, 233
floats per row — instead of derived tie scalars. Every peak, argmax, runner-up, top gap and tie
set in the document is recomputed from those vectors. The previous schema stored a
producer-reported tie list, and a list can name any block because nothing in it is tied to a
temperature; six trusted row fields disappeared when the vectors arrived.

Gate policy 2 replaced exact argmax equality with `0 <= peak - T[registered_block] <= quantum`,
computed from the registered block's own temperature. Policy 1's check depended on how an exact
tie was broken.

## Three facts worth reading off it directly

- **All 30 temperatures are bit-identical to the schema-3 run's, and so is every reported
  label.** Three independent runs at three different commits now agree. The HotSpot binary is
  byte-identical in all of them, so this confirms the provenance chain, not the physics.
- **11 of the 15 rows have a periodic argmax tied with at least one other block, all at exactly
  `0.000e+00` K.** The crossing row's `mtxu_16` is tied with `ubuf_16`. The reported hottest-block
  name therefore carries no spatial claim — see the correction in
  `docs/V6_PHYSICAL_TRACE_GATE.md`.
- **54 HotSpot invocations, 369.5 MB of outputs, every one hashed** — but the bytes are not
  archived here, so no consumer can reparse them. That is the largest remaining gap after
  instance binding.

Raw HotSpot outputs and traces are NOT in this repository; only their SHA-256s inside the
manifest. Measured cost of retaining them: 353 MB raw, 14.3 MB gzipped, plus 288 MB of
driver-written `.ptrace` inputs.
