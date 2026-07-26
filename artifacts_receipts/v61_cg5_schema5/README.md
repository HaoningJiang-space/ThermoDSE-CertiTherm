# V6.1 claim-grade factorial, schema 5 / gate policy 3

`v61_manifest.json` is the manifest of the **fourth** claim-grade run of the 15-subset
`grid64-max` factorial: clean tree at commit `fd9d93b`, on `moe-server`, 67.1 min,
`complete=true`, `gate.passed=true`. It is the input `docs/V6_1_CAUSAL_ISOLATION.md` is generated
from, and the suite requires that document to regenerate from it byte for byte.

Supersedes `../v61_cg4_schema4/`, `../v61_cg3_schema3/` and `../v61_claimgrade/`, all of which
the pipeline now refuses. Do not migrate them forward: they were produced under their original
contracts, and rewriting them would manufacture fields that were not recorded at execution time.

## What this run closed

**The physical instance is bound (gate policy 3).** Every earlier run's gate bound names and
temperatures only, so a changed registry, power trace, floorplan or routing under the same
workload/architecture names would have passed. This run was gated on the canonical staged input
hashes, the binary, the 233-block floorplan registry hash, all fifteen per-subset power-trace
hashes and the source energy decomposition.

Those canonical hashes were canonicalised **from** the schema-4 run, **not preregistered ahead of
it** — the originally registered run predates this pipeline and no hash of its inputs survives.
The binding therefore guarantees that this run replayed the same instance as the run the evidence
rests on. It does not establish that either replayed the instance behind the original registered
numbers; that link is unrecoverable.

**The raw outputs are retained (schema 5).** Hashes without bytes cannot be reparsed by anyone.
One bundle, 54 files, **11.2 MB gzipped from 369.5 MB**, `sha256 bfc1b62281094bad…`, at
`artifacts/v61_cg5_grid64/v61_hotspot_outputs.tar.gz` on the run host. Deliberately not
committed: 369.5 MB of ttrace text against a 1.1 MB repository pack. `/data` on that host is
shared and periodically cleaned, so the hash identifies the bytes without guaranteeing they
still exist.

## Cross-run agreement

Compared against the schema-4 run at the level of the **full 233-block temperature vectors**, not
just the peaks: **0 of 15 rows differ.** Four runs at four commits now agree. The HotSpot binary
is byte-identical in all of them, so this confirms the provenance chain and the reproducible
build, not the physics.

## What is still open

- **No independent thermal model.** This bounds the evidence to HotSpot-conditional decision
  preservation, which is what DSOS asks about. It is a gap only for a claim of physical accuracy;
  see `docs/V6_PHYSICAL_TRACE_GATE.md`, where model choice alone moves the periodic peak by
  >= 0.69 K and flips a decision with 33.01% EDYP regret, against this crossing's +0.19 K margin.
- **11 of 15 rows have an exactly tied periodic argmax.** The leading explanation -- blocks
  sharing the hottest grid cell under `max` mapping -- is UNTESTED, and is testable inside
  HotSpot.
- `grid128-max` has not been run as a factorial; one workload and one candidate cannot support a
  general source-importance claim.
