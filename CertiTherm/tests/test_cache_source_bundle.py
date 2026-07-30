"""A cache receipt must be bound to every module whose behaviour it executes.

The failure this guards is a false cache HIT: an operator or capture reused although the logic
that built or validated it has changed. Downstream results would then be internally consistent
while corresponding to the wrong thermal operator, which is worse than a crash because it can
enter claim-grade evidence unnoticed.

Peer review found a live instance of exactly that. When the TSV writer moved out of
`experiments.py` into `tabular.py`, both source bundles still named only `experiments.py` and
`digest.py`, so a change to how receipts are written and read would have left `builder_sha256`
untouched. These tests exist so the next extraction cannot repeat it silently.
"""

from __future__ import annotations

from typing import Sequence

import pytest

from CertiTherm import experiments

# The modules a cache receipt EXECUTES, as opposed to merely importing. digest.py does the
# hashing; tabular.py writes the receipt row and reads it back for validation. Both must appear
# in every bundle, or a change to hashing or to the column rule leaves the builder digest fixed.
_EXECUTED_BY_EVERY_RECEIPT = ("CertiTherm/digest.py", "CertiTherm/tabular.py")

_ARCH = {"architecture_id": "arch_a", "chiplet_x": "2", "chiplet_y": "2", "cut_x": "1", "cut_y": "1"}
_WORKLOAD = {"workload_id": "resnet50"}
_PACKAGE = {"package_id": "default"}


def _bundle_paths(source: str) -> Sequence[str]:
    """The literal path tuple a signature builder passes to `_source_bundle_sha256`.

    Read out of the source rather than from a call, because the point is to check the LIST the
    module declares -- calling the builder would only tell us what it hashed, not what it forgot.
    """

    import ast
    import inspect

    tree = ast.parse(inspect.getsource(getattr(experiments, source)))
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "_source_bundle_sha256"
        ):
            return [
                element.value
                for element in node.args[0].elts
                if isinstance(element, ast.Constant)
            ]
    raise AssertionError(f"{source} does not call _source_bundle_sha256")


@pytest.mark.parametrize(
    "builder", ["_capture_cache_signature", "_operator_cache_signature"]
)
def test_every_receipt_binds_the_modules_it_executes(builder: str) -> None:
    """Membership, not behaviour: this is the assertion that would have caught the omission."""

    declared = _bundle_paths(builder)
    assert declared, f"{builder} declared an empty bundle"
    missing = [path for path in _EXECUTED_BY_EVERY_RECEIPT if path not in declared]
    assert not missing, (
        f"{builder} does not bind {missing}; a change there would leave builder_sha256 fixed and "
        "a cache written under the old logic would be accepted under the new one"
    )
    assert "CertiTherm/experiments.py" in declared


@pytest.mark.parametrize(
    "builder", ["_capture_cache_signature", "_operator_cache_signature"]
)
def test_substituting_any_listed_module_changes_the_builder_digest(
    builder: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Every listed path must actually reach the digest, one path at a time.

    A path that is listed but never hashed would satisfy the membership test above while binding
    nothing, so each one is substituted individually and the digest must move. `_sha256` is
    patched on `experiments` because `_source_bundle_sha256` still resolves it there.
    """

    declared = list(_bundle_paths(builder))

    def _sha_with(swapped: str = "") -> str:
        def fake(path):
            name = str(path)
            return ("b" if swapped and name.endswith(swapped) else "a") * 64

        monkeypatch.setattr(experiments, "_sha256", fake)
        return experiments._source_bundle_sha256(declared)

    baseline = _sha_with()
    for path in declared:
        assert _sha_with(path) != baseline, (
            f"{builder} lists {path} but substituting it did not change builder_sha256, so the "
            "receipt is not bound to it"
        )


def test_the_two_bundles_are_not_accidentally_the_same_list() -> None:
    """Non-vacuity: if both builders shared one list, the parametrised tests would test one thing.

    The operator receipt binds the operator construction path -- core, hotspot, gpu_hotspot,
    measurements -- which the capture receipt has no business depending on.
    """

    capture = set(_bundle_paths("_capture_cache_signature"))
    operator = set(_bundle_paths("_operator_cache_signature"))
    assert capture < operator, (
        "the operator bundle must strictly contain the capture bundle's shared modules plus its "
        f"own construction path; capture={sorted(capture)} operator={sorted(operator)}"
    )
    assert "CertiTherm/hotspot.py" in operator - capture
