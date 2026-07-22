# Query-level parallelism evidence

Status: **infrastructure smoke only; not a scientific result**  
External archive ID: `certitherm-query-pool-smoke-9195e0e`

## What was tested

Commit `9195e0e193eebc60db22f878031fe0badf720e8f` ran the six dev
workload/package queries through one three-process spawn pool. Each worker
executed complete queries; query-internal methods and their signal timers
remained serial. Existing physical captures and operators were reused, so this
run tested scheduling and evidence assembly rather than thermal construction.

The deliberately short query budget was 5 seconds. Every row therefore has
`budget_is_frozen=0` and is excluded from method-freeze-v3 scoring.

## Outcome

- exit status: 0;
- result rows: 6/6;
- registry order preserved: yes;
- recorded workers: 3;
- recorded mode: `persistent-spawn-pool`;
- end-to-end elapsed time: 66.212 seconds;
- `SHA256SUMS` verification: pass;
- repository state after the run: clean.

There is no matched serial timing in this smoke, so it supports no numerical
speedup claim. Its purpose is narrower: the coarse process boundary is
executable, child-process timers work, collection is complete and ordered, and
the normal evidence manifest closes.

## Retained failed attempt

The first invocation produced all six rows and manifests but exited 1 at the
final clean-tree guard. The temporary fresh clone reused `.build` and `.venv`
through symbolic links; directory-only `.gitignore` rules correctly did not
ignore those links. Adding the two links to that clone's local
`.git/info/exclude` made the identical second invocation pass. A normal
`make bootstrap` creates real ignored directories and does not need this test
fixture exception.

Commit `da759c4` subsequently added frozen one-thread numeric-library guards
and receipt fields. Those fields still require verification in the final dev
rehearsal; this earlier smoke cannot evidence code that did not yet exist.
