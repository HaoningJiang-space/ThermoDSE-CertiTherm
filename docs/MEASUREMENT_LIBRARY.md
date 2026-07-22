# Registered EDA Measurement Library

Status: unchanged and frozen for `method-freeze-v1` and
`method-freeze-v3.0`.

CertiTherm begins with one workload-level fact: total chip power. Individual
block powers remain free and nonnegative subject to that total and
content-derived per-block capacity bounds. A capacity equals the captured
total budget of that hardware module type; it is an inequality, not a hidden
module-total observation. Every additional action is a linear aggregate over
the same placed-power vector.

| Class | Vector | Normalized cost | EDA interpretation |
|---|---|---:|---|
| module | all instances of one module type | 1 | early module power report |
| chiplet | all units physically assigned to one chiplet | 2 | chiplet aggregate analysis |
| placement-region | all blocks in one placed quadrant | 4 | placed-design regional report |
| post-route | one physical floorplan block | 8 | detailed post-route power analysis |

The implementation derives membership from the provenance-bound floorplan
and architecture cuts, removes duplicate and total-power-complement-equivalent
vectors, and removes the all-block vector because total power is already observed.
A registry artifact records
every action, class, support size, and cost seen by each method.

These costs are a frozen ordinal tool-effort model: later EDA stages and finer
reports cost more. They are not claimed to equal wall-clock seconds, license
fees, silicon area, or sensor energy. All compared methods use exactly this
same registry and cost vector. Consequently, DSOS proves the minimum cost
under this declared library; changing the library or costs defines a new
problem instance and requires a new freeze.

The fixed baseline sorts by registered cost, workload-specific EDYP candidate
rank, and stable action ID, then calls the same decision oracle after every
action. It therefore receives the same sequential early-stop opportunity as
width and dual policies. Width ties use the same candidate rank. Full
refinement means purchasing the entire deduplicated registry, not an
artificially inflated number of repeated channels.
