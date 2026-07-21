from __future__ import annotations

import numpy as np

from CertiTherm import MeasurementAction, PowerPolytope, ThermalFamily
from CertiTherm.spectral import (
    audit_ranks,
    channel_spectral_leverage,
    spectral_envelope,
)


def test_spectral_tail_is_certified_in_peak_norm() -> None:
    power = PowerPolytope.box_with_total(np.zeros(2), np.ones(2), 1.0)
    thermal = ThermalFamily(
        ("model",),
        np.array([[[3.0, 0.0], [0.0, 1.0]]]),
        np.array([0.0]),
        10.0,
    )
    spectrum, records = spectral_envelope(power, thermal, ranks=(0, 1, 2))
    assert records[0] == (0, 0.0, 3.0)
    assert np.isclose(records[1][1], 0.9)
    assert np.isclose(records[1][2], 1.0)
    assert records[2][1] == 1.0
    assert records[2][2] < 1e-12
    action = MeasurementAction("dominant", np.array([1.0, 0.0]))
    assert np.isclose(channel_spectral_leverage(action, spectrum), 0.9)


def test_spectral_rank_grid_includes_full_operator() -> None:
    assert audit_ranks(9) == (0, 1, 2, 4, 8, 9)
