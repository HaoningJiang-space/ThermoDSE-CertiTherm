# G4 registered acquisition schema and evidence protocol

G4 consumes one `spatial_equivalence` query artifact from a replay-valid G3
suite.  It never reconstructs a power trace, thermal operator, or candidate
pool.  The only new scientific input is a content-bound registry of obtainable
linear measurements.

## Registry v1

Schema: `certitherm.g4-measurement-registry.v1`

Required top-level fields:

| Field | Meaning |
| --- | --- |
| `registry_id` | stable experiment identity |
| `evidence_class` | `synthetic_fixture` for tests or `physical_measurement_family` for claim-grade execution |
| `query_artifact_sha256` | exact parent G2 spatial-query artifact |
| `query_digest` | exact cross-candidate query semantics |
| `measurement_value_tolerance_w` | threshold below which two witness values are indistinguishable |
| `registration` | frozen family, cost model/unit, and obtainability basis |
| `source_files` | relative, SHA-256-bound sensor-map/report/config inputs; non-empty for physical evidence |
| `actions` | non-empty list of registered candidate-specific linear forms |

Each action contains:

| Field | Meaning |
| --- | --- |
| `measurement_id` | stable action identity; never parsed for semantics |
| `candidate_id` | architecture candidate on which the information is acquired |
| `coefficients_by_block` | sparse, nonnegative `block_name -> coefficient` map for `m(p)=w^T p` |
| `cost` | positive scalar under the registry's common cost model |
| `obtainability_record` | why this measurement is available at the registered EDA stage |

Explicit block identities prevent the legacy component-order and name-parser
failures.  The runner verifies every source file relative to the registry
bundle. The registry file, source digests, action family, and parent query are
all hashed in the G4 artifact. Claim-grade CLI execution rejects a synthetic
registry.

## Evaluation semantics

For each action in ascending `(cost, measurement_id)` order:

1. project each of the two decision-changing witness tuples to a measurement
   value;
2. reject the action if those values are equal within the registered tolerance;
3. append `w^T p = m_i` to the target candidate's existing observation while
   preserving every prior equality, inequality, and component bound;
4. replay the source witness's membership in the augmented domain;
5. solve the complete cross-candidate architecture query; and
6. accept only if both conditioned queries are `CERTIFIED`, reproduce their
   respective witness outcomes, and those outcomes differ.

If a cheaper action produces an unresolved solve, G4 fails closed; it cannot
skip that action and still claim the selected action is cheapest in the
registry.  Evaluation stops after the first accepted action because the order
is already total and content-bound.

## Result statuses

| Status | Interpretation |
| --- | --- |
| `WITNESS_PAIR_CONFIRMED` | cheapest registered action confirms both stored witness outcomes |
| `NO_REGISTERED_WITNESS_CONFIRMING_ACTION` | every registered action was resolved and none confirmed both witnesses |
| `NOT_APPLICABLE` | parent query was not `NON_IDENTIFIABLE` |
| `UNRESOLVED` | malformed evidence, solver/replay failure, or certificate contradiction blocks a conclusion |

`WITNESS_PAIR_CONFIRMED` is not the stronger statement that every measurement
value makes the query identifiable.  It is also not global minimum
information outside the registry.

## Claim-grade execution

The runner accepts a G3 suite artifact, one suite `query_id`, and one registry.
It requires a clean source tree and writes the raw artifact and replay receipt
outside Git:

```text
python -m CertiTherm.exact.g4_acquisition \
  --g3-artifact /external/g3-suite.json \
  --query-id <registered-query-id> \
  --registry /external/g4-registry.json \
  --artifact /external/g4-artifact.json \
  --receipt /external/g4-receipt.json
```

The artifact embeds the selected G2 spatial query, registry, result, source
commit, environment, command, input hashes, runtime, and peak RSS.  Replay
checks the envelope, replays the G2 artifact, re-runs every required
conditioned query, and compares decision semantics with numerical tolerance.

## Evidence table shells (no results yet)

### Per-query acquisition outcome

| Workload | Package | Parent outcomes | Registry size | Selected action | Cost | Conditioned outcomes | Status |
| --- | --- | --- | ---: | --- | ---: | --- | --- |
| TBD | TBD | TBD | TBD | TBD | TBD | TBD | TBD |

### Policy comparison required to close G4

| Policy | Correctness/coverage target | Expensive-query count | Cost | Runtime | Failure taxonomy |
| --- | --- | ---: | ---: | ---: | --- |
| Fixed uniform refinement | TBD | TBD | TBD | TBD | TBD |
| Uncertainty-width refinement | TBD | TBD | TBD | TBD | TBD |
| Decision-witness-directed | TBD | TBD | TBD | TBD | TBD |

Do not populate these tables from synthetic software fixtures.  G4 closes only
with registered physical undecidable cases and matched policy baselines.
