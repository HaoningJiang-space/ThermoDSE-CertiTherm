"""Which registry rows a split evaluates, and what protocol state it was frozen under.

A split name in this project carries three separate facts that used to be looked up from three
tables scattered near the bottom of `experiments.py`: which physical registry rows it reads,
whether its results are preregistered and therefore off-limits for tuning, and which freeze ID
its endpoints were declared under. They are listed together so a split added to the CLI cannot
quietly miss one of the three -- an unnamed split falls through to `UNREGISTERED`, which the
report prints rather than hides.

Layer position: leaf. Imports nothing from this package.
"""

from __future__ import annotations

from typing import Tuple

# Splits that may be inspected, tuned against and re-run freely.
DEVELOPMENT_SPLITS: Tuple[str, ...] = ("dev", "dev_v3")

# Splits whose results are preregistered and must never be used for tuning. `heldout` is
# method-freeze-v1's split; `heldout_v2` is method-freeze-v2's, registered in
# experiments/architectures.tsv and disjoint from both dev and v1. They are listed together so a
# future split cannot be added to the CLI without also being recognised as frozen here.
HELDOUT_SPLITS: Tuple[str, ...] = ("heldout", "heldout_v2", "heldout_v3")

# Held-out splits already spent: their endpoints have been read, so a further run cannot be
# claim-grade for the same freeze.
BURNED_SPLITS = frozenset({"heldout_v2"})

# Splits that may only be run under `--frozen`.
FROZEN_ONLY_SPLITS = frozenset({"heldout_v3"})

# Splits where `--frozen` is accepted but not required.
FROZEN_ENABLED_SPLITS = frozenset({"heldout"})

# Splits evaluated by the anytime controller rather than the v1 exact driver.
ANYTIME_SPLITS = frozenset({"dev", "dev_v3", "heldout_v2", "heldout_v3"})

# The tables are public as well as the accessors: tests assert membership directly
# (`"dev_v3" in ANYTIME_SPLITS`, `FREEZE_ID["dev_v3"] == ...`), while the accessors below add the
# UNREGISTERED default that a report must print rather than hide.

# Method profiles that read another split's physical registry rows.
REGISTRY_SPLITS = {"dev_v3": "dev"}

PROTOCOL_STATE = {
    "dev": "DEVELOPMENT",
    "dev_v3": "DEVELOPMENT_REHEARSAL",
    "heldout": "FROZEN_HELDOUT",
    "heldout_v2": "BURNED_HELDOUT",
    "heldout_v3": "FROZEN_HELDOUT",
}

# An artifact table is only meaningful if it names the protocol whose preregistered endpoints it
# was produced under.
FREEZE_ID = {
    "dev": "method-freeze-v1",
    "dev_v3": "method-freeze-v3.1",
    "heldout": "method-freeze-v1",
    "heldout_v2": "method-freeze-v2.1",
    "heldout_v3": "method-freeze-v3.1",
}


def registry_split(split: str) -> str:
    """Map a method profile to the physical registry rows it evaluates."""

    return REGISTRY_SPLITS.get(split, split)


def protocol_state(split: str) -> str:
    """The protocol state to stamp on this split's artifacts, or UNREGISTERED."""

    return PROTOCOL_STATE.get(split, "UNREGISTERED")


def freeze_id(split: str) -> str:
    """The freeze ID this split's endpoints were declared under, or UNREGISTERED."""

    return FREEZE_ID.get(split, "UNREGISTERED")


def _known_splits() -> frozenset:
    """Every split any table in this module names."""

    return frozenset(DEVELOPMENT_SPLITS) | frozenset(HELDOUT_SPLITS)


# Checked at import, not at first use. A split registered in two of the three tables and missing
# from the third would otherwise report a real protocol state next to an UNREGISTERED freeze ID,
# and the artifact would carry a contradiction rather than an obvious gap. The tables are the
# whole content of this module, so the check costs nothing and cannot go stale.
_declared = _known_splits()
for _name, _table in (("PROTOCOL_STATE", PROTOCOL_STATE), ("FREEZE_ID", FREEZE_ID)):
    _missing = _declared - set(_table)
    _extra = set(_table) - _declared
    if _missing or _extra:
        raise AssertionError(
            f"{_name} disagrees with the declared splits: missing {sorted(_missing)}, "
            f"unexpected {sorted(_extra)}"
        )
if set(REGISTRY_SPLITS) - _declared:
    raise AssertionError(
        f"REGISTRY_SPLITS maps undeclared splits: {sorted(set(REGISTRY_SPLITS) - _declared)}"
    )
for _group in (BURNED_SPLITS, FROZEN_ONLY_SPLITS, FROZEN_ENABLED_SPLITS, ANYTIME_SPLITS):
    if _group - _declared:
        raise AssertionError(f"a split set names undeclared splits: {sorted(_group - _declared)}")
del _declared, _name, _table, _missing, _extra, _group
