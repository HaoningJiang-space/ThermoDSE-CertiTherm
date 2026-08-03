"""The library must reuse EXACTLY or not at all; a near-hit is the failure mode that enters evidence."""

from __future__ import annotations

import numpy as np
import pytest

from CertiTherm.operator_library import OperatorLibrary, geometry_key


def _operator(cells=4, blocks=3, seed=0):
    rng = np.random.default_rng(seed)
    return rng.uniform(0.1, 2.0, size=(cells, blocks)), rng.uniform(300.0, 310.0, size=cells)


def test_the_key_separates_geometry_package_and_model(tmp_path):
    a = geometry_key("blk 1 1 0 0\n", "default", "grid128-avg")
    assert a != geometry_key("blk 1 1 0 0\n", "standard", "grid128-avg")
    assert a != geometry_key("blk 1 1 0 0\n", "default", "grid64-avg")
    assert a != geometry_key("blk 1 1 0 1\n", "default", "grid128-avg")


def test_concatenation_cannot_forge_a_collision():
    """`("ab", "c", "d")` and `("a", "bc", "d")` must not share a key."""
    assert geometry_key("ab", "c", "d") != geometry_key("a", "bc", "d")


def test_a_hit_returns_the_stored_operator_bit_identically(tmp_path):
    library = OperatorLibrary(tmp_path)
    rows, ambient = _operator()
    blocks = ["b0", "b1", "b2"]
    library.put("flp\n", blocks, rows, ambient)
    got_rows, got_ambient = library.get("flp\n", blocks)
    assert np.array_equal(got_rows, rows)
    assert np.array_equal(got_ambient, ambient)


def test_a_different_floorplan_is_a_miss_not_a_near_hit(tmp_path):
    library = OperatorLibrary(tmp_path)
    rows, ambient = _operator()
    blocks = ["b0", "b1", "b2"]
    library.put("flp\n", blocks, rows, ambient)
    assert library.get("flp \n", blocks) is None, "one whitespace character is a different geometry"


def test_a_reordered_block_list_is_refused_rather_than_reordered(tmp_path):
    library = OperatorLibrary(tmp_path)
    rows, ambient = _operator()
    library.put("flp\n", ["b0", "b1", "b2"], rows, ambient)
    with pytest.raises(ValueError, match="different order"):
        library.get("flp\n", ["b1", "b0", "b2"])


def test_a_non_finite_operator_is_refused_on_the_way_in_and_out(tmp_path):
    library = OperatorLibrary(tmp_path)
    rows, ambient = _operator()
    bad = rows.copy()
    bad[0, 0] = np.nan
    with pytest.raises(ValueError, match="non-finite"):
        library.put("flp\n", ["b0", "b1", "b2"], bad, ambient)

    library.put("flp\n", ["b0", "b1", "b2"], rows, ambient)
    target = library.path_for("flp\n")
    with np.load(target, allow_pickle=False) as data:
        payload = {k: np.array(data[k]) for k in data.files}
    payload["response_k_per_w"][0, 0, 0] = np.inf
    np.savez_compressed(target, **payload)
    with pytest.raises(ValueError, match="non-finite"):
        library.get("flp\n", ["b0", "b1", "b2"])


def test_get_or_build_counts_hits_and_misses_and_builds_once(tmp_path):
    library = OperatorLibrary(tmp_path)
    rows, ambient = _operator()
    blocks = ["b0", "b1", "b2"]
    calls = []

    def build():
        calls.append(1)
        return rows, ambient

    got, amb, hit = library.get_or_build("flp\n", blocks, build)
    assert not hit and len(calls) == 1
    got2, amb2, hit2 = library.get_or_build("flp\n", blocks, build)
    assert hit2 and len(calls) == 1, "a hit must not rebuild"
    assert np.array_equal(got, got2) and np.array_equal(amb, amb2)
    assert library.stats.hits == 1 and library.stats.misses == 1
    assert library.stats.hit_rate == pytest.approx(0.5)


def test_a_shape_mismatch_is_refused_on_store(tmp_path):
    library = OperatorLibrary(tmp_path)
    rows, ambient = _operator(cells=4, blocks=3)
    with pytest.raises(ValueError, match="different column count"):
        library.put("flp\n", ["b0", "b1"], rows, ambient)
    with pytest.raises(ValueError, match="disagree"):
        library.put("flp\n", ["b0", "b1", "b2"], rows, ambient[:2])
