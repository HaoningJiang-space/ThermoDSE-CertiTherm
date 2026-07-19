# G4 optional acquisition extension: current status

Status: **implementation authored but unexecuted; no claim-grade G4 result**
Date: 2026-07-20

The previously pushed G4 pilot at commit
`73a1afd67685bfc96873980f0837a3dfa08cdadb` is
`LEGACY_INVALIDATED_FOR_CLAIMS`.  Its committed JSON reports only that one
single-candidate problem was already `CERTIFIED_SAFE`; it does not demonstrate
measurement-driven resolution of a `NON_IDENTIFIABLE` architecture query.

The repaired G4 contract is narrower and decision-level:

> Given a replay-valid `NON_IDENTIFIABLE` architecture query, its two
> decision-changing witness tuples, and a content-bound registry of obtainable
> measurement actions with declared costs, find the cheapest registered action
> whose two witness-conditioned **complete architecture queries** are both
> certified and reproduce the two distinct witness outcomes.

This establishes witness-pair confirmation for a registered action.  It does
not establish global policy optimality or resolution for every possible
measurement value.

The cross-query implementation and adversarial tests now exist on
`round/g4-cross-query-acquisition`, but they were deliberately not executed in
this repair turn. No numerical G4 result is currently permitted in the paper. Promotion
requires a clean-tree run on a registered, non-identifiable G3 spatial query,
an external artifact, a passing fresh replay receipt, full-dimensional physical
inputs, and an executed test record.
