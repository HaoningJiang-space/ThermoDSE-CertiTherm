# Robustness probes

Two generations live here and they are not interchangeable.

## Current — parameterised, documented, reproducible

| file | what it produces |
| --- | --- |
| `l1_body.py` | the exact L1 relocation body: reachability by lifted LP, and the radius in closed form |
| `threshold.py` | the instrumentation tier as a function of the uncertainty radius, per geometry |
| `yield_composition.py` | the three yield compositions from recorded die geometry, and the bonding phase boundary |
| `architecture_sweep.py` | fresh architecture points and their radii, over three declared grids |
| `relocation_radii.py` | adds the exact relocation radius to a sweep captured before it existed |

Each takes its artifact root and options on the command line, states its usage in its docstring, and
is exercised by tests under `CertiTherm/tests/`.

## Superseded — kept for provenance, not for reuse

`sstar.py`, `taustar.py`, `regret.py`, `yieldprice.py` produced numbers quoted in
`docs/THERMAL_ROBUSTNESS_RADII.md`. They **hardcode an absolute path** to one scratch directory on
one execution host and take no arguments, so they cannot be re-run anywhere else. They are retained
only because deleting the sole implementation behind a published number is the provenance hole this
project closed for `radius_l1`, not because they are a reproduction path. Anything built on them
should be rewritten in the current style first.

`attr.py`, `edyp.py`, `reachcheck.py`, `transition.py` were **deleted on 2026-07-31**. They shared
the hardcoded path and had no docstring, usage line or CLI, and their capability is now covered:
`reachcheck` and `transition` both maximised `r . p - floor` over a polytope's reject cells, which
`threshold.reject_reachable` and `l1_body` do properly and with the geometry named; `attr` measured
the class-aggregate attribution, whose corrected conclusion is recorded in the radii document; `edyp`
printed the EDYP domination table, which is in the same document and which
`yield_composition.py` now derives from geometry instead of from a composed scalar. Their findings
stay in `docs/`; only the unrunnable scripts are gone.
