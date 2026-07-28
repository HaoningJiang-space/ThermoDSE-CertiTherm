"""The ONE copy of the V6.1 evidence contract, imported by both producer and consumer.

Before this module the driver and the renderer each carried their own `classify()` and
`subset_tag()`. They happened to agree, but nothing enforced it -- and the one place they did
NOT agree was the gate, where the driver decided a crossing with a bare `periodic >= limit`
while classification requires `>= limit + quantum`, so a row at exactly the limit could pass a
gate that calls it undecidable. A rule that decides evidence has to exist once.

Holds: the fail-closed error type, the quantisation-aware classification, subset tagging, and
the pinned-registration loader with its citation check.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Iterable, Sequence

# The single source of the output quantum: HotSpot's own serialisation limit, defined next to
# the convergence guard that also depends on it.
from CertiTherm.transient import OUTPUT_RESOLUTION_K  # noqa: F401  (re-exported)

ROOT = Path(__file__).resolve().parents[2]
# `V61_REGISTRATION` exists so a SYNTHETIC manifest can be rendered in a subprocess against the
# synthetic registration it describes. Gate policy 3 binds the physical instance, so the
# committed registration only validates the real 233-block run; monkeypatching cannot reach a
# subprocess. Never set it for a claim-grade render.
REGISTRATION = Path(os.environ.get("V61_REGISTRATION")
                    or ROOT / "docs/registration/v61_grid64_counterexample.json")


class Refuse(Exception):
    """Any inconsistency, missing evidence, or unmet precondition. Never rendered around."""


def require(cond: bool, msg: str) -> None:
    if not cond:
        raise Refuse(msg)


def get(d: dict, key: str, where: str):
    """Fetch a required field as a Refuse, not a KeyError -- a traceback is not fail-closed."""
    require(key in d, f"{where}: required field `{key}` is missing")
    return d[key]


def finite(value, where: str) -> float:
    require(isinstance(value, (int, float)) and not isinstance(value, bool)
            and value == value and abs(value) != float("inf"),
            f"{where} is not a finite number ({value!r})")
    return float(value)


def rel(path: Path) -> str:
    """Repo-relative when inside the tree, absolute otherwise.

    `Path.relative_to` RAISES for a path outside ROOT, and it was called from inside refusal
    messages -- so a refusal about a misplaced file died with a ValueError instead of printing.
    An error path must never be able to raise.
    """
    try:
        return str(Path(path).resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def positional_script_argument(index: int, default, cast=str, *, module_name: str):
    """Read `sys.argv[index]`, but ONLY when the calling module is the script being run.

    Reading `sys.argv` at module level makes a module unsafe to import: the importer's own
    command line gets reinterpreted as this module's arguments. That has bitten twice.
    `complete_trace_probe` died with "could not convert string to float: 'transformer'" when
    the factorial driver imported it. `v61_frozen_factorial` had the same defect and silently
    bound its model id to "CertiTherm/tests" under `pytest -q CertiTherm/tests`; one extra
    pytest flag turned that into a ValueError that broke collection of the WHOLE suite.

    Pass `module_name=__name__` from the caller: only the module Python is executing as
    `__main__` owns the command line.
    """
    if module_name != "__main__" or len(sys.argv) <= index:
        return default
    return cast(sys.argv[index])


def subset_tag(components: Iterable[str], all_components: Sequence[str]) -> str:
    """`full` for the grand coalition, otherwise the alphabetical `-`-joined member list."""
    return "full" if set(components) == set(all_components) else "-".join(sorted(components))


def classify(periodic_k: float, limit_k: float, quantum_k: float) -> str:
    """Strictly outside the two-sided quantum band, or INDETERMINATE.

    At a 330.0 K limit and a 0.01 K quantum: >= 330.01 crosses, <= 329.99 is below, and
    exactly 330.00 is undecidable and must never be counted as a crossing.
    """
    if periodic_k >= limit_k + quantum_k:
        return "crossing"
    if periodic_k <= limit_k - quantum_k:
        return "below"
    return "indeterminate"


def load_registration(path: Path = None) -> dict:
    path = Path(path) if path is not None else REGISTRATION
    require(path.is_file(), f"pinned registration {rel(path)} is missing")
    return json.loads(path.read_text(encoding="utf-8"))


def check_citation(cite: dict, values: Iterable) -> None:
    """A pinned document:line must still contain the values recorded beside it.

    Line numbers drift the moment the cited document is edited -- this record was wrong within
    an hour of being written, because adding a correction paragraph above the cited table
    shifted it by one. A wrong citation prints silently, so it has to be a refusal.
    """
    path = ROOT / get(cite, "document", "citation")
    require(path.is_file(), f"cited document {cite['document']} is missing")
    lines = path.read_text(encoding="utf-8").splitlines()
    n = get(cite, "line", "citation")
    require(1 <= n <= len(lines),
            f"{cite['document']}:{n} is past the end of a {len(lines)}-line file")
    line = lines[n - 1]
    for v in values:
        require(str(v) in line,
                f"{cite['document']}:{n} no longer contains {v!r}; the pinned citation in "
                f"{rel(REGISTRATION)} is stale")
