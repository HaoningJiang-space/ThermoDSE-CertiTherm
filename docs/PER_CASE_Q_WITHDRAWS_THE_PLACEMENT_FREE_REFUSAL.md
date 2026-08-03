# Measuring `Q` per case withdraws the placement-free refusal, and creates a different separator

RESULT 2026-08-03, `moe-server`, `/data/ziheng/ThermoDSE-CertiTherm` at `f3b280d`, clean.
NON-CLAIM. Re-run of `research/triangle/robustness/split_missing_heat.py` over the same 12 points and
the same operators, changing **one input**: the missing-energy fraction is now read per case from
`experiments/missing_energy_ledger.tsv` instead of scaled from a single constant.
**No external review** — Codex quota-locked to 2026-08-08.

## The defect

`MISSING_OVER_ARRIVING = 9.2218 / 4.6118 - 1.0 = 0.9997` was the audit closure for **one** case,
`arch_c`/resnet50, applied to all six by scaling with total placed power. `research/triangle/
energy_ledger.py` measures it per case:

| case | source (mJ) | HotSpot-admitted (mJ) | **`Q/admitted`** |
| --- | ---: | ---: | ---: |
| `arch_a`/resnet50 | 8.4896 | 4.7550 | 0.7854 |
| `arch_a`/transformer | 22.5237 | 16.8995 | **0.3328** |
| `arch_b`/resnet50 | 9.2153 | 5.0540 | 0.8234 |
| `arch_b`/transformer | 22.8807 | 16.7377 | 0.3670 |
| `arch_c`/resnet50 | 9.2219 | 4.6116 | **0.9997** ← the value that was used for all six |
| `arch_c`/transformer | 23.6706 | 15.1228 | 0.5652 |

The span is a factor of **three**, and the value in use was the **largest**. Every uplift was
therefore overstated, in the direction that makes the certificate look stricter — the direction that
flatters the method.

This was declared and then used anyway. `MISSING_ENERGY_SENSITIVITY.md` and
`GUARANTEED_RISE_AND_PLACEMENT_SPREAD.md` both label it *"the largest remaining approximation"*.
**Labelling an approximation is not handling it**, and here it inverted the load-bearing half of the
conclusion.

## What the per-case run gives, unfavourable part first

**The placement-free refutation is gone.** `guaranteed = Q * min_i R_ji` is linear in `Q`, and
`arch_b`/transformer's measured `Q` is 63.3 % below the one used. Its upper bound is now
**329.24 K < 330 K**, so it is CERTIFIED rather than refuted under every placement.

> The claim *"2 designs the nominal method calls SAFE and this refutes under every placement"* is
> **withdrawn**. It was an artefact of an overstated `Q`.

| | `8bc90f2` (scaled `Q`) | **measured per-case `Q`** |
| --- | ---: | ---: |
| decided under an incomplete map | 12 / 12 | **12 / 12** |
| placement-free refutations | 2 | **0** |
| disagreements with a guessed guard band | 0 | **2** |

## The 12 points

`L = 330`, `standard` and `enhanced` packages, activity span 0.30.

| case | pkg | nominal | **upper bound** | `Q` (W) | guar | spread | verdict | 3 K guard | 5 K guard |
| --- | --- | ---: | ---: | ---: | ---: | ---: | --- | --- | --- |
| `arch_a`/resnet50 | enh | 321.171 | 322.826 | 11.17 | 0.734 | 0.652 | CERTIFIED | SAFE | SAFE |
| `arch_a`/transformer | enh | 323.493 | 324.914 | 9.59 | 0.630 | 0.560 | CERTIFIED | SAFE | SAFE |
| `arch_b`/resnet50 | enh | 323.398 | 326.086 | 19.06 | 1.129 | 1.118 | CERTIFIED | SAFE | SAFE |
| **`arch_b`/transformer** | enh | 327.006 | **329.239** | 15.23 | 1.006 | 0.882 | **CERTIFIED** | **UNSAFE** | **UNSAFE** |
| `arch_c`/resnet50 | enh | 321.148 | 322.914 | 13.68 | 0.844 | 0.676 | CERTIFIED | SAFE | SAFE |
| `arch_c`/transformer | enh | 323.669 | 325.661 | 16.31 | 0.924 | 0.757 | CERTIFIED | SAFE | SAFE |
| `arch_a`/resnet50 | std | 321.192 | 322.868 | 11.17 | 0.759 | 0.640 | CERTIFIED | SAFE | SAFE |
| `arch_a`/transformer | std | 323.540 | 324.979 | 9.59 | 0.652 | 0.549 | CERTIFIED | SAFE | SAFE |
| `arch_b`/resnet50 | std | 323.392 | 326.081 | 19.06 | 1.145 | 1.100 | CERTIFIED | SAFE | SAFE |
| **`arch_b`/transformer** | std | 327.011 | **329.245** | 15.23 | 1.022 | 0.861 | **CERTIFIED** | **UNSAFE** | **UNSAFE** |
| `arch_c`/resnet50 | std | 321.161 | 322.938 | 13.68 | 0.860 | 0.665 | CERTIFIED | SAFE | SAFE |
| `arch_c`/transformer | std | 323.701 | 325.710 | 16.31 | 0.944 | 0.750 | CERTIFIED | SAFE | SAFE |

## The separator that appeared, and it points the other way

`arch_b`/transformer is **certified feasible** while both guessed guard bands **reject** it. That is a
guard band's **false REJECT**, not a false SAFE: the method rescues a design the convention discards.
It is a cost claim, not a safety claim, and it is the opposite of what `8bc90f2` argued.

**It is robust at `g = 5` and worthless at `g = 3`.** The margin by which the nominal peak crosses the
guard threshold:

| case | `T − (L − 3)` | `T − (L − 5)` |
| --- | ---: | ---: |
| `arch_b`/transformer, enh | **+0.0058** | **+2.0058** |
| `arch_b`/transformer, std | **+0.0106** | **+2.0106** |

At `g = 3` the disagreement is **6 to 11 millikelvin** — two orders of magnitude inside the
`0.2997-1.4332 K` cross-solver band, so it is where the threshold happens to fall and nothing more. At
`g = 5` it is **2.01 K**, against a certified upper bound sitting **0.76 K below the limit**. Only the
`g = 5` disagreement is a separator, and `g` still has no source
(`G2_REPAIR_THE_WINDOW_IS_ONE_DIMENSIONAL.md`), so what is demonstrated is *"there exists a design a
5 K guard rejects and this certifies"*, not *"guard bands are wrong"*.

## The separator's own case is the one closest to failing

`critical_kappa` — the non-uniformity at which each certificate stops holding — on the same run:

| case | `kappa*` (enh / std) |
| --- | ---: |
| `arch_a`/* , `arch_c`/* | inf |
| `arch_b`/resnet50 | 6.960 / 7.163 |
| **`arch_b`/transformer** | **2.147 / 2.189** |

The measured non-uniformity from the routed lowering
(`KAPPA_IS_MEASURED_AND_THE_SUPPORT_IS_WRONG.md`) is **2.140** for NoP and **1.869** for NoC. So the
one case that produces the separator survives the non-uniformity allowance by **0.007 in `kappa`,
about 0.3 %**. The certificate holds on the measured value and would not hold on a slightly less
uniform one. That must be stated wherever the separator is.

## What did not change

* **12/12 decidability.** Every point is decided without knowing where the missing heat goes. This is
  the capability claim and it is `Q`-independent in kind, though not in value.
* **The decomposition.** `R_j q = Q*m + sum_i (R_ji − m) q_i` is exact; only `Q` was wrong.
* **The direction of the guarantee.** `Q*m` is still a true lower bound over every placement.

## What is still owed

* **The support.** `split_missing_heat` still places the missing heat on the compute die. The routed
  lowering puts DRAM — 78-123 % of the missing energy depending on case — on **separate DRAM dies**
  (`KAPPA_IS_MEASURED_AND_THE_SUPPORT_IS_WRONG.md`). Correcting `Q` does not correct **where**. Five
  routed traces plus the V6.1 one now exist for all six development points, so this is wireable
  rather than open-ended.
* **`Q` is per case but the shares are informative on their own.** NoC **over**-injects on every case
  (1.290-1.334), so the DRAM share of the *net* missing energy exceeds 1 on `arch_a` (1.080, 1.230):
  the over-injection is partially masking the DRAM omission in the aggregate. `nop_dict` is
  identically zero on `arch_a` — that architecture emits no NoP energy at all.
* **G0 provenance.** This run recorded its SHA and exit status in this document but did not persist a
  digest manifest beside the JSON.

## The standing rule this cost

**A declared approximation is not a handled one.** Two documents named this `Q` as the largest
remaining approximation and then drew conclusions from it anyway. The cheap check — measure it per
case, which the ledger already could — was available the whole time and takes minutes. Where a
quantity can be measured, a scaled stand-in is not a conservative choice, because nothing guarantees
the stand-in errs in the safe direction; here it happened to err in the flattering one.
