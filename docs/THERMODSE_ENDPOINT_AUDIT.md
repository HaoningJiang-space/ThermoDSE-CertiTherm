# ThermoDSE endpoint audit — what the frozen captures actually contain

> **Produced by** `research/triangle/legacy_core_transient_audit.py`. Recorded here because a doc that cites numbers without naming its producer makes that script look orphaned to every dead-code scan, and the scan is right to flag it: nothing else points at it.

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

## 3. RESOLVED — half the dissipated energy never reaches the thermal model

The `2.0000x` between `sum(placed_power_w) = 13.68 W` and the per-order mean total of
`27.36 W` is now fully accounted for, by measurement, with **zero residual**. It is the
coincidental product of two independent losses and one over-count.

### The measurement

An energy-source ledger (`research/triangle/energy_ledger.py`) probes each source by
ISOLATION — zero every other source, re-run ThermoDSE's OWN `gen_all_ptrace_3D`, read the
file back — so destination columns are established by the original code rather than by
reading it. The generator's linearity was verified, not assumed: isolated sources superpose
to the unmodified reference with a **maximum column error of 0.000e+00 W**.

| source | energy (pJ) | ptraced | in-domain | columns |
| --- | ---: | ---: | ---: | ---: |
| `core_dict` | 4.0703e9 | 12.0756 W | 100.00% | 80 |
| `noc_dict` | 4.0585e8 | 1.6064 W | **133.41%** | 64 |
| `nop_dict` | 1.0052e9 | 2.9824 W | 100.00% | 1 |
| `dram_dict` | 3.7405e9 | **0 W** | **0.00%** | **0** |

Then the alignment step was measured directly:

    raw cores_3D.ptrace  : 186 columns, 16.6644 W
    name_aligned.ptrace  : 181 columns, 13.6820 W
    dropped              :   5 columns,  2.9824 W

The five dropped columns are `interposer` and `interposer_e0..e3`. **None of them exists as a
floorplan unit** (`grep -c '^interposer	' output_3D.flp` = 0), so `align_trace` — which
aligns by name — carried none of them over. The dropped 2.9824 W is *exactly* the
`interposer` column, i.e. all NoP power.

### The closure

    total sources - DRAM - NoP + NoC over-count  =  energy reaching HotSpot
    9.2218e9      - 3.7405e9 - 1.0052e9 + 1.3560e8  =  4.6118e9 pJ
    residual: 0.00e+00

    9.2218e9 / 4.6118e9 = 2.0000

| loss | share of source energy | mechanism |
| --- | ---: | --- |
| DRAM | **40.56%** | never written to any column (the placing code is commented out) |
| NoP | **10.90%** | written, then silently dropped by name alignment |
| **combined** | **51.46%** | — |

plus NoC over-counted by **+33.41%**.

**About half the dissipated energy never reaches HotSpot.** Note the two are different in
kind: the DRAM omission is at least consistent with a compute-domain model, whereas the NoP
loss is an unintended alignment failure that nobody chose.

Distinguish two percentages that are easy to conflate: DRAM is **40.56%** of source energy
(`3.7405/9.2219`), while **39.09%** is the *net* excluded ledger energy
(`3.605026/9.221901`) — smaller because the NoC over-count is credited in-domain.

### Fixed

`align_trace` now fails closed on any unplaced column carrying power, returning the report
and accepting the omission only via an explicit `allow_unplaced` that records what was
discarded (`CertiTherm/tests/test_trace_alignment.py`). Understating heat leaves the output
entirely plausible, which is why nothing caught this.

### What reading `gen_all_ptrace_3D` establishes about the ptrace (read, not inferred)

- `interposer` carries `sum(nop)/latency`; `interposer_e0..e3` are zero.
- Per core, `NAME_LIST_3D = [mtxu, vecu, ubuf, ibuf, obuf, io_0..io_3]`, with
  `ibuf = L0A + L0B` and `obuf = L0C + L1C`.
- Every `io_*` column receives `p_noc / ((cylen-1)*2*cxlen + (cxlen-1)*2*cylen)`, i.e. NoC
  power is spread **uniformly** over IO blocks — which destroys its spatial information by
  construction, and over a block count that need not equal the number of `io_*` columns.
- `blockX/Y/XY` and `eblk0..3` are all zero. **DRAM energy never enters the ptrace**: the
  lines that would have placed it are commented out (`statistic.py:359-363`), and they would
  have written FIVE columns (`dram` plus four edge strips) matching a separate `dram.flp`,
  not the four `eblk` columns actually emitted.

## 4. The DRAM boundary — what is and is not established

`dram.flp` exists alongside the compute floorplan and contains `dram_e0..e3` whose geometry
is byte-identical to `eblk0..3`, plus a central `dram` block. `example.lcf` exists but
references the stock Alpha EV6 example floorplans, and the run invokes HotSpot with
`-f output_3D.flp -model_type block`, no `-model_3D`, no layer file. `grep -c dram
output_3D.flp` = 0.

**Established:** the executed model is a planar block-level compute-domain model with no
explicit DRAM power source and no DRAM thermal node, so DRAM self-heating and explicit
DRAM–compute coupling are omitted.

**NOT established, and previously overstated here:**

- that DRAM is *physically* outside the thermal domain. Block-mode HotSpot still carries
  implicit package, spreader, sink and ambient paths, so "absent from the solved model" is
  not "outside the physical domain".
- the *purpose* of `eblk0..3`. Identical geometry makes the filler reading plausible but does
  not establish it. An earlier hypothesis that the floorplan "reserves DRAM block positions"
  was wrong and is withdrawn; the reserved positions are in `dram.flp`, which is not used.

**Consequence for claims.** A flip found on this ptrace may support *"under the stated
compute-domain / no-explicit-DRAM boundary, the cheap abstraction does not preserve decision
X"* — never a package-level claim, a DRAM-inclusive safety certification, or a quantitative
physical temperature. A sensitivity envelope over non-negative nuisance heat loads can test
robustness (a linear passive thermal network is monotone in applied heat) but is not a
physical bound without independently justified magnitudes and paths.

## 5. NoC: a blocking defect for spatial claims

NoC is ptraced at 133.41% of its source energy, and spread **uniformly** over the `io_*`
columns. Both matter, differently: the over-count violates source conservation, and the
uniform spreading erases exactly the event-dependent spatial information a spatial trace is
meant to measure. **Documentation cannot turn an incorrect energy transform into a certified
trace**, so this must be corrected — or NoC reclassified as a nuisance/background model — before
any spatial claim.

The direction of bias is **indeterminate**: extra power raises temperature and pushes toward
infeasibility, while uniform spreading suppresses local hotspots and may *hide* a spatial
flip. Which dominates depends on how the coarse and refined abstractions each respond.

Likewise the single lumped `interposer` column conserves NoP energy while discarding the
location of every NoP link and PHY. It is a documented lumped background source, not
floorplan-resolved interconnect activity.

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
