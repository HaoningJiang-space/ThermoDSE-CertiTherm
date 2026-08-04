

> **Produced by** `research/triangle/robustness/nominal_vs_envelope_feasible_set.py`. Recorded here because a doc that cites numbers without naming its producer makes that script look orphaned to every dead-code scan, and the scan is right to flag it: nothing else points at it.
# P0: the "you used the wrong cap" objection, measured and closed

RESULT 2026-08-04. NON-CLAIM, exact post-processing of `certified_search` evidence already on disk;
no solver, no sampling. **No external review** — Codex quota-locked to 2026-08-08.

## The objection

`docs/CERTIFIED_SEARCH_RESULT.md` reports a certificate-constrained search reaching a feasible design
at `+8.77 %` EDYP from a baseline the certificate refuses. The strongest reply is that the baseline
was tuned against the **wrong limit**: ThermoDSE's own cap is `348 K` and this study's is `330 K`, so
a fair comparison would re-run ThermoDSE's search at 330 K and it would presumably find the same
design we did.

## Why the answer does not need their optimiser, and is stronger without it

ThermoDSE's thermal feasibility test is `evaluate_thermal()` — one **nominal** HotSpot peak — entering
`tools/scbo_search.py` as the hard SCBO constraint `c2 = peak_temp - max_temp <= 0`, with an
additional `+0.05 * (maxT - peak_temp)` coolness bonus in the objective. (Both were read from source:
the constraint is real, it is not merely a penalty.) So the two feasible sets are

    F_nominal(L)  = { design : nominal peak <= L }
    F_envelope    = { design : sup over the declared activity envelope <= L - margin - error }

and both are **deterministic functions of numbers already measured for every candidate**. Comparing
the sets is exact. Re-running a stochastic optimiser answers the same question with sampling noise on
top and invites *"your BO run was unlucky"* as a reply.

The conclusion is therefore about the **rule**, not the optimiser — which is the stronger claim,
because it survives any search algorithm built on that rule.

## Result, on the `arch_b`/transformer neighbourhood (12 candidates, 0 unresolved)

Evaluated at **330 K**, i.e. the objection's own strongest form. ThermoDSE's actual 348 K cap admits
strictly more.

| | feasible |
| --- | ---: |
| nominal rule, `peak ≤ 330.0` | **10 / 12** |
| envelope rule, `sup ≤ 329.94` | **3 / 12** |

| rule | its optimum | EDYP | nominal | certified |
| --- | --- | ---: | ---: | ---: |
| nominal | `mtxu_h = 128` | **13.8628** | 329.973 | **331.558** |
| envelope | `mtxu_h = 192` | 15.0792 | 328.307 | 329.612 |

> **Seven of the ten designs the nominal rule admits are refuted by the envelope — including its own
> optimum.** Corrected to 330 K, ThermoDSE's feasibility rule still selects `mtxu_h = 128`, whose
> nominal peak reads `329.973 ≤ 330` while its supremum over the envelope is `331.558`. The objection
> is answered: the wrong cap is not what produced the disagreement, **the wrong kind of test is.**

The five cheapest such designs span nominal peaks `328.791` to `329.973` — all comfortably under the
limit — against suprema `330.072` to `331.558`, all over the ceiling. The gap between the two
quantities is **0.4 to 1.6 K** here, which is the size of the error the nominal rule makes.

## The direction of the disagreement, which bounds the claim

| | count |
| --- | ---: |
| admitted by nominal, refuted by envelope | **7** |
| refused by nominal, certified by envelope | **0** |

`F_envelope ⊆ F_nominal` on every candidate measured. That is one-sidedness demonstrated on real
designs rather than argued from the construction, and it **bounds what can be claimed**: the
certificate can only ever *cost* EDYP relative to the nominal rule, never gain. There is no design
here that the incumbent wrongly rejects and we rescue. The contribution is soundness, not reach.

## Where the two rules agree, and it is most of the space

On `arch_c`/transformer (14 candidates) the two rules are **identical**: 14/14 feasible under both,
the same optimum, EDYP ratio `1.0000`, zero disagreements in either direction.

**So the rules coincide away from the frontier and diverge at it.** That is the honest scope of the
finding and it is the same lesson the two archive populations gave: under `resnet50` the archive
designs sit 4.94-9.17 K from the ceiling and nothing disagrees; under `transformer` they reach it and
disagreement appears. A method that only matters near the limit is exactly what a feasibility
certificate should be — but the claim must be stated that way and not as a general improvement.

## What is NOT claimed

* **Not that ThermoDSE's search is bad.** Its constraint is real and hard. The finding is that a
  constraint evaluated at one power map does not define the feasible set over an envelope of them.
* **Not that 330 K is the right limit.** `CertiTherm/frozen_limits.py` still gives it no provenance,
  and ThermoDSE's 348 K is documented as unsupported. The comparison is run at 330 K because that is
  the objection's strongest form, not because 330 K is established.
* **Not a global statement about the design space.** Two neighbourhoods, one workload, 26 candidates.
  The scale-up to all six seeds is running.
* **No model-form band is folded in.** It would lower every peak by 0.25-1.43 K on both sides of the
  comparison; because it is applied to both rules its effect on the *disagreement* is second-order,
  but the envelope optimum's `+0.328 K` slack would become `UNRESOLVED`.
