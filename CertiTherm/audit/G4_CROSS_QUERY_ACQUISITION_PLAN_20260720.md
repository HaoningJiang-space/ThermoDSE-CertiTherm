# G4 cross-query acquisition repair plan

Date: 2026-07-20  
Repair branch: `round/g4-cross-query-acquisition`  
Parent: `808d00a35e0d26f36008cb8ae1f0df24358bdd36`

## Scope

G4 is an optional extension after a registered G3 architecture query returns
`NON_IDENTIFIABLE`.  It may rank only an explicitly registered family of
obtainable measurements.  Its decision object remains the complete
cross-candidate architecture-selection query; a single-candidate thermal
status is not a G4 result.

The repaired implementation must:

1. replay and bind the input G2/G3 query artifact;
2. require two replay-valid, decision-changing witness tuples;
3. append a measurement equality without deleting any existing equality,
   inequality, or component-bound constraint;
4. condition the complete query at each witness-derived measurement value;
5. accept an action only when both conditioned queries are `CERTIFIED` and
   reproduce their respective, distinct witness outcomes;
6. rank accepted actions only by the registered acquisition cost and a stable
   tie break; and
7. emit a self-authenticating artifact and fresh replay receipt outside Git.

## Claim boundary

The output is a **cheapest registered witness-confirming action**.  It is not a
globally minimum-information policy, and two witness-conditioned solves do not
prove that every possible future measurement value resolves the query.  A
stronger adaptive-policy claim would require a registered outcome partition
and a universal proof over every measurement cell.

## Legacy input disposition

Commit `73a1afd67685bfc96873980f0837a3dfa08cdadb` is treated as a source of an
enumeration idea only.  Its result and executable path are invalid for claims:

- the committed run terminates at a single-candidate `CERTIFIED_SAFE` result;
- the ptrace is truncated/padded from 106 values to a 186-dimensional model;
- the measurement branch overwrites prior `A_eq`/`b_eq` constraints;
- one-direction certification can be reported as a resolution;
- the interposer parser and dictionary attribute writes fail if reached;
- no cross-candidate decision, replay envelope, input manifest, or executed
  test record is present; and
- the commit message names `G4_REPORT.md`, but that file is absent.

Legacy source SHA-256:

- `g4_acquisition.py`: `22a42a4a4605758cde20e276ebd037b49292b031f0063736e101948d6395ad29`
- `g4_acquisition.json`: `5d641b091f7cb3d52cc48e78f8f4701acc8fa3a3cb82589b9c11cbeabeedc3fa`

## Verification boundary

Per user instruction, this repair turn will not execute local or remote tests.
Adversarial tests may be authored, but they must remain explicitly marked
`NOT_EXECUTED`.  Only non-executing static checks are permitted before push.
