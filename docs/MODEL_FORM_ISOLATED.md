# Model form, with the boundary realisation removed: HotSpot largely agrees

RESULT 2026-08-02. Development split, six points, `grid512-avg` against a DOLFINx FEM whose sink
boundary is HotSpot's **lumped** node rather than a distributed Robin coefficient.

This supersedes the headline in `MODEL_FORM_AGAINST_AN_INDEPENDENT_SOLVER.md`. That comparison used a
uniform Robin coefficient over the sink top; HotSpot uses a single lumped sink-to-ambient resistance.
The two are different boundary-value problems, and the difference was inside every number reported as
"model form".

## The exact construction, which needs no new boundary condition

Every face except the top is adiabatic -- verified, not assumed: `bottom_heat_transfer = 0.0`, and
the weak form carries boundary terms only on `ds(1)` (top) and `ds(2)` (bottom), so the sides have no
`ds` term at all and take the natural zero-flux condition. In a problem with one Dirichlet plane and
everything else insulated, **changing that plane's value shifts the solution rigidly**. So:

1. pin the top at ambient (`h = 1e7`, Robin degenerating to Dirichlet) and solve once;
2. all heat leaves through the top, so the total flux is exactly the dissipated power `P`;
3. the lumped relation `Q = (T_s - T_inf) / r` gives `T_s = T_inf + r P`;
4. the lumped solution is the pinned field plus `r P`.

`r P` is **linear in `p`**, so it belongs in the response and not the ambient: the zero-power row is
unchanged and every response entry gains exactly `r_convec`, each impulse being one watt. Putting it
on the ambient instead would have made the operator depend on the nominal map and stop being affine.

One solve, exact, and `h` is a **surface** coefficient rather than a volume contrast -- which is why
this is well conditioned where scaling the sink conductivity was not (that route drove the material
contrast to 1e6-1e7, lost the energy balance, and could not be rescued by refining the mesh because
the obstruction is coercivity).

## The result

Polytope-wide one-sided band at activity span 0.30:

| case | distributed Robin | **lumped node** | boundary realisation |
| --- | --- | --- | --- |
| `arch_a` / resnet50 | 0.7030 K | **0.3706 K** | 0.3324 K |
| `arch_a` / transformer | 1.2748 K | **0.6039 K** | 0.6709 K |
| `arch_b` / resnet50 | 0.6515 K | **0.0860 K** | 0.5655 K |
| `arch_b` / transformer | 1.1220 K | **0.1168 K** | 1.0051 K |
| `arch_c` / resnet50 | 0.2603 K | **0.0000 K** | 0.2603 K |
| `arch_c` / transformer | 0.4583 K | **0.0000 K** | 0.4583 K |

**The boundary realisation was 47 - 100 % of what was reported as model form.** It is a property of
the comparison adapter, not of HotSpot.

And the sign, at the nominal map (`T_FEM - T_grid512`):

| case | distributed | lumped |
| --- | --- | --- |
| `arch_a` / resnet50 | +0.4356 | +0.1118 |
| `arch_a` / transformer | +0.8089 | +0.1507 |
| `arch_b` / resnet50 | +0.5415 | **-0.0091** |
| `arch_b` / transformer | +0.9304 | **-0.0486** |
| `arch_c` / resnet50 | +0.2128 | **-0.0598** |
| `arch_c` / transformer | +0.3795 | **-0.1382** |

## What is withdrawn

**"HotSpot systematically underestimates, one-signed on all six points."** Withdrawn. With the
boundary matched, **four of six are negative** and the residual is **+-0.15 K** at the nominal map.
The one-signed behaviour was the adapter's distributed Robin against HotSpot's lumped node. The
citation of Fetis and Seznec as independent corroboration goes with it: their finding may hold, but
nothing here supports it.

**"Model form is 25-106x the frozen contract and 1.4-11.8x the refinement tail."** Restated:
**0 - 60x** the contract and **0 - 11.8x** the tail, and on two of six points the model-form band is
**exactly zero**.

## What survives, and it is the more useful statement

**The frozen `0.01 K` budget is still wrong.** Even with the boundary matched, the polytope-wide band
reaches 0.604 K -- sixty times a contract that covers only linearisation. That was the original
finding and it stands.

**And HotSpot comes out well.** Once the boundary condition is matched, `grid512-avg` agrees with an
independent three-dimensional finite-element solve to **+-0.15 K at the nominal map and 0 - 0.60 K
over the whole power polytope**. That is a validation result, not a criticism, and it makes the
certificate's budget far tighter than the earlier comparison suggested.

## What this does not touch

The cell-endpoint result (`CELL_ENDPOINT_RESULT.md`) is a HotSpot-internal comparison -- cell rows
against the exact block projection -- and involves no FEM band. `arch_b`/transformer is refused there
by -0.36 K with a cell peak of 330.30 K, above the limit itself, and the `arch_b -> arch_c` switch
with its +32.1 % price is unaffected by anything on this page.
