# Deciding under an incomplete power map — and the separator that is NOT there

> **WITHDRAWN 2026-08-03 in its two headline numbers. See
> `docs/PER_CASE_Q_WITHDRAWS_THE_PLACEMENT_FREE_REFUSAL.md`.** Every number below was computed with
> `Q` scaled from one architecture's audit closure (`0.9997`). Measured per case, `Q/admitted` spans
> `0.3328-0.9997`, and `0.9997` is the **largest** of the six — so every uplift here is overstated.
> Re-run with the per-case ledger: the **2 placement-free refutations become 0**, and the
> **0 disagreements with a guessed guard band become 2** — in the opposite direction to the one this
> document argues. What survives is `12/12` decidability. Do not quote anything else from this file.

RESULT 2026-08-02. NON-CLAIM. `research/triangle/robustness/split_missing_heat.py`, existing
operators and captures, no new solve. **No external review** (Codex quota-locked to 2026-08-08).

## The capability, stated so it can be attacked

This pipeline's thermal trace omits about **half** the dissipated heat, and about **78 %** of that
has no established placement (`docs/THERMODSE_ENDPOINT_AUDIT.md`, `docs/GUARANTEED_RISE_AND_
PLACEMENT_SPREAD.md`). Every method in the field — a guessed guard band, a nominal peak, a
convolutional kernel in a MILP, a multi-fidelity surrogate — **requires a complete power map**.

The decomposition `R_j q = Q*m + sum_i (R_ji - m) q_i` splits the unplaced heat into a term every
admissible placement produces and a term placement decides. So the claim is not "our band is
narrower". It is:

> **a verdict is returned under an incomplete power map, and the verdict states which half of itself
> depends on the missing information.**

## Result over 12 points (3 architectures x 2 workloads x 2 packages)

| | |
| --- | ---: |
| points | 12 |
| **decided without knowing where the missing heat goes** | **12 / 12 = 100 %** |
| of which **placement-free refutations** | **2** |
| designs the NOMINAL method calls SAFE and this refutes under every placement | **2** |

Both placement-free refutations are `arch_b`/transformer, on `standard` and `enhanced`. The nominal
peak reads **SAFE** there; `peak + Q*m = 330.749 K > 330 K` refutes it **without using the placement
spread at all**, so the refusal survives any future answer to where the centre share goes.

**That is a false-SAFE that current practice would ship**, caught by an argument that needs no
placement evidence.

## The separator that is NOT there, reported first because it limits the claim

**On these 12 points a guessed 3 K or 5 K guard band returns the SAME verdict as this method,
12 out of 12.** It flags `arch_b`/transformer as UNSAFE too.

So the "computed band beats a guessed band" separator — which
`~/.claude/plans/fixed-geometry-thermal-scheduling.md` calls the whole paper — **does not exist on
this population**. The guard band is right here, and it is right *by coincidence*: it does not know
the missing heat exists, and its margin happens to cover it on designs whose nominal peak sits
2–3 K under the limit.

**What that means for the claim.** Two things survive and one does not:

* **Survives:** the placement-free refutation, and the 100 % decidability under an incomplete map.
  A guard band cannot produce either — it returns a verdict, not a verdict *plus* a statement of what
  the verdict depends on, and it has no mechanism at all for unplaced heat.
* **Survives:** catching a false-SAFE against the nominal method, 2 of 12.
* **Does not survive:** any claim of better *decisions* than a guessed guard band. Zero
  disagreements. Asserting a quality advantage here would be unsupported.

## What a separator would require, derived rather than hoped for

The guard band and this method agree because on this population the missing heat's **total** is what
binds, and a flat margin covers a total. They must disagree where the **distribution** binds — i.e.
on a design whose nominal peak is comfortably under the limit but whose unplaced heat concentrates
near the hot block, or the reverse. Concretely, a discriminating population needs designs where

    Q * (max_i R_ji - min_i R_ji)   is comparable to the guard band

rather than `Q * min_i R_ji` alone. On the six dev points the spread term is **0.665–2.346 K** and
the guaranteed term **0.860–2.783 K**, so they are the same order and no design isolates them. That
is a selection problem, and it is the same shape as the one `archive-census-v1` hit: a population
chosen without reference to the quantity under test cannot discriminate on it.

## Scope

* `grid512`, block-average rows, nominal map. `default` package produced no rows here — only
  `standard` and `enhanced` operators exist in the sweep directory.
* `Q` is still one architecture's audit closure scaled by total power; a per-case ledger is running.
  The refutation dies if `Q` is **26.9 %** smaller, and the measured case-to-case variation of that
  quantity is **4.2–79.2 %**, so this is the single load-bearing approximation.
