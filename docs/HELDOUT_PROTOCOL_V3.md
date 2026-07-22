# Frozen Held-out Protocol v3 — Recovery After Invalid Opening

Freeze ID: `method-freeze-v3.0`  
Freeze date: 2026-07-22  
State: **DEFINED_UNOPENED / PRECONDITIONS_PENDING**

## Purpose and lineage

This is the claim-grade successor to the burned `method-freeze-v2.1` split.
The v2 incident, including its dirty-worktree diff and partial physical data,
remains archived and must not influence v3 method choices or endpoints.

v3 retains the scientific question fixed before the invalid opening:

> Under one 1800-second end-to-end query budget, return an oracle-certified
> non-adaptive observation contract and an independently checkable lower bound
> on the minimum registered-library cost.

The split cannot currently execute. `CertiTherm.experiments` rejects both
non-frozen v3 runs and frozen runs while this document says preconditions are
pending. This is an executable guard, not only a prose promise.

## Frozen algorithm

For every ordered workload/package query:

1. compute the uncertainty-width order and run its exact sequential
   early-stop verifier, allowing this phase to use the current remaining
   budget rather than an arbitrary fixed fraction;
2. bind any certified upper bound to one immutable `CertifiedContract`
   containing its registered action IDs, replayed cost, and source;
3. give the exact/IHS proof search only the measured remaining time;
4. if exact closes at an equal or lower cost, replace the width contract with
   the exact contract;
5. report `L`, `U`, `U-L`, `(U-L)/L`, `U/L`, bound provenance, plan validity,
   cost optimality, action IDs, and phase times from that one invocation.

The fixed, width, dual, and exact methods also run as independently budgeted
baselines. Their values cannot be substituted into the Anytime interval.
`method-freeze-v1` remains unchanged and does not run this controller.

## Frozen endpoints and pass conditions

Hard failure: exactly zero internally contradictory or exact-oracle-invalid
certificates.

The gate passes only if all 12 query rows use the frozen budget and:

- at least 10/12 return an oracle-certified contract;
- median certified-U saving is at least 15% versus the full registry;
- at least 6/12 return both a finite certified U and a finite valid L;
- interval and proof-class fields are present and internally consistent.

Exact closure count, U/L over time, and fixed/width/dual cost-runtime Pareto
points are secondary results. A missed threshold is archived as a negative
result; no endpoint or threshold may be changed after opening.

## Strictly new split

Unlike v2.1, v3 reuses neither held-out workloads nor held-out architectures.
All workloads run dense (`sparsity=0`) with one total/executing batch so the
new axis does not depend on unregistered sparsity estimates.

| Workload ID | ThermoDSE network | Family | b_tot | b_exe | sparsity |
|---|---|---|---:|---:|---:|
| `alexnet_v3` | `alex_net` | early CNN | 1 | 1 | 0 |
| `vgg16_v3` | `vgg_net` | deep chain CNN | 1 | 1 | 0 |
| `gnmt_lstm_v3` | `lstm_gnmt` | recurrent | 1 | 1 | 0 |
| `mlp_l_v3` | `mlp_l` | dense MLP negative control | 1 | 1 | 0 |

| ID | grid | cut | interval | mtxu | ubuf | nop_bw | dram_bw |
|---|---|---|---:|---|---:|---:|---:|
| `arch_j` | 6x3 | 2x1 | 0.0012 | 192x128 | 1048576 | 160 | 176 |
| `arch_k` | 2x9 | 1x3 | 0.0018 | 112x192 | 2097152 | 128 | 224 |
| `arch_l` | 10x2 | 5x1 | 0.0008 | 160x144 | 4194304 | 240 | 112 |

The three existing package regimes remain fixed because the novelty required
after the incident is on the workload and architecture axes; changing every
axis would prevent a controlled comparison with dev.

## Permitted pre-open check

Before any HotSpot operator, thermal outcome, measurement registry, or DSOS
query may be generated, one non-thermal ThermoDSE check may evaluate all 12
workload/architecture combinations on the default package. It may answer only:

1. does every vector complete and produce positive latency, energy, and yield;
2. for every workload, are adjacent EDYP values separated by at least 1%?

The exact metrics are archived, but may not tune the algorithm, costs, budget,
thermal limit, or gate thresholds. The check has three possible outcomes:

- `PASS`: accept the complete primary set unchanged;
- `REPLACEMENT_REQUIRED`: an evaluator completed with an explicitly invalid
  metric, or at least one adjacent EDYP gap is below 1%;
- `UNRESOLVED`: an unexpected software or environment failure occurred. This
  outcome authorizes diagnosis, but **not** architecture replacement.

To avoid choosing which member of a close EDYP pair to discard after seeing
the values, any `REPLACEMENT_REQUIRED` outcome replaces the entire primary set
`(arch_j, arch_k, arch_l)` wholesale by `(arch_m, arch_n, arch_o)` in the table
order below. The non-thermal check may then run exactly once more. If that
fallback set does not pass, v3 remains unopened; no further vector may be
introduced.

| Fallback | grid | cut | interval | mtxu | ubuf | nop_bw | dram_bw |
|---|---|---|---:|---|---:|---:|---:|
| `arch_m` | 5x4 | 1x2 | 0.0015 | 192x96 | 1048576 | 144 | 208 |
| `arch_n` | 7x2 | 1x1 | 0.0023 | 112x160 | 524288 | 208 | 144 |
| `arch_o` | 3x6 | 3x2 | 0.0010 | 176x128 | 2097152 | 112 | 240 |

No replacement may depend on temperature, identifiability, contract cost, or
policy performance. After the check, its receipt and decision are committed.
Only then may the protocol become `READY_UNOPENED` and obtain a Make target.

## Remaining preconditions

1. Run the permitted non-thermal check from a clean moe-server clone.
2. Commit the receipt and either accept the primaries or apply only the frozen
   fallback rule.
3. Run the full core tests and a dev-only value-populating rehearsal from the
   exact candidate commit.
4. Audit the report schema, secret/path scan, submodule pins, and artifact
   producer labels.
5. Change the state to `READY_UNOPENED`, enable the frozen guard, and then open
   v3 exactly once from a fresh clone.
