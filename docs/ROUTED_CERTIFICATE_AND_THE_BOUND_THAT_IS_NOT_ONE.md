# Certifying on the routed trace, and the nuisance bound is not a bound

RESULT 2026-08-03, `moe-server`, `/data/ziheng/ThermoDSE-CertiTherm` at `022df3d`, clean; pinned
HotSpot `sha256 b0040b3e…`, both patches. NON-CLAIM. **No external review** — Codex quota-locked to
2026-08-08.

Six cell operators built on the DRAM-augmented floorplans (187-243 blocks each), then the certificate
taken **from the routed trace directly** — every source where its route puts it, with the lowering's
`source` and `route` reconciliation receipts enforced at load. This is the first verdict in this
repository that is not taken on the legacy trace.

## 1. The six points, certified on the routed trace

`L = 330`, margin `0.05`, linearisation `0.01`, activity span `0.30`, `grid128-avg`, endpoint
`tool_compatible`.

| case | blocks | mean power | **max cell average** | block projection | **slack** | |
| --- | ---: | ---: | ---: | ---: | ---: | --- |
| `arch_a`/resnet50 | 243 | 28.22 W | 326.9768 | 326.1664 | **+2.9632** | CERTIFIED |
| `arch_a`/transformer | 243 | 40.26 W | 328.5463 | 327.6781 | **+1.3937** | CERTIFIED |
| `arch_b`/resnet50 | 233 | 44.79 W | 328.8711 | 328.2872 | **+1.0689** | CERTIFIED |
| **`arch_b`/transformer** | 233 | 57.18 W | **331.5584** | 330.9710 | **−1.6184** | **REFUSED** |
| `arch_c`/resnet50 | 187 | 28.91 W | 326.3818 | 325.7901 | **+3.5582** | CERTIFIED |
| `arch_c`/transformer | 187 | 46.06 W | 329.0170 | 328.3554 | **+0.9230** | CERTIFIED |

**Five of six certify with all the heat placed.** The single refusal is `arch_b`/transformer, the same
point the legacy trace refuses (330.3018, slack −0.3618) and by **1.26 K more** once the missing heat
is present. The cell endpoint sits 0.58-0.87 K above the exact block projection on every case, which
is the cell-vs-block gap `CELL_ENDPOINT_RESULT.md` measures, reproduced here on a different trace.

## 2. The assumed-uniform nuisance placement is not an upper bound

The comparison in §1 changes geometry as well as placement — the augmented floorplan has DRAM dies
the legacy one does not — so it cannot attribute the difference. `placement_only_comparison.py`
removes the confound: **same operator, same floorplan, same total power to machine precision**, only
the placement differs. `assumed` lifts every non-core watt off its block and spreads it area-weighted
over the sys area, which is exactly what `split_missing_heat.py` and `central_share_uplift.py` do.
The quantity is the nominal peak cell average, which needs no polytope — a polytope over one placement
and a polytope over another are different sets, and comparing their suprema would put the confound
back.

| case | **routed** | assumed | assumed + frame share | `assumed − routed` | with frame |
| --- | ---: | ---: | ---: | ---: | ---: |
| `arch_a`/resnet50 | 325.6499 | 324.6657 | 324.4018 | **−0.9842** | **−1.2480** |
| `arch_a`/transformer | 327.1950 | 326.9332 | 326.5978 | **−0.2618** | **−0.5973** |
| `arch_b`/resnet50 | 327.4570 | 327.7299 | 327.5547 | +0.2728 | +0.0976 |
| `arch_b`/transformer | 329.9732 | 330.8834 | 330.6749 | +0.9102 | +0.7017 |
| `arch_c`/resnet50 | 325.1430 | 324.0108 | 323.9099 | **−1.1322** | **−1.2332** |
| `arch_c`/transformer | 327.5475 | 327.1264 | 327.0181 | **−0.4212** | **−0.5294** |

> **On four of six points the assumed placement is BELOW the routed one, by up to 1.13 K — 1.25 K once
> the frame share is included.** A quantity a fail-closed certificate treats as an upper bound is
> under-stating the truth on two thirds of the development split.

**This is the `kappa = 1` singleton argument, measured.** The uniform-density cap `q_i <= Q A_i/A(S)`
with `sum q_i = Q` forces every `q_i` to its bound, so the "supremum over placements" is a **point
evaluation at an assumed placement**. A point evaluation has no reason to dominate a different point,
and here it does not. The structural argument was made in
`KAPPA_IS_MEASURED_AND_THE_SUPPORT_IS_WRONG.md`; this is the number.

**The frame share makes it strictly worse on every case.** `split_missing_heat.py` diverts 19-25 % of
the missing power to `eblk0..3`, and the routed lowering measures those four strips at **exactly zero
watts on all six cases** (`THE_NUISANCE_PARAMETERS_ARE_ALL_MEASURED.md`). Diverting real heat to a
block that carries none is a pure reduction of the reported peak.

## 3. What this does and does not invalidate

**Invalidated as a bound, not as a verdict.** Any CERTIFIED verdict resting on the assumed-uniform
placement — `split_missing_heat.py`'s and `central_share_uplift.py`'s certified columns — is **not
fail-closed**: it can report a peak below the true one. Those tables must be read as *"the value at
the uniform placement"*, which is what their own `kappa` note already says, and not as a certificate.

**Superseded rather than repaired for these six points.** The routed certificate needs no nuisance set
at all: every watt is placed. Five of six certify, and the refusal is the same design either way. The
outcome of the round is unchanged; the *instrument* changed from an assumption to a measurement.

**`Q*m` survives.** The guaranteed-rise term is `Q * min_i R_ji` over whatever support the heat
actually occupies, and it remains a true lower bound. What was wrong was the support and the value of
`Q` (`PER_CASE_Q_WITHDRAWS_THE_PLACEMENT_FREE_REFUSAL.md`), and now neither is needed here.

## 4. G1's bar, and what is left of it

`ROUND_PLAN_FIXED_GEOMETRY.md` G1 asks for: *"compute, NoC, NoP and DRAM energy each placed and
conserved, with the placement justified against source rather than assumed; the energy ledger closing
to the same zero residual the audit already achieves; and the resulting power map differing from the
current one by an amount that is reported, not discovered later."*

* **Placed and conserved** — yes. `source` and `route` receipts reconcile to `< 1e-9` relative on
  every case, and the duration-weighted reduction is checked against the trace's own source receipt.
* **Ledger closing** — yes. `experiments/missing_energy_ledger.tsv`: the four source shares sum to 1
  to `1e-12` before serialisation, with the core residual at `1e-5` of the missing energy, which is
  the ptrace's four-decimal rounding.
* **Justified against source** — partly. `physical_nop.py` replaces ThermoDSE's aliased `link_hops`
  ledger, so routing, accounting and placement share one spatial fact source. But the lowering keeps
  named modelling freedom: `io_die_aspect_ratio` (labelled *"a sensitivity parameter, not a discovered
  fact"* at `routed_trace.py:117`), a fixed 50/50 same-chiplet NoC split, and X-then-Y deterministic
  routing rather than ThermoDSE's own.
* **Difference reported** — yes, §2 is that report, and it is the opposite sign from what was assumed
  on two thirds of the split.

So **G1 is cleared on conservation and placement and open on the lowering's own freedom**, which is
the three-parameter sensitivity `ROUND_PLAN_FIXED_GEOMETRY.md` Step 1 already scopes — and two of the
three (`50/50` split, routing order) are matvecs on the operators just built.

## 5. Scope

* Six development points, one package, `grid128` cells. No model-form band folded in; adding the FEM
  comparison lowers every slack, and `arch_c`/transformer's `+0.9230` and `arch_b`/resnet50's
  `+1.0689` sit inside the 0.251-1.4332 K band, so **two of the five certifications would become
  UNRESOLVED** under it. That is the honest reading and it is why `e_total` at the cell endpoint is
  the binding measurement.
* The routed lowering is not ground truth (§4).
* The operators are bit-identical to a serial build and were produced 15x faster
  (`THE_IMPULSE_LOOP_IS_PARALLEL.md`).
