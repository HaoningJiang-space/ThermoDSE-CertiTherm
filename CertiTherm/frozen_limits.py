"""The two frozen DSOS thermal numbers, defined once.

These are the values the method was frozen at. They are NOT the `348 K` / `300 mm^2` defaults
baked into the upstream ThermoDSE submodule's `tools/` and `rl_opt/` CLI flags -- that is a
different and, per `research/reachable_thermal_envelope/G2_BENCHMARK_SPEC.md`, unsupported
convention. Keeping the two apart is the reason this module has a name of its own rather than
living as two floats near the top of whichever file needed them first.

Both were duplicated before this module existed: `experiments.py` held
`THERMAL_LIMIT_K`/`MODEL_ERROR_LIMIT_K` and `gpu_benchmark.py` held its own
`THERMAL_LIMIT_K`/`ERROR_LIMIT_K` with the same values. Two definitions of a frozen constant is
a policing problem, not a check -- a change to one would leave the other silently disagreeing
about what the method was frozen at.

Layer position: leaf. Imports nothing from this package.
"""

from __future__ import annotations

# The registered peak-temperature limit the SAFE/REJECT decision is taken against.
THERMAL_LIMIT_K = 330.0

# The two-sided HotSpot linearization error band from `docs/THERMAL_ERROR_CONTRACT.md`. It is
# folded into every SAFE/REJECT LP one-sidedly: error only ever makes certification harder.
MODEL_ERROR_LIMIT_K = 0.01
