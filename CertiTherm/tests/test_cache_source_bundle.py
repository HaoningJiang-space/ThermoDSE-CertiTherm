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
_EXECUTED_BY_EVERY_RECEIPT = (
    "CertiTherm/cache_receipts.py",
    "CertiTherm/digest.py",
    "CertiTherm/tabular.py",
)

# Modules only ONE builder executes. The capture's content comes from the bridge over the paths
# leaf; the operator's comes from the HotSpot construction path. Listing them per builder keeps
# the check specific -- a blanket "every module" rule would force an expensive rebuild of every
# cached capture on an unrelated edit.
_EXECUTED_PER_BUILDER = {
    "_capture_cache_signature": (
        "CertiTherm/paths.py",
        "CertiTherm/thermodse_bridge.py",
    ),
    "_operator_cache_signature": (
        "CertiTherm/core.py",
        "CertiTherm/hotspot.py",
        "CertiTherm/measurements.py",
    ),
}

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
    own = [path for path in _EXECUTED_PER_BUILDER[builder] if path not in declared]
    assert not own, f"{builder} does not bind its own construction path: {own}"


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


def test_the_two_bundles_differ_by_exactly_their_own_construction_paths() -> None:
    """Non-vacuity: if both builders shared one list, the parametrised tests would test one thing.

    They are NOT nested. An earlier version of this test asserted the operator bundle strictly
    contained the capture bundle, which stopped being true once the ThermoDSE bridge moved out --
    the capture's content comes from the bridge, which the operator has no business binding. What
    must hold is that each bundle names its own path and not the other's.
    """

    capture = set(_bundle_paths("_capture_cache_signature"))
    operator = set(_bundle_paths("_operator_cache_signature"))
    shared = {"CertiTherm/experiments.py", "CertiTherm/digest.py", "CertiTherm/tabular.py",
              "CertiTherm/cache_receipts.py", "CertiTherm/paths.py", "requirements.lock"}
    assert shared <= capture and shared <= operator
    assert "CertiTherm/thermodse_bridge.py" in capture - operator
    assert "CertiTherm/hotspot.py" in operator - capture


class _SeamObserved(Exception):
    """A sentinel no production path raises, so reaching it proves the injection took effect."""


@pytest.mark.parametrize(
    "call",
    [
        "_source_bundle_sha256",
        "_write_cache_receipt",
        "_cache_receipt_matches",
    ],
)
def test_patching_the_driver_still_reaches_the_moved_implementation(
    call: str, tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The wrappers exist for exactly this, and prose is not evidence that they work.

    The receipt implementations moved to `cache_receipts`, which resolves `sha256_file` from its
    argument rather than from a module global. Had `experiments` re-exported the functions instead
    of wrapping them, `monkeypatch.setattr(experiments, "_sha256", ...)` would have stopped
    affecting them -- and because the real files exist, the affected tests would have gone VACUOUS
    rather than failed. So the seam is checked by an exception no production path can raise.
    """

    def exploding(_path):
        raise _SeamObserved(call)

    monkeypatch.setattr(experiments, "_sha256", exploding)
    artifact = tmp_path / "artifact.npz"
    artifact.write_bytes(b"payload")
    signature = {"kind": "t", "builder_sha256": "a" * 64, "input_sha256": "b" * 64}

    with pytest.raises(_SeamObserved):
        if call == "_source_bundle_sha256":
            experiments._source_bundle_sha256(("requirements.lock",))
        elif call == "_write_cache_receipt":
            experiments._write_cache_receipt(artifact, signature)
        else:
            # `receipt_matches` returns False before hashing if the receipt is absent, so one is
            # written with the real digest first; otherwise this test would pass on the early exit
            # and prove nothing about the seam.
            monkeypatch.undo()
            experiments._write_cache_receipt(artifact, signature)
            monkeypatch.setattr(experiments, "_sha256", exploding)
            experiments._cache_receipt_matches(artifact, signature)


def test_the_root_the_bundle_resolves_against_is_also_patchable(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """`ROOT` moved to the `paths` leaf, so the wrapper must read the driver's copy, not the leaf's."""

    (tmp_path / "requirements.lock").write_text("pinned\n", encoding="utf-8")
    monkeypatch.setattr(experiments, "ROOT", tmp_path)
    against_fixture = experiments._source_bundle_sha256(("requirements.lock",))

    monkeypatch.undo()
    against_repo = experiments._source_bundle_sha256(("requirements.lock",))
    assert against_fixture != against_repo, (
        "patching experiments.ROOT did not change which file the bundle hashed, so the wrapper is "
        "resolving ROOT somewhere the tests cannot reach"
    )
