"""Where this repository's fixed inputs live, resolved once from this file's own location.

`ROOT` is the repo root, not a configured value: every path below is derived from it so a clone
in any directory resolves correctly without an environment variable. Two of these -- the HotSpot
binary and the ThermoDSE submodule -- are the only points where this package touches something it
did not build.

The GPU HotSpot build paths deliberately do NOT live here. Tests replace them with
`monkeypatch.setattr(experiments, "GPU_HOTSPOT_BUILD", ...)` to check that the operator cache
signature responds to the GPU configuration, and Python resolves a function's globals in the
module where it was DEFINED -- so moving those names would leave the patch with no effect and the
test asserting a signature built from the real, absent paths. It would go vacuous rather than
fail, which is the worse outcome. They stay in `experiments` until that seam is converted to
explicit configuration.

Layer position: leaf. Imports nothing from this package.
"""

from __future__ import annotations

from pathlib import Path

# `parents[1]` because this file sits at <root>/CertiTherm/paths.py.
ROOT = Path(__file__).resolve().parents[1]

# The HotSpot input template the capture pipeline copies per process. It is committed; the
# ThermoDSE submodule's own `tmp/` template never was, which is why this one exists.
TEMPLATE = ROOT / "CertiTherm" / "evidence" / "thermodse_tmp_template"

# The pinned ThermoDSE submodule, read-only from this package's point of view.
THERMODSE = ROOT / "ThermoDSE"

# The HotSpot binary built by `make bootstrap` from the patched export. Absent in a fresh clone
# until that runs, which is why callers check rather than assume.
HOTSPOT = ROOT / ".build" / "hotspot" / "hotspot"

# Submodules whose cleanliness a claim-grade run asserts before producing evidence.
SUBMODULE_PATHS = ("ThermoDSE", "HotSpot", "Rodinia", "SuperLU")
