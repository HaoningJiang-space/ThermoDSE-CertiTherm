# Sensitivity to a lumped sink boundary -- which is NOT the one HotSpot uses

> # THE PREMISE OF THIS DOCUMENT WAS FALSE AND EVERY INTERPRETATION IN IT IS CORRECTED.
>
> This file was written as `MODEL_FORM_ISOLATED.md` on the premise that **HotSpot uses a single
> lumped sink-to-ambient resistance**, and it claimed to supersede
> `MODEL_FORM_AGAINST_AN_INDEPENDENT_SOLVER.md` on that basis. **HotSpot does no such thing.**
>
> ```
> temperature_grid.c:1054   /* heatsink is connected to ambient. divide r_convec proportional to cell area */
>                           rz += r_convec * (s_sink * s_sink) / (cw * ch);
> temperature_block.c:207   /* vertical R to ambient: divide r_convec proportional to area */
>                           r_amb = r_convec * (s_sink * s_sink) / area;
> ```
>
> Per-cell resistance scaled inversely with cell area **is** a uniform Robin coefficient
> `h = 1 / (r_convec * s_sink^2)` -- exactly what the FEM adapter already used. Verified at source and
> in algebra: summing the per-cell conductances over the sink top gives `1 / r_convec` regardless of
> discretisation. Neither HotSpot model imposes an isothermal sink top.
>
> **So the distributed-Robin comparison was like-for-like all along, there is no
> "boundary realisation" to remove, and this document supersedes nothing.** What it actually contains
> is a valid and useful measurement of something else: **how much the band would change if the sink
> boundary were lumped.** That is a sensitivity to a boundary condition nobody here uses. The numbers
> below are real; only what they were said to mean was wrong.
>
> Guarded against recurrence in code: `fem_reference.py::_assert_convection_is_distributed` reads
> HotSpot's assembly and refuses if it ever stops dividing `r_convec` by cell area.

MEASUREMENT 2026-08-02, reinterpreted 2026-08-02. Development split, six points, `grid512-avg`
against a DOLFINx FEM whose sink boundary is replaced by a lumped node.

## The construction, which is exact and remains worth having

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

## The measurement

Polytope-wide one-sided band at activity span 0.30. The right-hand column is **the sensitivity to
swapping the boundary condition** -- it was previously and wrongly labelled "boundary realisation",
which implied it was an error sitting inside the distributed-Robin number.

| case | distributed Robin (**the like-for-like comparison**) | lumped node (a BC HotSpot does not use) | sensitivity to the swap |
| --- | --- | --- | --- |
| `arch_a` / resnet50 | **0.7030 K** | 0.3706 K | 0.3324 K |
| `arch_a` / transformer | **1.2748 K** | 0.6039 K | 0.6709 K |
| `arch_b` / resnet50 | **0.6515 K** | 0.0860 K | 0.5655 K |
| `arch_b` / transformer | **1.1220 K** | 0.1168 K | 1.0051 K |
| `arch_c` / resnet50 | **0.2603 K** | 0.0000 K | 0.2603 K |
| `arch_c` / transformer | **0.4583 K** | 0.0000 K | 0.4583 K |

And at the nominal map (`T_FEM - T_grid512`):

| case | distributed (**like-for-like**) | lumped |
| --- | --- | --- |
| `arch_a` / resnet50 | **+0.4356** | +0.1118 |
| `arch_a` / transformer | **+0.8089** | +0.1507 |
| `arch_b` / resnet50 | **+0.5415** | -0.0091 |
| `arch_b` / transformer | **+0.9304** | -0.0486 |
| `arch_c` / resnet50 | **+0.2128** | -0.0598 |
| `arch_c` / transformer | **+0.3795** | -0.1382 |

That the swap column agrees closely with the independently measured sink-top spread is the physics
working as expected: replacing a non-uniform top with an isothermal one removes exactly that spread.
It is a consistency check on the construction, not evidence about HotSpot.

## Two withdrawals this document made, both of which are VOID

**"HotSpot systematically underestimates, one-signed on all six points" -- the withdrawal is void and
the original claim stands.** The like-for-like column is `+0.2128` to `+0.9304 K`, **positive on all
six**. The four-of-six-negative result belongs to the lumped comparison, which is against a boundary
condition HotSpot does not have. The Fetis and Seznec citation is likewise reinstated as independent
corroboration of the direction.

**"Model form is 25-106x the frozen contract and 1.4-11.8x the refinement tail" -- the withdrawal is
void and the original numbers stand.** The `0 - 60x` and `0 - 11.8x` restatement, and the "exactly
zero on two of six" reading, are all properties of the lumped comparison.

## What this document does establish

**The frozen `0.01 K` budget is wrong under either boundary condition.** That was never in dispute
and is the one claim that survived both the withdrawal and its reversal unchanged.

**A lumped sink boundary would change the band by 0.26 - 1.01 K.** That is a real number about model
sensitivity, and it is the right size to matter, so any future comparison against a tool that *does*
lump its sink must construct the boundary to match rather than assume it is a detail.

**It does NOT establish that HotSpot agrees with an independent solver to +-0.15 K.** That figure is
against the wrong boundary-value problem. The like-for-like agreement is `+0.21` to `+0.93 K` at the
nominal map and `0.251 - 1.061 K` over the polytope, owned by
`MODEL_FORM_AGAINST_AN_INDEPENDENT_SOLVER.md`.

## What this document does not touch

The cell-endpoint result (`CELL_ENDPOINT_RESULT.md`) is a HotSpot-internal comparison -- cell rows
against the exact block projection -- and involves no FEM band. `arch_b`/transformer is refused there
by -0.36 K with a cell peak of 330.30 K, above the limit itself, and the `arch_b -> arch_c` switch
with its +32.1 % price is unaffected by anything on this page.

## The lesson, which cost more than the measurement

`r_convec` is *named* like a lumped resistance and is *documented* as sink-to-ambient. Two rounds of
reasoning treated the name as the specification, built an exact lumped-node FEM to separate a term
that does not exist, and withdrew a valid finding on the strength of it. **The check that settled it
was one grep of the assembly.** Read how a coefficient is assembled -- not what it is called, and not
what its comment says it represents. And hold a withdrawal to the same standard as a promotion: name
the premise it rests on, then check that premise against source before publishing the retraction.
