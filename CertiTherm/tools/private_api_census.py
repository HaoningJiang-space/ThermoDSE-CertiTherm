"""Enumerate every private symbol that crosses a module boundary in this repository.

Why this exists. The planned decomposition moves functions out of `experiments.py` and
`synthesis.py`. Python resolves a function's globals in the module where it was DEFINED, so
moving a symbol silently changes two things that no test failure will announce:

  * `from .experiments import _x` in another module keeps working only if a compatibility
    alias is left behind -- and an alias does NOT restore `monkeypatch.setattr(experiments,
    "_x", ...)`, because the moved caller now looks `_x` up in its new module.
  * a research script that reaches in as `syn._solve_master` is not exercised by the test
    suite at all, so "443 passed" says nothing about whether it still works.

The census is therefore a precondition for moving anything, not documentation of it: every
row is a name whose move needs a decision. Regenerate with

    python -m CertiTherm.tools.private_api_census > experiments/private_api_census.tsv

and diff the result. A row appearing or disappearing is a real change in the coupling
surface, whether or not any test noticed.

Detection is deliberately over-inclusive. It counts both `from <module> import _name` and
attribute access `module._name`, including through the aliases the research tree actually
uses (`syn`, `E`, `S`). Over-inclusion costs a row to dismiss; under-inclusion costs a
silently broken entrypoint.
"""

from __future__ import annotations

import ast
import collections
import pathlib
import subprocess
import sys

# The two modules being decomposed. Everything else is already small enough that its
# private surface is not a refactor hazard.
DECOMPOSED_MODULES = ("experiments", "synthesis")

# How the research tree and tests actually spell these modules when reaching in.
MODULE_ALIASES = {
    "experiments": "experiments",
    "E": "experiments",
    "synthesis": "synthesis",
    "syn": "synthesis",
    "S": "synthesis",
}

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _caller_kind(path: str) -> str:
    """Which of the three coupling classes a caller belongs to.

    The classes differ in what proves them still working: `test` callers are covered by the
    suite, `prod` callers are covered by the suite only indirectly, and `research` callers
    are covered by nothing -- they are the ones a move can break in silence.
    """

    if "/tests/" in path:
        return "test"
    if path.startswith("research/"):
        return "research"
    return "prod"


def collect() -> dict:
    """symbol -> {"module": str, "callers": {path: kind}} for every crossing private name."""

    tracked = subprocess.check_output(
        ["git", "ls-files", "*.py"], text=True, cwd=REPO_ROOT
    ).split()
    found: dict = collections.defaultdict(
        lambda: {"module": "", "callers": {}}
    )
    for relative in tracked:
        if pathlib.Path(relative).stem in DECOMPOSED_MODULES:
            continue
        try:
            tree = ast.parse((REPO_ROOT / relative).read_text(errors="ignore"))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            module = symbols = None
            if isinstance(node, ast.ImportFrom) and node.module:
                tail = node.module.split(".")[-1]
                if tail in DECOMPOSED_MODULES:
                    module = tail
                    symbols = [alias.name for alias in node.names]
            elif isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                module = MODULE_ALIASES.get(node.value.id)
                symbols = [node.attr]
            if module is None:
                continue
            for symbol in symbols:
                if not symbol.startswith("_"):
                    continue
                entry = found[(module, symbol)]
                entry["module"] = module
                entry["callers"][relative] = _caller_kind(relative)
    return found


def main() -> None:
    found = collect()
    out = sys.stdout
    out.write(
        "# Private symbols crossing a module boundary, by (module, symbol).\n"
        "# `callers` counts distinct files; `kinds` says what covers them.\n"
        "# research-only rows are the dangerous ones: the test suite does not exercise them,\n"
        "# so a move can break them without any test failing.\n"
        "#\n"
        "# Regenerate: python -m CertiTherm.tools.private_api_census\n"
        "module\tsymbol\tcallers\tkinds\tfiles\n"
    )
    for (module, symbol), entry in sorted(found.items()):
        kinds = sorted(set(entry["callers"].values()))
        files = ",".join(sorted(entry["callers"]))
        out.write(f"{module}\t{symbol}\t{len(entry['callers'])}\t{'+'.join(kinds)}\t{files}\n")


if __name__ == "__main__":
    main()
