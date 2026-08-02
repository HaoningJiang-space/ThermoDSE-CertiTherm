# Gate 1, step 1: the `E(x)/L(x)` obstruction is removable, and what replaces it

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
linear expression in the round variables. `limit - a_j > 0` always here, since `a_j` is the ambient
row (~318.15 K) and `limit` is 330 K, so no case split on the sign of the multiplier is needed.

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

   **This is a physical modelling question, not a solver question, and it is now the first thing
   Gate 1 owes.** Getting it wrong in the permissive direction produces designs certified on time
   the machine never spends idle.

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
