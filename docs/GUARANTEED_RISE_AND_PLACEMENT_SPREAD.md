# The missing heat, split into what every placement causes and what placement decides

RESULT 2026-08-02. NON-CLAIM. `research/triangle/robustness/split_missing_heat.py`, operators and
captures already committed, no new solve. **No external review** — Codex is quota-locked until
2026-08-08; reviewed by a `claude -p` instance only.

## The correction this starts from

`docs/NUISANCE_BOUND_IS_NOT_AN_ESCAPE.md` placed **all** the missing heat on `eblk0..3` and concluded
the `arch_b -> arch_c` headline was strengthened. **Withdrawn.** `gen_cover_flp`
(`gen_floorplan.py:202-209`) emits **five** blocks: `_e0..e3` are the frame and `name` is a central
block of `(sys_width, sys_height)` covering the compute die. Measured from the committed floorplans,
the frame is only **19.2–24.9 %** of the cover area — so that placement put a minority of the heat on
the coolest blocks and none where three quarters of it belongs.

## The decomposition, and why it is two-sided

`R`'s rows are Green's functions: a source acts through a nearly uniform **far** field — that is what
the spreader does — plus a **near** field significant only for sources close to the observation
point. Writing `m = min_{i in S} R_ji` over the admissible support `S`,

```
R_j q  =  Q * m  +  sum_i (R_ji - m) q_i
```

* **`Q * m` is produced by every admissible placement**, because the heat is conserved and must land
  somewhere in `S`. It is not an error term — it is a known, unavoidable rise.
* **Only the second term is placement uncertainty**, and its width is the row's **spread** over `S`,
  not the row's maximum. The lumped adversarial bound charges the certificate for heat it knows
  about; this does not.

And because `Q*m` is a **guarantee rather than a bound**, the same decomposition **refutes**: if
`peak + Q*m > limit`, the design is infeasible **under every placement**, with no placement evidence
required at all.

## The declared set has to say what the source is

A first run allowed `q_i` up to the whole centre share, i.e. a plane of DRAM collapsing onto one
1 mm block. That gave spreads of **27–150 K** and resolved nothing. It is not a conservative reading
of an unknown placement — it is a **different physical object**. DRAM is a memory plane and NoP is
interconnect; both are distributed sources with bounded areal density, so the box is

```
q_i <= Q * area_i / area(S),      sum_i q_i = Q
```

which states "the heat is spread over the die, we just do not know how evenly" and still contains
every admissible spreading. The spread collapses to **0.665–2.346 K**.

## Result

| case | peak (frame share placed) | guaranteed | spread | upper | slack | |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `arch_a`/resnet50 | 321.545 | 0.966 | 0.814 | 323.325 | +6.675 | CERTIFIED |
| `arch_a`/transformer | 324.255 | 1.958 | 1.650 | 327.863 | +2.137 | CERTIFIED |
| `arch_b`/resnet50 | 323.932 | 1.390 | 1.335 | 326.657 | +3.343 | CERTIFIED |
| **`arch_b`/transformer** | 327.966 | **2.783** | 2.346 | 333.096 | **−3.096** | **REFUTED under EVERY placement** |
| `arch_c`/resnet50 | 321.413 | 0.860 | 0.665 | 322.937 | +7.063 | CERTIFIED |
| **`arch_c`/transformer** | 324.258 | 1.669 | 1.327 | 327.254 | **+2.746** | CERTIFIED |

**The `arch_b -> arch_c` headline holds on transformer, and in its strongest form yet.**

* `arch_b` is refused by `peak + guaranteed = 330.749 > 330` — **the refutation uses only the
  placement-free term**, so it survives any answer to the open question of where the centre share
  goes.
* `arch_c` certifies with **+2.746 K**, which exceeds the measured cross-solver band
  (0.2997–1.4332 K, `docs/PACKAGE_SWEEP_RESULT.md`). The preregistered kill condition — margin below
  the band — **does not fire**.

On resnet50 both architectures certify, so there is no decision to preserve there; that is consistent
with resnet50 never having been near the limit.

## Scope

* `standard` package, `grid512`, block-average rows. Not the cell endpoint, which would move both
  columns in the refusing direction.
* The frame share is **established** (`gen_floorplan.py:325,327` calls `gen_cover_flp` with identical
  arguments for `interposer.flp` and `dram.flp`). The centre share is **bounded, not placed** — this
  document does not decide where it goes, and does not need to for the refutation.
* `Q` comes from one architecture's audit closure scaled by total power. A per-architecture ledger
  would replace that; it is the largest remaining approximation here.
* The NoC over-count (+33.41 %) and its uniform spreading are untouched.
