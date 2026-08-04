# A verdict is relative to a declared thermal model, and the solver gap is measured beside it

METHOD + RESULT 2026-08-04. Replaces the framing in which the HotSpot-versus-FEM band was to be
folded into the certificate. **No external review** — Codex quota-locked to 2026-08-08.

## The object was wrong, not the number

`E_TOTAL_AT_THE_CELL_ENDPOINT.md` measured the disagreement between HotSpot's `grid128-avg` cell
operator and an independent DOLFINx reference, and treated it as a model-form **error band** to fold
one-sidedly into every certificate. Two things make that the wrong object:

* **Neither model is ground truth.** The FEM operator carries `error_k = NaN` deliberately, precisely
  so that nothing in this repository can certify *against* it. A quantity that cannot be certified
  against cannot supply a bound on reality either.
* **The band measures which solver you trust.** Folding it in converts a comparison of two models
  into a claim about a chip, and the resulting number is not a property of the design.

Every thermal DSE in this field produces a verdict relative to whichever solver it ran, silently —
ThermoDSE's `evaluate_thermal()` is one HotSpot call, and its `348 K` cap is documented as
unsupported. The defensible move is not to pretend otherwise. It is to **say which model**, and to
report the gap to an independent one as a separate measured quantity a reader can act on.

## What is now enforced in code, not just written down

`CertiTherm/model_relative_verdict.py`, 14 tests:

| rule | how it is enforced |
| --- | --- |
| a verdict cannot exist without a model | `ModelRelativeVerdict` requires a `ThermalModel`; there is no default |
| a model is not "HotSpot" | it carries solver, `model_id`, package, endpoint **and the operator digest**, because the same binary at the same grid returns a different field for a different package |
| a gap is a measurement, not a bound | `CrossModelGap.measured_on` is **required** and non-empty; a gap with no named cases is refused |
| the gap never reaches the slack | no method combines them; a test asserts attaching a gap does not move `slack_k` |
| folding it in is a **different** claim | `verdict_if_gap_were_a_bound` returns a new object whose model is the **pair**, `max(hotspot,dolfinx)` |
| a bare status is not a sentence | `sentence()` always names the model and the measured disagreement |

The last row is the one that matters in a paper. **"CERTIFIED" is not a sentence.** This is:

> `transformer/arch_b`: **REFUTED with respect to `hotspot/grid128-avg@default[tool_compatible]`**,
> slack `−0.3618 K`, with a measured `+0.0708 K` disagreement against
> `dolfinx/p1-cell128@default[tool_compatible]` on 1 case.

## The round's own verdicts, restated

`research/triangle/robustness/restate_verdicts.py` emits all three columns from evidence already on
disk. The third is what folding the band in amounts to, kept separate because it is a different
claim.

| case | verdict w.r.t. HotSpot | slack | measured gap vs FEM | if the gap were a bound |
| --- | --- | ---: | ---: | --- |
| `resnet50/arch_b` | CERTIFIED | +4.4781 | −0.0687 | CERTIFIED, +3.3687 |
| `resnet50/arch_c` | CERTIFIED | +7.6262 | −0.0276 | CERTIFIED, +6.8761 |
| `transformer/arch_b` | REFUTED | −0.3618 | +0.0708 | REFUTED, −2.1797 |

**The status changes on 0 of 3.** On these cases the distinction is presentational — the two safe
designs clear by 4.5 and 7.6 K against tight bounds of 1.11 and 0.75, and the refused one is refused
either way.

**It bites at the frontier and only there.** The round's composed headline
(`CERTIFIED_MAPPING_AND_THE_UNIFICATION.md`) has `+0.7738 K` of slack against a tight bound of
`~1.82 K` on the nearest measured case, so that verdict **is** `CERTIFIED` with respect to HotSpot and
**would be** `REFUTED` under the pair model. Both sentences are now writable, distinguishable, and
neither can be produced by accident from the other.

## What this does and does not buy

**Buys.** A verdict that is attributable: the operator digest is in it, so the model can be
re-derived. A gap that cannot be silently transferred to a case it was not measured on. And a
statement of the round's central limitation that is precise rather than apologetic — the headline is
model-relative, and the model is named.

**Does not buy.** It does not make the pair-model claim true, and it does not decide which claim a
paper should make. A referee entitled to ask "is this design safe?" is asking the pair question, or a
harder one; a referee asking "does the incumbent's rule admit designs an envelope refutes?" is asking
the model-relative one, and that finding
(`THE_NOMINAL_RULE_ADMITS_WHAT_THE_ENVELOPE_REFUTES.md`) is unaffected because **both rules are
evaluated on the same model**. Separating the two questions is what this type makes possible.

## Scope

* Three cases, legacy captures, `default` package, span 0.30. The routed-trace band is still owed and
  is named as owed in `E_TOTAL_AT_THE_CELL_ENDPOINT.md`.
* Two models compared. A third (3D-ICE) cannot represent this package — its passive layers share one
  global chip footprint while die, spreader and sink here have three — and truncating adds ~2.57 K of
  series copper against a 0.095 K margin, so it is recorded as blocked rather than skipped.
