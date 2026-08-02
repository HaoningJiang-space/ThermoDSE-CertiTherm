# G-A result: the stepped domain is a build, not a flag — and the existing knob moves the wrong way

RESULT 2026-08-02, on `moe-server` from an isolated worktree at pinned `b55a5b7`, clean, submodules
verified (`HotSpot@f18831e`, `ThermoDSE@51c1506`). GPUs idle, load 3.21 on 52 cores.
NON-CLAIM diagnostic: this gate reads source and probes capability; it computes no temperature.

## What G-A was preregistered to do, and why it could not

`PEAKCERT_OPERATOR_PREREGISTRATION.md` registered G-A as "half a day, and it is the highest-leverage
change available": run the FEM on a **stepped domain** — excluding the space outside each plate
instead of filling it with still air — so the coefficient contrast falls from `1.54e4` (copper against
air) to `~100` (copper against TIM), because max-norm a posteriori constants degrade with the
ellipticity ratio.

**It is not runnable, and the reason is structural rather than a missing option.**

    steady_heat_fem.py:307   if np.any(indices < 0):
                                 raise RuntimeError("mesh cell is not owned by exactly one region")

`_region_indices` refuses any cell not owned by exactly one region, and `_create_domain` always meshes
the **full** box — either `mesh.create_box` over `size_m`, or a structured grid from the node lists.
There is no path by which a cell can be absent. **A domain with a hole is outside the adapter's
contract, not merely unconfigured.**

## The existing knob is not a stand-in, and it moves in the wrong direction

`CERTITHERM_FEM_VOID_K` (default `AIR_K_W_PER_M_K = 0.026`) is documented as the way to drive "the
void towards the adiabatic limit HotSpot actually models". For *physical matching* that is the right
direction. **For the estimator constants it is exactly backwards**: lowering the filler raises the
contrast rather than removing it —

| filler | `k_max / k_min` |
| --- | ---: |
| still air, `0.026` (default) | **1.54e4** |
| `1e-4`, "near-adiabatic" | **4e6** |
| no material at all (stepped) | `400 / 4 = 100`, copper against TIM |

`fem_reference.py` already records the middle row as the reason air was chosen: a `1e-4` filler "would
put a 4e6 contrast ratio into the stiffness matrix for no gain". So the knob cannot approximate the
thing G-A wanted, and using it harder makes the max-norm problem worse.

**This is the tension named in the round plan, now measured rather than predicted:** the direction
that improves the physics degrades the conditioning, and they are the same knob.

## It is constructible, and here is what it costs

`dolfinx 0.11.0` in the pinned environment provides

    dolfinx.mesh.create_submesh(msh, dim, entities) -> (Mesh, EntityMap, EntityMap, ndarray)

so the complement of the void can be extracted as a submesh. That makes a stepped domain reachable —
but it needs a **new adapter**, not a parameter:

1. build the full structured box;
2. mark the void cells rather than assigning them a region;
3. `create_submesh` the complement;
4. re-tag materials, sources, the Robin top and the newly exposed **step faces**, and rebuild every
   form on the submesh;
5. decide and record the boundary condition on the step faces — insulated is the natural reading of
   "no material", and it is a modelling choice that must be registered, not defaulted.

**It must live in this repository.** `steady_heat_fem.py` belongs to the sibling
`/data/ziheng/ThermoDSE` tree (at `403f039`, clean), which the workspace rules make read-only for this
project; the standing instruction is to write a typed adapter rather than edit a foreign source.

## What this changes in the preregistration

**G-A is not half a day and is not a precondition of G-B.** It is a bounded build with a modelling
decision inside it. The gate order registered in `PEAKCERT_OPERATOR_PREREGISTRATION.md` assumed the
stepped domain was a flag away, so the cheap-first ordering it derived from that assumption no longer
holds.

Two ways forward, and they should be chosen deliberately rather than by momentum:

* **Run G-B first, at `1.54e4`.** If a verified two-sided majorant is non-vacuous even at the air
  contrast, the stepped-domain build is unnecessary and G-A is dropped. This is the cheaper
  experiment and it is decisive in the direction that matters: a pass makes the whole question moot.
* **Build the submesh adapter first.** Only worth it if G-B is vacuous at `1.54e4` *and* the failure
  is attributable to the contrast rather than to the re-entrant geometry, source-edge regularity, or
  the barrier construction itself — which the earlier review noted has no theorem either way, because
  the stepped domain trades contrast for re-entrant edges.

**Recommended: G-B first.** The preregistration's own reasoning supports it — G-B is named there as
"the only real kill point", and a kill point should not be gated behind a build whose benefit is
unproven.

## Scope

This gate establishes an adapter capability and a contrast arithmetic. It does **not** establish that
the contrast is what makes a majorant vacuous, that removing it would help, or anything about
temperature. The competing-effects argument against G-A — that a stepped domain degrades elliptic
regularity through re-entrant edges as much as it improves the coefficient ratio — is untouched by
this result and remains the reason G-A cannot be assumed beneficial even once it is buildable.
