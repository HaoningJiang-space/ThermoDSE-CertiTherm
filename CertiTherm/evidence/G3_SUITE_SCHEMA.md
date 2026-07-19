# Registered G3 Suite Contract

Schema: `certitherm.g3-suite.v1`

The G3 suite has two workload-family × package-regime query strata. The
architecture dimension lives inside every query: each query must contain the
same candidate IDs and cover every registered architecture family. This avoids
mislabeling eight independent candidate checks as eight architecture decisions.

## Suite fields

- `suite_id`: stable non-empty identity;
- `evidence_class`: exactly `physical_placed_power`;
- `workload_families`: at least two unique identities;
- `architecture_families`: at least two unique identities;
- `package_regimes`: at least two unique identities;
- `queries`: exactly one entry for every workload-family × package pair;
- each query entry: `workload_family`, `workload_id`, `package_id`, and a
  bundle-relative `query_spec` path.

Each query spec retains schema `certitherm.g2-query-spec.v2` and must contain a
complete candidate pool. In addition to the G2 files, every candidate record
must bind:

- `point_power_npy`;
- `point_power_semantics: original_thermodse_point_estimate`;
- `placed_power_npy`.

Each observation provenance record must add:

- `architecture_family`;
- `thermal_operator_sha256`, equal to the candidate `response_npy` digest;
- `placed_power_sha256`, equal to the candidate `placed_power_npy` digest.

The existing physical provenance fields remain mandatory. In particular,
`workload_id`, `workload_family`, `architecture_id`, `package_id`,
`power_source_sha256`, `placement_sha256`, and `thermal_config_sha256` must be
present.

## Fail-closed checks

The loader rejects:

- missing or duplicate Cartesian strata;
- different candidate pools across strata;
- workload or package labels that disagree with candidate provenance;
- a point or placed vector outside the spatial observation domain;
- one placed/point vector reused under multiple workload labels;
- one response/config digest reused under multiple package labels;
- architecture identity, family, `sys_info`, or placement changes across
  strata;
- nonthermal order changes across packages;
- different thermal limits across strata.

## Output semantics

For each workload/package stratum the runner emits three replayable
architecture-query artifacts:

1. `point_estimate`: every component is fixed to the original DSE point;
2. `placed_reference`: every component is fixed to the registered placed map;
3. `spatial_equivalence`: the observation-equivalent spatial domain.

Permitted comparison names are `point_commitment_not_identifiable` and
`point_placed_disagreement`. Neither is automatically an error rate. Raw suite
artifacts and receipts must be written outside the Git worktree.

The synthetic fixtures in `tests/test_g3_evidence.py` document the file shape
but are software tests only, never paper evidence.
