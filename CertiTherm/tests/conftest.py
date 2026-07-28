"""Pytest configuration for the CertiTherm test suite.

Deliberately free of path manipulation. Every remaining test imports through the
`CertiTherm` package from the repository root, so `python -m pytest -q` needs no
`PYTHONPATH` and no `sys.path` insertion.

This file used to prepend `CertiTherm/exact`, `CertiTherm/audit` and
`CertiTherm/robust_dse` to `sys.path` so that six pre-DSOS regression tests could
import their modules by bare name. Those trees and those tests were removed; they
stay reachable in git history under the `legacy-g1-g4-archived` tag.
"""

from __future__ import annotations
