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

## Consequences

1. **No tag, and the reason is no longer about experimental breadth.** The instrument is not
   validated. A DAC reviewer finding this would be right to reject, which is exactly the class of
   objection this project set out to eliminate before submission rather than after.
2. **The frozen `0.01 K` error contract needs a companion, not a replacement.** Linearisation and
   discretisation are different errors and only one was ever budgeted. The gate is the companion;
   whether its bound belongs in the SAFE/REJECT rows the way the linearisation band does is an open
   design question, not a decided one.
3. **The registered family may need finer operators, anisotropic grids, or both.** The convergence
   study's hypothesis — a square grid over a non-square floorplan under-resolves the short axis — is
   consistent with `6x2` drifting 5x more than `4x4`, and the model-id vocabulary (`gridN-avg`, one
   size) cannot express the fix.
4. **Every thermal number in the tree keeps its value and loses its error bar.** Nothing is deleted;
   the documents now say which side of the line each claim falls on.
