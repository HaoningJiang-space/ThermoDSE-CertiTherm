"""Pytest path configuration for CertiTherm tests.

Allows `python3 -m pytest -q` from the repository root without a manual
PYTHONPATH, per the post-closure integrity audit repair requirement.
"""

from __future__ import annotations

from pathlib import Path
import sys


_CERTITHERM = Path(__file__).resolve().parents[1]
for _sub in ("exact", "audit", "robust_dse"):
    _path = str(_CERTITHERM / _sub)
    if _path not in sys.path:
        sys.path.insert(0, _path)
