# Gate 1, step 1: one obstruction removed, one found to be blocking, two claims withdrawn

**READ THE WITHDRAWALS AT THE END BEFORE ANYTHING ELSE.** Claims B, C and D below are withdrawn or
narrowed after round-3 peer review; the text is kept in place so the reasoning that failed stays
visible, but it must not be quoted without its retraction.

ANALYSIS 2026-08-02. NON-CLAIM. Prompted by peer review, which correctly identified that ThermoDSE's
power is `energy / mapping-dependent latency` and that **McCormick does not linearise a ratio** — a
harder obstruction than the placement-pair products, and one the first bilinearity analysis missed.

The conclusion is that the ratio does not have to be linearised at all. What it leaves behind is a
**sign condition**, which is a different and much more tractable problem — but it is a false-ACCEPT
direction, so it has to be discharged explicitly rather than assumed.

## The obstruction, from source

`ThermoDSE/core/statistic.py:231` and `:290`:

```python
latency = np.sum(self.latency_dict[nn_name]) / self.clk_freq
```

and power per block is that block's accumulated energy divided by this `latency`. So

```
p_i(x) = E_i(x) / L(x)
```

with `E_i` bilinear in the placement (it accumulates `hop(c,c') * volume` terms, `nop.py:105`) and
`L(x)` a **sum over rounds** of per-round latencies. Not a global max — `np.sum`, verified above —
so `L` itself is MILP-representable: one variable per round with `L_r >= ` each candidate path, and
`L = sum_r L_r`.

## The removal

The thermal row a certificate asserts is

```
T_j(x) = sum_i R_ji p_i(x) + a_j  <=  limit
```

Substitute and multiply through by `L(x)`, which is strictly positive:

```
sum_i R_ji E_i(x)  <=  (limit - a_j) * L(x)
```

**Both sides are linear in `(E, L)`.** The ratio is gone. `E_i` still needs the standard binary
McCormick treatment for its placement-pair products — exact, not a relaxation — and `L` is already a
linear expression in the round variables.

**The multiplier's sign is not assumed, it is measured.** `limit - a_j` over **all 2 580 rows of all
twelve operators** built for the package sweep is `11.8500 K` on every single row — the ambient is
uniform at 318.15 K, so the multiplier is not merely positive but **constant**, and no case split is
needed. The thermal row is therefore just

```
sum_i R_ji E_i(x)  <=  11.85 * L(x)
```

If a future package or an ambient map made `a_j` row-dependent this must be re-checked, because a row
with `a_j >= limit` would flip the inequality's direction on multiplication and silently invert the
constraint. That is a guard the eventual implementation owes, not a live problem today.

This is not a trick: it is the statement that a *temperature* constraint under constant total energy
is really a constraint on **energy against elapsed time**, which is what a thermal limit physically
is. Dividing to get an average power and then multiplying back is a round trip.

## What replaces it: a false-ACCEPT sign condition

`L` now appears on the **right** of a `<=` with a **positive** coefficient. Larger `L` makes the
constraint **easier**. A MILP that only bounds `L_r >= path` can therefore satisfy a thermal row by
declaring a latency larger than the schedule actually takes — spreading the same energy over
fictitious time and reading a lower average power.

**That is the false-ACCEPT direction and it must be closed, not argued away.** Two routes:

1. **Let the objective close it.** EDYP is `energy * delay / yield`, so the master minimising EDYP
   pushes `L` **down**, against the direction that would relax the thermal row. At the master's
   optimum `L` is therefore at its lower bound and tight. Since the cutting-plane scheme only ever
   certifies the master's *optimum* — every generated cut is checked by replaying that point — this
   is exactly where tightness is needed.
   **But this argument is not airtight and must not be quoted as if it were.** If the thermal row
   binds, the solver has a genuine incentive to lengthen `L`: running slower really does lower
   average power. Whether that is legitimate depends on a modelling decision nobody has made yet.
2. **Decide whether idling is admissible, and say so in the model.**
   * If the hardware may idle, `L_r >= path` is *correct* and a longer schedule is a real design
     point with a real thermal benefit. The certificate is valid as written.
   * If it may not, `L` must be tied to the schedule exactly, which needs complementarity
     (`L_r <= path + M(1 - z)`) and more binaries.

   **This is a physical modelling question, not a solver question.** Getting it wrong in the
   permissive direction produces designs certified on time the machine never spends idle.

### RESOLVED, and by the scheme's own structure rather than by a new constraint

The tension looks unavoidable and is not. Write it out:

* using an **over**-estimate `L_master >= L_true` makes the master row
  `sum_i R_ji E_i <= 11.85 L_master` **weaker** than the true row, so **every truly feasible point is
  master-feasible**. That is exactly the definition of a relaxation — and it is also exactly the
  false-ACCEPT direction.
* using an **under**-estimate is fail-closed but makes the master a **restriction**, which destroys
  the optimality argument: the true optimum can be excluded and never seen.

So one cannot pick the conservative side without losing the theorem. **The resolution is that the
master is not what certifies.** The scheme replays the master's optimum against the true evaluator,
and the arbiter is the replay:

* master optimum **passes replay** → it is feasible for the true problem *and* attains the relaxation
  bound, so `z_true <= f(x*) = z_master <= z_true` and it is the **global optimum**;
* master optimum **fails replay** → a cut is generated at that point and the loop repeats.

A false ACCEPT therefore requires trusting the master **without** replay, which the scheme never
does. The optimistic direction is not a defect here; it is the property that makes the bound valid.

**What this converts the requirement into.** Not a tighter master, but a hard condition on the
replay: **replay must use the TRUE latency and the TRUE energy, from the evaluator, never the
master's model of them.** If replay ever inherits the master's `L`, the arbiter and the proposer
become the same object and the argument collapses. That is a one-line invariant to enforce and to
test, and it replaces the open modelling question above.

The idling question does not disappear, but it stops being a soundness issue and becomes a
*modelling fidelity* one: if the evaluator forbids idling and the master assumes it, the master
merely proposes points that replay rejects — wasted iterations, not wrong certificates.

## What this does and does not change

**Changes:** `EXACT_MAPPING_TO_POWER_MILP` is no longer blocked by the ratio. The remaining exactness
obstacles are the ones peer review listed — grouped multicast, placement-dependent reuse-source
selection, buffer retention/eviction, DRAM fallback (`core/evaluator.py`) — which are hyperedge and
state decisions, not products of two placement variables.

**Does not change:** that a compact chiplet-pair energy model would be a **new abstraction rather
than an exact reformulation of this evaluator**. If the master used one while replay used ThermoDSE,
generated thermal cuts would not be globally valid in the master's variables and the
relaxation-bound theorem would not apply. The component-by-component equality test between MILP
power and ThermoDSE power on adversarial mappings is still the precondition, and it is still unwritten.

## MEASURED: the equality test fails at its very first component

The cheapest component of the equality test peer review demanded is whether the reported energy and
latency reproduce the placed power map at all: `sum_i p_i * L == E`. Measured on all six development
captures (`_power_space`, the same reader the certificate uses):

| capture | `E` (mJ) | `L` (ms) | `E/L` (W) | `sum p` (W) | gap |
| --- | --- | --- | --- | --- | --- |
| resnet50/`arch_a` | 7.2348 | 0.6021 | 12.0160 | 14.2153 | **+18.3 %** |
| resnet50/`arch_b` | 7.9604 | 0.3930 | 20.2575 | 23.1506 | **+14.3 %** |
| resnet50/`arch_c` | 7.9670 | 0.6067 | 13.1316 | 13.6820 | **+4.2 %** |
| transformer/`arch_a` | 16.9768 | 1.0560 | 16.0766 | 28.8061 | **+79.2 %** |
| transformer/`arch_b` | 17.3338 | 0.7258 | 23.8815 | 41.5085 | **+73.8 %** |
| transformer/`arch_c` | 18.1237 | 0.9432 | 19.2144 | 28.8593 | **+50.2 %** |

**`p = E / L` is not the relation between the numbers this pipeline actually carries.** The placed
map draws 4–79 % more power than the reported energy over the reported latency, one-signed on all six.

**The dominant mechanism is confirmed at source, and it is DELIBERATE rather than a bug.**
`ThermoDSE/core/statistic.py:200`, comment included:

```python
e_tot = e_nop + e_noc + e_dram + e_core - e_comp  # exclude the energy of computing units, since they are always fixed
```

`e_comp` is `mtxu + vecu`. Meanwhile `gen_ptrace` (`:203`) writes the **full** per-block energy,
compute included. **So the objective's energy and the thermal model's energy are different
quantities by construction**, and the reported `E` is short by exactly the compute term. That
predicts the sign (positive on all six), and predicts transformer being worst (GEMM-dominated).

**It does not explain everything, and the residual is stated rather than absorbed.** The same
workload varies 4.2 % to 18.3 % across architectures, which a fixed compute fraction cannot produce
alone. A second effect is still present — most plausibly peak-versus-mean, since `sum p` is the
placed instantaneous map while `E/L` is a time average, and
`docs/ARCHIVE_CENSUS_RESULT.md` already measured a 19 % spread of that kind on `arxv017`. The two
compound and have not been separated.

**Why this is decision-relevant regardless of which mechanism it is.** A MILP whose objective and
whose thermal rows both use ThermoDSE's reported `energy_mj` would drive a power map that is 4–79 %
below the one the thermal operator is actually evaluated on. The generated cuts would be valid for a
quantity nobody certifies. **So the master cannot take its energy from the reported scalar; it has
to reproduce the ptrace accounting itself**, and that accounting is the one with the documented
defect. Gate 1's first task is therefore not the MILP — it is deciding which energy definition the
certificate is about.

**Status unchanged:** `CERTITHERM_OPT_KILL_CONDITION: NOT CLEARED`. This step removes one obstruction,
names its replacement, and **finds a third that was not on anyone's list**: the two energy
accountings in this pipeline do not agree, and the certificate is built on the one that is not
reported.

## DECISION: the certificate is about `E_full`, and it costs nothing to say so

The question "which energy definition is the certificate about" is not open. It is answered by where
the power map comes from: `_power_space` reads the **placed map**, which is the ptrace, and
`gen_ptrace` (`statistic.py:221`) computes each block's power as

```python
avg_p = np.sum(self.core_dict[nn_name][:, idx, m]) * 1e-12 / latency
```

over **every** component `m`, `mtxu` and `vecu` included. So the thermal operator has only ever been
evaluated on `E_full = e_nop + e_noc + e_dram + e_core`. **The certificate is about `E_full`. `e_tot`
is a search objective and belongs in the objective; it is not a thermal quantity.** These are two
different quantities with two different jobs, and the mistake was reading them as competing
definitions of one.

**And the decision costs nothing — but NOT for the reason first written here.**

**CORRECTED before review.** The first version of this section argued the compute term is a
*constant*, on the strength of `statistic.py:81`
`core_dict[:, i, :] = core_dict[:, 0, :]`. That line lives inside **`cost_copy()`**, and
`chiplet_eva.py:229` calls it only `if self.baseline2 or self.baseline3`. **On the default path the
replication does not happen**, so per-core compute energy is whatever `update_internal_info` wrote
and it does depend on what was mapped there. The constant argument is withdrawn.

The conclusion survives on a different and simpler footing. A task's compute energy does not depend
on *where* it runs — only on the task — so the compute energy landing on block `i` is

```
c_i(x) = sum_t x[t,i] * e_comp(t)
```

which is **linear in `x`: one index, not a product**. So

```
E_full,i(x) = E_var,i(x) + c_i(x)
```

and the thermal row stays exactly as tractable as before:

```
sum_i R_ji ( E_var,i(x) + c_i(x) )  <=  (limit - a_j) L(x)
```

**Still no McCormick term, no new variable, no new binary** — the compute part is the *easiest* part
of the model, being the only one with a single placement index. What changes versus the withdrawn
version is that it moves a linear expression rather than a right-hand constant, which matters
because a constant would have been invisible to the search and a linear term is not: **the master
can trade compute placement against thermal feasibility, and that is a real degree of freedom the
constant reading would have hidden.**

**What this closes and what it does not.** It closes the third obstruction found above — the two
accountings disagree, but the disagreement is a constant the thermal row absorbs. It does **not**
close `EXACT_MAPPING_TO_POWER_MILP`, because the *variable* part `E_var` still contains the
hyperedge and state behaviour peer review listed (grouped multicast, placement-dependent
reuse-source selection, buffer retention/eviction, DRAM fallback). Those are what the
component-by-component equality test has to cover, and they remain unwritten.

**The residual is now partly explained by the correction itself.** With `c_i(x)` mapping-dependent
rather than constant, a gap that varies 4.2 % to 18.3 % *within one workload across architectures*
is no longer anomalous: different architectures place the same compute differently and have
different core counts, so the excluded `e_comp` is a different fraction of the total in each. That
removes the need to invoke a second mechanism to explain the spread, though it does not rule one
out — peak-versus-mean remains plausible and unseparated, and `docs/ARCHIVE_CENSUS_RESULT.md`
measured a 19 % spread of that kind independently.

---

# WITHDRAWALS 2026-08-02, after round-3 peer review

Three of the four claims above are withdrawn or narrowed. Each withdrawal names the premise it rests
on and that premise was checked against source, per the standing rule that a retraction is held to
the same falsification standard as a promotion.

## The process failure first, because it caused two of the three

**`docs/THERMODSE_ENDPOINT_AUDIT.md` was committed on 2026-08-01 and I did not read it.** It already
establishes, by measurement on `arch_c`/resnet50 at `ec91515`:

* **`latency_ms` is 1.8x too large** — a units bug, cycles accumulated where time was meant;
* the aligned ptrace **excludes DRAM entirely, drops NoP during alignment, and over-counts NoC by
  33.41 %**, and the resulting `2.0000x` against the per-order mean is **fully accounted for with
  zero residual**;
* its `sum(placed_power_w) = 13.68 W` is **the same number** the table above reports for
  `resnet50/arch_c`.

So the measurement was arithmetically right and **scientifically ill-posed**: I re-derived one side
of a discrepancy the repository had already decomposed to zero residual, and then attributed it to a
mechanism that document rules out. This is the "grep the repository before writing a new script"
rule in `CLAUDE.md`, and the cost was a whole section of wrong conclusions.

## C — WITHDRAWN

`sum_i p_i * L` and `energy_mj` are **not two endpoints of one conservation identity**. `L` is 1.8x
too large, so the left side is overstated by 1.8x; and the two sides cover different channels —
the ptrace has no DRAM and, after alignment, no NoP, while `energy_mj` includes both and excludes
compute. **The +4.2 % to +79.2 % gaps therefore do not isolate the compute subtraction and do not
support the `e_tot` mechanism**, however well the sign and ordering appeared to fit. Peak-versus-mean
is also not the residual explanation: `gen_all_ptrace_3D` emits one time-averaged sample.

What is required instead is the ledger that audit already demonstrates: `E_objective`,
`E_source-full`, `E_raw-ptrace`, `E_aligned-ptrace` under **physical** latency, reconciling each
transition to near-zero residual.

## D — WITHDRAWN in its headline, narrowed to what survives

**"The certificate is about `E_full` because that is what the operator has always been evaluated
on" is FALSE.** The aligned operator sees core energy plus distorted NoC, **no DRAM**, and **no NoP**.
It has never seen `e_nop + e_noc + e_dram + e_core`. The captures also use
`gen_all_ptrace_3D` (`chiplet_eva.py:231`), not the `gen_ptrace` I cited.

**What survives** is the linearity result, and only in the corrected form already committed at
`4bb62c4`: compute work is placement-invariant per task, so per-core compute energy is
`E_comp[c,m](x) = sum_{r,t} x[r,t,c] * e_comp[t,m]` for `m` in `{mtxu, vecu}` — **linear in the
assignment variables**, indexed by component and core rather than a scalar per block. It is not a
right-hand constant, and this document's earlier sentence calling the disagreement "a constant the
thermal row absorbs" is void.

**The certificate target must be defined operationally from the aligned ptrace transformation**, not
from scalar energy names — and the prior question is whether the intended target is today's defective
compute-domain trace or a corrected trace that conserves DRAM/NoP/NoC.

## B — WITHDRAWN; the replay argument does not close it

My resolution was that replay is the arbiter, so an optimistic master is harmless. **That is wrong,
and the counter-argument is decisive: the generated cuts are thermal rows, and a point that is
infeasible because of its *latency representation* is not excluded by any thermal row.** Replay
rejects the point, the cut is added, and the master can return the same point again. The loop need
not converge, and no valid cut exists to make it.

`L_r >= q_rk` is the **epigraph** of a max, not equality to it. Closing this needs one of two
explicit contracts, and the choice is a modelling decision:

* **no idle** — tie `L_r = max_k q_rk(x)` exactly, e.g. one-hot `z_rk` with `L_r <= q_rk + M_rk(1 - z_rk)`
  and `sum_k z_rk = 1`, with proved finite big-M;
* **idle allowed** — explicit bounded idle variables `d_r`, `L_r = max_k q_rk(x) + d_r`, replayed with
  the identical idle schedule, and idle/leakage energy plus any deadline or throughput constraint
  included.

An unconstrained epigraph variable is not an idle policy. **Status: `UNRESOLVED`, blocking.**

## A — survives, but it transformed the wrong row

The algebra is exact and multiplying by `L > 0` never reverses the inequality (an earlier sentence
here implied it could; that is void — the sign of `limit - a_j` controls only whether a larger `L`
*relaxes* the row). Two corrections:

* the certificate's actual SAFE ceiling is `limit - margin - error_m - a_mj`
  (`CertiTherm/thermal_constraints.py:55`), not `limit - a_j`. **The transformation above is of a
  weaker row than the one the certificate uses** and must be redone on the registered row.
* `core.py:183` validates shape and finiteness but **not** `ambient_k < limit_k`. The measured
  11.85 K holds on all 2 580 rows of the current operators, but that is an observation, not a
  guarantee; a fail-closed per-row headroom guard is owed.

## Net effect on the gate

`CERTITHERM_OPT_KILL_CONDITION` remains **NOT CLEARED**, and this round moved it backwards rather
than forwards: one obstruction (the ratio) is genuinely removed, one (the latency representation) is
now known to be blocking rather than resolved, and the energy-definition question is reopened on a
firmer footing than the one I closed it with.

---

# B, closed: the idle question has a decisive answer and the max is over TWO terms

## Why "idle allowed" cannot be the contract — the certificate would be vacuous

As `L` grows, `p = E/L -> 0`, so `T -> ambient`. **With unbounded idle, every architecture is
thermally certifiable — just run it slowly enough.** The feasibility question this whole project
asks would be degenerate: the answer would always be SAFE and the observation-sufficiency headline
would be about nothing.

So "idle allowed" is admissible **only** with an explicit deadline or throughput constraint that
bounds `L` from above. No such constraint exists anywhere in this pipeline: the captures carry a
latency produced by the schedule, and the certificate reads a power map derived from it. **The
contract implicit in every number already committed is therefore NO IDLE**, and stating it is a
correction of record-keeping, not a change of model.

This also disposes of the earlier hedge. It is not that the EDYP objective *probably* keeps `L`
tight; it is that a model permitting fictitious idle answers a different and empty question.

## The exact encoding is one binary per round, not a big-M family

`ThermoDSE/core/evaluator.py:58`:

```python
cyc_list = [cyc_core, cyc_nop_out]
latency  = cyc_nop_in + max(cyc_list)
```

**The max is over exactly two terms.** So `L_r = a_r + max(u_r, v_r)` with
`a_r = cyc_nop_in`, `u_r = cyc_core`, `v_r = cyc_nop_out`, and the exact encoding is one binary
`z_r` with four rows:

```
L_r >= a_r + u_r
L_r >= a_r + v_r
L_r <= a_r + u_r + M_r (1 - z_r)
L_r <= a_r + v_r + M_r  z_r
```

`z_r = 1` selects `u_r` as the bottleneck. `M_r` is any bound on `|u_r - v_r|`, and a finite one is
immediate: both are cycle counts bounded by the round's total issued work. **Rounds number in the
tens**, so this is a few dozen binaries and a few hundred rows — negligible beside the
`O(|E| C**2)` transport variables that dominate the mapping MILP anyway.

**And the binary has a directly observable ground truth.** `evaluator.py:64` already records

```python
self.bottleneck.append(cyc_list.index(max(cyc_list)))
```

so every `z_r` the MILP chooses can be checked against what the evaluator actually did, on a real
mapping, without instrumenting anything. That is the cheapest possible validation of the encoding
and it should be the first row of the component-by-component ledger.

## Status change

`L_r >= q_rk` being an epigraph rather than an equality was the blocking defect. With the contract
declared (**no idle**) and the encoding exact (**one binary per round**), it is closed at a cost
that does not change the tractability picture.

`EXACT_MAPPING_TO_POWER_MILP` remains **UNRESOLVED**, now for one reason only: the *variable* energy
`E_var` still carries the hyperedge and state behaviour — grouped multicast, placement-dependent
reuse-source selection, buffer retention/eviction, DRAM fallback — and the energy-domain question
reopened by the D withdrawal, namely whether the target is today's defective compute-domain trace
or a corrected trace conserving DRAM/NoP/NoC. **That correction is a prerequisite for the MILP, not
a refinement of it**, because a master fitted to a trace missing DRAM and NoP would generate cuts
for a thermal object nobody intends to certify.

---

# The energy-domain question is ANSWERED in the repository, and the answer prescribes an artifact

Read properly this time. `docs/THERMODSE_ENDPOINT_AUDIT.md` does not merely explain why my
measurement was ill-posed — **it answers the question the D withdrawal reopened, and it specifies
the check I should have implemented instead of re-deriving one.**

## The answer

Three distinct energies, an identity rather than an equality (audit §2), on `arch_c`/resnet50:

| quantity | mJ | what it is |
| --- | ---: | --- |
| `optimization_energy_mj` | 7.967035 | what EDYP ranks by — compute **excluded** |
| `excluded_compute_mj` | 1.254866 | `e_comp` |
| **`thermal_dissipated_energy_mj`** | **9.221901** | **what actually heats the die** |

**"A thermal trace must be built from the dissipated value"** — audit §2, already committed. So the
certificate's energy target was never ambiguous, and my "decision" restated an answer that existed.

But the dissipated value is not what reaches HotSpot either (audit §3, zero residual):

```
dissipated - DRAM - NoP + NoC over-count = energy reaching HotSpot
9.2218e9   - 3.7405e9 - 1.0052e9 + 1.3560e8 = 4.6118e9 pJ
```

DRAM is **40.56 %** never written; NoP is **10.90 %** written then dropped by name alignment; NoC is
over-counted by **+33.41 %** and spread **uniformly** over IO blocks, which erases the spatial
information a spatial trace exists to carry.

## Why my measurement showed 4–79 %, exactly

Recomputing the audit's own closure: `4.6118 mJ / 0.337058 ms = 13.683 W` against its reported
`sum(placed_power_w) = 13.68 W` — **residual 0.0025 W, i.e. rounding.** The invariant closes
perfectly with **cycle-derived latency and post-loss energy**. My version used the **endpoint**
latency, which audit §1 proves is 1.8× too large, and pre-loss energy. Both errors push the same
way. There was never a new phenomenon.

## The artifact the audit prescribed and nobody built

Audit §"Consequences", item 2, verbatim:

> `_capture` should gain a fail-closed invariant check (`sum(placed_power_w) * latency ~= dissipated
> energy`). Such a check would have caught both defects at the point they were introduced.

**Grepped: it is not implemented.** `thermodse_bridge.py` only *comments* on the 10.90 % NoP loss
(`:100`). So a recommendation that would have prevented both endpoint defects — and would have
prevented my whole withdrawn section — has sat unimplemented since 2026-08-01.

**That, not the MILP, is the next artifact.** Its exact form, from the audit's own closure:

```
sum(placed_power_w) * (cycles / clk_freq)  ==  dissipated - DRAM - NoP + NoC_overcount
```

with every term taken from `research/triangle/energy_ledger.py`, which already probes each source by
isolation and whose linearity was verified at **0.000e+00 W** column error. Every quantity needed
exists; nothing new has to be measured.

**Why it outranks the MILP.** A master fitted to a trace missing 40.56 % DRAM and 10.90 % NoP, with
NoC over-counted 33.41 % and spatially flattened, would generate cuts for a thermal object nobody
intends to certify — and would do so *convincingly*, because understating heat leaves every output
plausible. That is the audit's own explanation for why nothing caught these defects, and it applies
verbatim to the proposed scheme.

## Status

`EXACT_MAPPING_TO_POWER_MILP` stays **UNRESOLVED**, but the reason is now singular and actionable:
**the trace the certificate is built on does not conserve the energy it claims to.** Fixing that is
the prerequisite. The hyperedge/state behaviour in `E_var` is the second item and is downstream of it.
