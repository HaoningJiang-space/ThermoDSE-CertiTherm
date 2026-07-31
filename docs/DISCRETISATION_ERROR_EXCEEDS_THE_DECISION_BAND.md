# The certified family's discretisation error is larger than the band it decides in

RESULT 2026-08-01, `method-freeze-radii-v2`. This supersedes the ordering-claim refutation as the
principal finding of the round: that one said a claim did not generalise, this one says the
instrument every thermal number in this project was measured with has an error that was never
bounded, and that the error is **larger than the SAFE/REJECT band itself**.

## The measurement

The grid-convergence gate (`CertiTherm/grid_convergence_gate.py`, wired into `_operator`) replays
each calibration vector at `gridN` and at `grid2N` and bounds the per-block disagreement. Run on four
architectures, one workload, five calibration vectors each:

| architecture | linearisation error | drift vs 2x refinement | gate |
| --- | --- | --- | --- |
| `6x2` cut 1x1 | 0.00066 K | `grid64` **1.409 K**, `grid128` **0.759 K** | REJECT |
| `6x2` cut 2x2 | 0.00067 K | up to **0.608 K** | REJECT |
| **`4x4` cut 1x1** | 0.00042 K | up to **0.250 K** | REJECT |
| **`4x4` cut 2x2** | 0.00035 K | up to **0.153 K** | REJECT |

**All four refused — including both `4x4` controls, which are the compact, near-square development
geometry that every number in this project was computed on.** Zero operators survived.

Set against the registered constants:

| quantity | value |
| --- | --- |
| frozen linearisation budget, folded into every SAFE/REJECT row | **0.01 K** |
| SAFE/REJECT indifference band, `2 x margin` | **0.10 K** |
| measured discretisation drift | **0.153 – 1.409 K** |
| ratio to the linearisation budget | **15x – 141x** |
| ratio to the whole decision band | **1.5x – 14x** |

The linearisation error is 0.0004–0.0017 K throughout — the contract is doing precisely what it
claims, to three spare orders of magnitude. It is bounding the wrong error.

## Why the contract could never have caught it

```python
direct    = replay_power(..., model_id, ..., power)          # same model_id
predicted = ambient[m] + response[m] @ power                 # that model's own impulse responses
error     = max|direct - predicted|                          # PASS if <= 0.01 K
```

Both sides share the grid. The comparison tests whether the operator is a faithful **linearisation**
of HotSpot at that resolution, and it is — superbly. It says nothing about whether that resolution
resolves the physics, and nothing anywhere else in the pipeline did either.

## What this does and does not invalidate

The project's claims separate cleanly, because half of them never touch the thermal operator.

**Unaffected** — computed from latency, energy, die geometry and cost, with no thermal operator
anywhere:

* the refinement-monotonicity proposition and its proof;
* the composition comparison — the all-dies-good product prefers `n = 1` in 8 of 8 held-out groups,
  the transcribed recurring cost in 8 of 8;
* no cut owns the joint cost-parameter box in any group;
* the `n=1`/`n=2` crossover lying outside `(0, 1]`;
* the transcription's term-by-term conformance against the upstream program.

**Now carrying an unbounded error** — anything computed from the thermal operator:

* every relocation and deviation radius, `beta*_safe`, `beta*_reject`, `epsilon*`, `tau*`;
* the instrumentation bracket and every tier verdict;
* the certified observation bounds, including the withdrawn 1312 and 1440;
* the held-out P5 result, which pairs a cost choice against a `beta*` choice.

Those numbers are not shown to be wrong. Their uncertainty is shown to be **unquantified, and larger
than the band the decision is made in**. A 0.25 K resolution uncertainty on a design whose margin to
the reject floor is a fraction of a kelvin is not a rounding detail; it is the same size as the
quantity being decided.

## What is NOT established

* **`grid256` is not validated either.** There is no `grid512` here, so "drift" is disagreement
  between two successive refinements. That bounds the convergence error from below; the true error
  could be larger. It cannot be smaller in the sense that matters: two resolutions of the same
  physics disagreed by 0.15–1.41 K, so at least one of them is wrong by at least that much.
* **Four architectures, one workload, five vectors.** Enough to refuse, not enough to characterise.
* **`block` is ungated.** It has no refinement parameter, so nothing here measures it — and it was
  already the outlier in one of the four convergence groups.
* **The bound `GRID_DRIFT_LIMIT_K = 0.05` is a first registration, not a calibration.** It was set to
  half the decision band before any drift was measured. That it refuses everything is a fact about
  the operators, not evidence the bound is right; a defensible bound needs an argument from the
  decision it protects, which is the next round's first task.

## The repair: charge the error, do not refuse the operator

Refusing was the first design and it rejected everything, which is fail-closed and useless — no
certificate at all, and it treats a large error as the defect when the defect is an **unbudgeted**
one. `thermal_constraints` already subtracts `error_k` from both the SAFE and the REJECT right-hand
sides, so folding the drift in makes SAFE harder to reach and REJECT easier, fail-closed on both, and
yields a sound weaker certificate. `CertiTherm/grid_convergence_gate.py:budgeted_error_k`:

    error_k = MODEL_ERROR_LIMIT_K + GRID_DRIFT_SAFETY_FACTOR * drift,   factor = 2.0

`drift = |T_N − T_2N|` is not the operator's error: `|T_N − T_inf| <= drift + |T_2N − T_inf|`, and the
second term is unmeasured without a `4N`. Assuming at least first-order convergence bounds it by the
first, which is where the factor of two comes from. **It is an assumption**, registered as a named
constant rather than multiplied in silently.

### The first attempt was routed around, and the number said so

Charging only the two grid operators left the headline unchanged, because `block` — no refinement
parameter, therefore ungated, therefore still carrying 0.01 K — is the model that **binds** the
family minimum:

| model | `error_k` | its own `beta*` |
| --- | --- | --- |
| `block` | 0.01 K | **3.757 %** ← sets the family minimum |
| `grid64-avg` | 2.829 K | 6.448 % |
| `grid128-avg` | 1.528 K | 5.796 % |

Reporting "the radii survive budgeting" at that point would have been true and meaningless. `block`
and `gridN-avg` are two discretisations of the same physics that both emit per-block temperatures, so
`block` is now gated against the refinement of the finest grid at no extra cost. Its charge rests on
a weaker argument than the grid ones — `block -> grid256-avg` is not a *refinement* of `block`, so the
Richardson factor does not apply and the drift is a plain lower bound on the disagreement.

### What survives, with every operator charged

All four architectures certify. `resnet50`:

| design | `tau*` unbudgeted -> budgeted | `beta*` unbudgeted -> budgeted | retained |
| --- | --- | --- | --- |
| `6x2` n=1 | 149.3 % -> **31.2 %** | 3.76 % -> **1.46 %** | 21 % / 39 % |
| `6x2` n=4 | 166.9 % -> **35.8 %** | 7.05 % -> **2.77 %** | 21 % / 39 % |
| `4x4` n=1 | 156.1 % -> **105.7 %** | 3.77 % -> **2.81 %** | 68 % / 75 % |
| `4x4` n=4 | 172.5 % -> **118.6 %** | 4.17 % -> **3.14 %** | 69 % / 75 % |

**Every radius previously reported by this project was overstated** — by about 1.3x on the compact
development geometry and up to 4.8x on the elongated geometry the held-out split introduced. The
retention tracks how badly each operator was resolved, which is the sanity check that the budget is
doing what it should rather than subtracting a constant.

A 31 % total-power under-prediction and a 1.46 % relocation budget are still real margins. The
method produces sound certificates with both known error sources priced; it produces smaller numbers.

**This is not a revival of the ordering claim.** Both grids happen to come out monotone under the
full budget (`6x2`: 1.46 < 2.77; `4x4`: 2.81 < 3.14), but that is four architectures, one workload,
two cuts, on a burned split. It is an observation, and the preregistered kill condition stands.

## Consequences

1. **No tag.** The instrument now has a budgeted error where it had an unmeasured one, which is a
   repair rather than a result — and its immediate consequence is that every thermal number already
   in the tree is overstated by 1.3x to 4.8x and has not yet been recomputed.
2. **The frozen `0.01 K` error contract has a companion now.** Linearisation and discretisation are
   different errors and only one was ever budgeted; both are. Whether the drift term belongs in the
   SAFE/REJECT rows exactly as the linearisation band does, or deserves a different treatment, is
   answered pragmatically here and not settled in principle.
3. **The registered family may need finer operators, anisotropic grids, or both.** The convergence
   study's hypothesis — a square grid over a non-square floorplan under-resolves the short axis — is
   consistent with `6x2` drifting 5x more than `4x4`, and the model-id vocabulary (`gridN-avg`, one
   size) cannot express the fix.
4. **Every thermal number in the tree keeps its value and loses its error bar.** Nothing is deleted;
   the documents now say which side of the line each claim falls on.
