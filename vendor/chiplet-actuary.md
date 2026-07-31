# Provenance: Chiplet Actuary cost model

Recorded before reuse, per the workspace rule that a copied model carries source, commit, path,
licence, reuse mode, semantic delta, tests and release status.

| field | value |
| --- | --- |
| source | `https://github.com/Yinxiao-Feng/chiplet-actuary` |
| commit | `42dd5de` ("fix os NRE cost"), fetched 2026-08-01 |
| paper | Feng and Ma, *Chiplet Actuary: A Quantitative Cost Model and Multi-Chiplet Architecture Exploration*, DAC 2022, arXiv:2203.12268 |
| licence | MIT, Copyright (c) 2024 Yinxiao Feng |
| files read | `chiplet_actuary/chip.py`, `chiplet_actuary/package.py`, `chiplet_actuary/spec.py`, `exploration.py`, `parameter.ini` |
| reuse mode | **clean-room transcription, nothing vendored.** No file is copied into this tree. `research/triangle/robustness/chiplet_cost.py` re-implements the organic-substrate recurring-cost path from the equations, with each constant traced to its `parameter.ini` key. |
| release status | public, MIT, released |

## Semantic delta — what this project's transcription does differently

* **Recurring cost only.** `NRE` is excluded. It is non-recurring and amortised over a production
  volume this project does not have, so including it would make every comparison depend on an
  unstated number. This is a scope choice, not an omitted count-dependent recurring term.
* **Organic substrate only.** The `FO` and `SI` (interposer) packages, the `chip_last` variants and
  the heterogeneous-node paths are not transcribed. Every design compared here is a single-node
  2.5D organic-substrate part, which is the case ThermoDSE's registry describes.
* **No module/chiplet decomposition.** The upstream model composes a chip from `Module` objects
  with D2D PHY area; here the die areas come from ThermoDSE's own floorplan
  (`die_h_list_m` x `die_w_list_m`, recorded per capture), so the D2D overhead is already inside
  the geometry rather than added as a separate module.
* **Every parameter is an argument.** Upstream reads a global `spec` module; the transcription
  takes each factor as a keyword so the sensitivity sweep can move one at a time. The defaults are
  the upstream `parameter.ini` values for the 14 nm node and the `OS` package.

## Why the yield models are comparable at all

Both use the same negative-binomial family with the same 14 nm parameters:
`Y(A) = (1 + D0 A / alpha)^(-alpha)`, `D0 = 0.08 cm^-2`, `alpha = 10` -- upstream at
`exploration.py:51` and `chip.py:46-48`, ThermoDSE at `core/gen_hw_setting.py:61-67`. The two
differ in **composition across dies**, not in the per-die model, which is what makes the
comparison in `docs/DECISION_SUFFICIENT_INSTRUMENTATION.md` a like-for-like one.

## Tests

`CertiTherm/tests/test_chiplet_cost.py` pins the transcription: the wafer-utilisation term against
a hand-computed gross-die count, the monotonicity of each count-dependent term, and the refusal
paths. The upstream repository is not a test dependency and is not required to run this tree.
