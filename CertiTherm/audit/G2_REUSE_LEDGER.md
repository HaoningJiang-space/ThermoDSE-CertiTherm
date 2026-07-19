# G2 Correction Reuse Ledger

| Source | Exact commit | Source paths | Ownership / license observation | Reuse mode | Destination | Semantic delta |
| --- | --- | --- | --- | --- | --- | --- |
| sibling `ChipletThermalEnvelope` G1 semantics worktree | `557bbb43e0ac447db879e3dd739b43d768f844d6` | `src/rte/identifiability.py`, `tests/test_identifiability.py` | no repository-root license observed | read-only semantic reference; no source copied | `CertiTherm/exact/decision_query.py`, adversarial tests | clean-room floating-point operational query with the frozen three-state semantics; exact-rational certificates remain sibling-only |
| ThermoDSE-CertiTherm intermediate LP | `62995b5073495f04dafdaf4bfa48ae9ac848ad5d` | `CertiTherm/exact/decide.py` | same repository | corrected/replaced | `CertiTherm/exact/linear_oracle.py` | preserves the epigraph min-max formulation, adds nonzero lower bounds, explicit observations/inequalities, validation, and fail-closed direct replay |
| ThermoDSE-CertiTherm measurement prototype | `7ce27a11e8c007f01d66a7627413bb456bdb2bca` | `CertiTherm/exact/measurement.py`, `g3_final.py` | same repository | repaired dependency and invalidated result claims | shared `linear_oracle.py`; legacy report headers | removes duplicated max-min solver; does not authorize a G3/G4 claim |
| sibling `ChipletThermalEnvelope` placed-power evidence | `d4e519d280dea5d9f4c1e92789a2e461f7efffd0` | registered placed-power domains, native HotSpot Green matrices, independent oracle bounds, continuous-frontier witnesses | no repository-root license observed | read-only content-hash and numeric evidence import; no source copied | `g2_placed_power_registry.json`, physical replay runner, corrected G2 report | re-solves the rectangular LP in CertiTherm, checks independent bound parity, and directly replays both certified and decision-changing queries |

The sibling implementation's frozen six-variable/forty-inequality exact
resource contract is not mixed with this scalable floating-point path. Exact
G1 evidence must retain its own source commit and manifest digest.
