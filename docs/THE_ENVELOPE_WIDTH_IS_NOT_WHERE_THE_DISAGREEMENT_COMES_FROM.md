# A3: the disagreement exists at every envelope width, and its size is monotone in the width

RESULT 2026-08-04. NON-CLAIM. `research/triangle/robustness/envelope_span_sweep.py` over the
`arch_b`/transformer neighbourhood, 12 candidates, 7 envelope widths. **No external review** — Codex
quota-locked to 2026-08-08.

## The attack

`ADVERSARIAL_SELF_REVIEW.md` A3: the envelope half-width `0.30` is a knob, and the disagreement
between the nominal rule and the envelope rule could have been tuned into existence by picking it.

## The sweep

`F_nominal` = `{ nominal peak ≤ 330.0 }`, `F_envelope(s)` = `{ sup over P(s) ≤ 329.94 }`, over the
same 12 candidates. The nominal rule does not see the span at all, which is the point.

| span | `\|F_nominal\|` | `\|F_envelope\|` | nominal optimum EDYP | envelope optimum EDYP |
| ---: | ---: | ---: | ---: | ---: |
| 0.05 | 10 | **9** | 13.8628 | 14.0852 |
| 0.10 | 10 | 6 | 13.8628 | 14.4065 |
| 0.20 | 10 | 4 | 13.8628 | 14.7043 |
| **0.30** | 10 | **3** | 13.8628 | **15.0792** |
| 0.50 | 10 | 1 | 13.8628 | 15.8211 |
| 0.75 | 10 | **0** | 13.8628 | **none** |
| 1.00 | 10 | 0 | 13.8628 | none |

**The two rules disagree at every span measured, including the narrowest.** At `s = 0.05` — a ±5 %
per-block activity variation, about as small a declaration as is meaningful — the incumbent's own
optimum is already refuted: its supremum reads **330.213** against a **329.94** ceiling. So the
disagreement is not produced by the span; the span only sets how many designs it catches.

**And the price is monotone and readable off the table.** The envelope optimum's EDYP rises
`14.0852 → 15.8211` as the declaration widens from ±5 % to ±50 %, i.e. **`+1.6 %` to `+14.1 %`** over
the nominal optimum. A reader who declares a different envelope reads their own price off this curve
rather than taking ours.

## What the sweep also shows against the method

**At `s ≥ 0.75` nothing certifies.** A ±75 % envelope makes the entire neighbourhood infeasible, so
the envelope is a real declaration with consequences and not a free strengthening. Reporting the span
at which the feasible set empties is part of the honest statement: a certificate that refuses
everything is useless, and this one does that at 0.75 here.

**The nominal column is constant at 10 by construction.** It is included because that constancy *is*
the finding — a rule evaluated at one power map cannot respond to a statement about a set of them,
and no amount of tuning its limit changes that.

## What this run also demonstrates about leg 2

**Operator library hit rate: 12 / 12 = 100 %.** Every design had been evaluated once by the search, so
the sweep rebuilt no operator at all and the whole 7-width sweep over 12 designs cost the ThermoDSE
evaluations plus 84 certificates at 12 ms each. This is the case the content-addressed library exists
for, and it is the first run in this project where its hit rate is high — the within-search rate is
~0 because **zero of the ten design fields is geometry-invariant**
(`THREE_LEGS_STATUS.md`).

The one cost this exposed is our own: the search stored peaks rather than power maps, so the sweep had
to re-run ThermoDSE once per design to recover the vector. **A future run stores the power vector**;
this one records the omission rather than hiding it.

## Scope

* One neighbourhood, one workload, one package, `grid128` cells, no model-form band folded in.
* The spans are declarations about per-block activity with the total power preserved. A different
  uncertainty model — correlated variation, a total-power range, a per-class cap — is a different set
  and this curve does not cover it.
