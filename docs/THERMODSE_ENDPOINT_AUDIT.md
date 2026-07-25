# ThermoDSE endpoint audit — what the frozen captures actually contain

Found while probing per-order data for `round/v6-physical-traces`. Both scalar endpoints that
CertiTherm freezes into every capture are wrong, for two independent and unrelated reasons.
The power map is not affected, and neither is the candidate ordering — but the reasons matter,
so they are stated separately.

Measured on `arch_c` / `resnet50`, moe-server, clean clone at `ec91515`.

## 1. `latency_ms` is 1.8x too large — a units bug

`Statistic.get_nn_cost` returns `np.sum(self.latency_dict[nn])`, which is in **CYCLES**
(`statistic.py:87` stores the per-order value straight from `Evaluator`, whose
`latency = cyc_nop_in + max(cyc_list)` is a cycle count). `chiplet_eva.py` accumulates that
into `self.latency` and then converts with

    self.latency = self.latency / 1e6          # ns -> ms      <- chiplet_eva.py:223

which treats cycles as nanoseconds, i.e. assumes a 1 GHz clock. The configured clock is
1.8 GHz (`chiplet_evaluator(..., clock_freq=1.8e9)`, hardcoded in
`CertiTherm/experiments.py:466`).

Confirmed arithmetically, not inferred:

| quantity | value |
| --- | ---: |
| cycles | 606 705 |
| `cycles / 1e6` (what the code computes, labelled ms) | **0.606705** |
| returned endpoint `latency_ms` | **0.606705** |
| `cycles / 1.8e9 * 1e3` (correct ms) | **0.337058** |
| endpoint / correct | **1.800000** |

Three independent confirmations that `0.337058 ms` is the physical value:

1. it is the cycle sum divided by the actual configured clock;
2. ThermoDSE's own `report_network_stats` prints `Delay:0.3370583333333333 ms`
   (`statistic.py:420`, which converts via `/clk_freq` correctly);
3. it is the latency consistent with the power map HotSpot actually consumed, since
   `gen_all_ptrace_3D` divides by `clk_freq` (`statistic.py:292`).

So the same object reports the latency correctly on stdout and incorrectly through its return
value.

### What this does and does not invalidate

- **`placed_power_w` is NOT affected.** The ptrace path uses `/clk_freq`. Every thermal
  result computed from the power map stands.
- **The candidate ORDERING is NOT affected.** `_ordered_architectures` sorts by
  `edyp = latency * energy / die_yield`, and `clock_freq` is hardcoded uniformly for every
  candidate, so the 1.8x is a constant multiplier and the sort is unchanged. Which candidate
  is `c0` / `c1` / `c2` does not move.
- **Absolute latency and absolute EDYP are wrong by 1.8x** wherever they are quoted.
- Any quantity derived as `energy / latency` from the capture fields is wrong by 1.8x in the
  other direction.

## 2. `energy_mj` excludes compute energy — a modelling convention, not a bug

`get_nn_cost` (`statistic.py:200`) returns

    e_tot = e_nop + e_noc + e_dram + e_core - e_comp

subtracting compute energy on the stated grounds that it is fixed across ThermoDSE's design
space. For ranking that is defensible. For thermal work it is not the right quantity, and the
two must not be conflated. The accurate framing is an identity, not an equality:

    optimization_energy_mj       = 7.967035     what EDYP is ranked by (compute excluded)
    excluded_compute_mj          = 1.254866     e_comp
    thermal_dissipated_energy_mj = 9.221901     what actually heats the die

`9.221901 * 0.864 = 7.967035` reproduces the endpoint exactly, and `9.221901` matches
ThermoDSE's own printout. **A thermal trace must be built from the dissipated value.**

## 3. An unchecked capture invariant fails, and the cause is NOT established

`sum(placed_power_w) = 13.68 W`, while the per-order time-weighted mean total is
`27.36 W` — a factor of exactly **2.0000**.

    sum(placed_power_w) * latency_ms(endpoint) = 8.300 mJ  vs energy_mj 7.967  -> 1.042
    sum(placed_power_w) * latency_ms(correct)  = 4.611 mJ  vs energy_mj 7.967  -> 0.579

So the capture is numerically self-consistent with the **wrong** latency and inconsistent with
the correct one. No root cause is claimed here. What reading `gen_all_ptrace_3D` establishes
about the ptrace's contents (read, not inferred):

- `interposer` carries `sum(nop)/latency`; `interposer_e0..e3` are zero.
- Per core, `NAME_LIST_3D = [mtxu, vecu, ubuf, ibuf, obuf, io_0..io_3]`, with
  `ibuf = L0A + L0B` and `obuf = L0C + L1C`.
- Every `io_*` column receives `p_noc / ((cylen-1)*2*cxlen + (cxlen-1)*2*cylen)`, i.e. NoC
  power is spread **uniformly** over IO blocks — which destroys its spatial information by
  construction, and over a block count that need not equal the number of `io_*` columns.
- `blockX/Y/XY` and `eblk0..3` are all zero. **DRAM energy never enters the ptrace**: the
  lines that would have placed it are commented out (`statistic.py:359-363`). DRAM is
  `3.7405e9` of `9.2219e9` pJ — **40.6% of dissipated energy is absent from the thermal
  input.**

The last point is the significant one for the transient direction and is recorded as OPEN.

## Consequences for this round

1. A trace built from per-order data must reconcile against the CYCLE-derived latency, not
   the endpoint, and against dissipated rather than optimization energy.
2. `_capture` should gain a fail-closed invariant check
   (`sum(placed_power_w) * latency ~= dissipated energy`). Such a check would have caught
   both defects at the point they were introduced.
3. Any transient result on this ptrace inherits the missing 40.6% DRAM heat. That must be
   placed, or excluded with the omission stated, or bounded — it cannot be ignored.
4. Nothing here changes which candidates the dev registry selected, so prior comparative
   results stand; absolute latency and EDYP figures do not.
