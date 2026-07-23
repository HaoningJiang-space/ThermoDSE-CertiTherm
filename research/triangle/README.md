# Primal–dual–integer triangle on one real dev candidate

Non-claim diagnostic. Answers a question the result table cannot: is the tiny
certified lower bound a genuinely weak LP relaxation, a defect in
`_anytime_lower_bound`, or a large integrality gap? Runs on **candidate 0
(`arch_b`) of `resnet50`** — the SAFE/REJECT subproblem every dev query stalls
on (`candidate_at_stop = 0` in D1/D2).

Reconstructs the candidate from cached D2 operators (real HotSpot), runs the
real constraint-generation loop under a wall budget, snapshots the antichain it
actually holds (a wrapper on `_insert_minimal_cut`, no core edit), then compares
three numbers over the **same cuts and costs**.

```bash
# from the repo root on moe-server, against a D2 output dir with cached operators
.venv/bin/python research/triangle/triangle1_triangle.py artifacts/<dev-out> 300
.venv/bin/python research/triangle/triangle2_closure.py  artifacts/<dev-out> 300
.venv/bin/python research/triangle/triangle3_interval.py artifacts/<dev-out>
```

## Findings (300 s, 3442 cuts)

| quantity | value | meaning |
|---|---:|---|
| primal LP | 20.10 | |
| `_anytime_lower_bound` | 20.10 | **equal to LP → bound code is faithful, no bug** |
| restricted-master MILP | 21.00 | **≈ LP → essentially no integrality gap** |
| reported `lower_bound` | 5.00 | 4× below achievable — see refresh cadence below |
| MILP cover feasibility | 638 collisions survive | cheapest cover of discovered cuts is **not** feasible → `C* > 21` |
| full-library separation | collision-free | candidate 0 is **synthesizable**, `C* ≤ 1846` |

`C*(arch_b) ∈ [21, 1846]` — a wide, unclosed interval.

### The bound climbs, but sublinearly and it saturates

LP over random nested subsets of the 3442-cut antichain:

| cuts | 100 | 250 | 500 | 1000 | 2000 | 3000 | 3442 |
|---|---:|---:|---:|---:|---:|---:|---:|
| LP | 5.0 | 12.5 | 13.0 | 14.0 | 14.0 | 14.0 | 20.1 |

Random subsets plateau near 14; only the full set reaches 20.1. Bulk cut volume
does little — the bound is pushed up by **rare high-value cuts**, not quantity.
This is why every throughput optimisation (32× pool fix, GPU, 15-worker) left
the bound where it was: cut *production* was never the limit.

### What this settles

- The three D1 conclusions withdrawn after peer review were right to go: it is
  **not** saturated at 2 (it climbs to 20 at 300 s), **not** a 700× integrality
  gap (MILP ≈ LP), **not** a bound bug (LP = anytime).
- The honest obstacle is **slow, sublinear growth of the LP lower bound** on a
  synthesizable-but-hard candidate, with the cheapest covers far from feasible
  (638 collisions at cost 21). Proving minimality at these budgets is not close:
  the interval is ~88× wide.

### A cheap, real reporting defect

`_anytime_lower_bound` is refreshed only on power-of-two iterations
(`synthesis.py` bound-refresh cadence), so a 300 s run reported 5.0 while the
cuts already in hand justified 20.1. Every reported interval understates its own
lower bound. Fixing the cadence is a one-line win independent of any method
change.

### The only lever that can help

Faster LB growth requires the separation oracle to seek **high-value /
minimal-support cuts** rather than arbitrary feasible collisions (the LP uses a
zero objective, `synthesis.py:598`). That changes a frozen method →
`method-freeze-v4`. MILP closure, faster LP, GPU, and round-robin scheduling are
all ruled out by the numbers above.
