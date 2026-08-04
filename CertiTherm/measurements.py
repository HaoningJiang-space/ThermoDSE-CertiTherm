"""Obtainable multilevel power-observation registry for EDA experiments."""

from __future__ import annotations

import re
from typing import Mapping, Optional, Sequence

import numpy as np

from .core import MeasurementAction, PowerPolytope


def _module_labels(blocks: Sequence[str]) -> list[str]:
    return [re.sub(r"\d+$", "", block.split("_", 1)[0]) for block in blocks]


def content_upper_bounds(
    blocks: Sequence[str], placed_power_w: np.ndarray
) -> np.ndarray:
    """Conservative per-block capacities from each content-type power budget."""

    placed = np.asarray(placed_power_w, dtype=float)
    if placed.shape != (len(blocks),):
        raise ValueError("block and placed-power dimensions differ")
    labels = _module_labels(blocks)
    totals = {
        label: float(np.sum(placed[np.asarray(labels) == label]))
        for label in set(labels)
    }
    return np.asarray([totals[label] for label in labels])


def coarse_power_space(
    placed_power_w: np.ndarray, upper_w: Optional[np.ndarray] = None
) -> PowerPolytope:
    """Admit every nonnegative placement with the observed workload total."""

    placed = np.asarray(placed_power_w, dtype=float)
    if placed.ndim != 1 or not np.all(np.isfinite(placed)) or np.any(placed < 0):
        raise ValueError("placed power must be a finite nonnegative vector")
    total = float(np.sum(placed))
    if total <= 0:
        raise ValueError("placed power must have positive total")
    upper = np.full(placed.size, total) if upper_w is None else np.asarray(upper_w)
    if upper.shape != placed.shape or np.any(upper < placed):
        raise ValueError("content upper bounds must cover the placed vector")
    return PowerPolytope.box_with_total(
        np.zeros(placed.size), upper, total
    )


def activity_bounded_power_space(
    blocks: Sequence[str],
    placed_power_w: np.ndarray,
    *,
    activity_span: float,
    constrain_class_totals: bool = True,
) -> PowerPolytope:
    """A physically defensible uncertainty set: bounded per-block activity, capped class totals.

    `coarse_power_space` admits EVERY nonnegative redistribution that preserves the workload total,
    and `content_upper_bounds` gives each block its whole content class's power as an individual
    cap without constraining the class aggregate at all. Peer review named that as the single
    strongest attack on this work: a certificate derived from it may describe adversarial power maps
    no workload can produce, so "these blocks require post-route extraction" could be an artifact of
    the abstraction rather than a property of the design.

    This narrows it on two independent axes, both of which correspond to something a designer knows:

    * **Activity span.** Each block stays within `placed * (1 +- span)`. A block's power varies with
      utilisation, not arbitrarily, and `span` is that variation. It bounds how much power a blind
      direction can actually move, which is the quantity the whole construction depends on.
    * **Class totals.** Each content class's aggregate stays within its own placed total times the
      same span. This blocks redistribution ACROSS classes while leaving redistribution WITHIN a
      class untouched -- which is the honest thing for it to do, since a class is exactly what a
      module-level power report measures.

    The workload total is kept as an equality: it is the one quantity the capture actually observes.

    A larger `activity_span` is a weaker claim, never an unsound one: it enlarges the set, so any
    bound proved under it holds under every tighter set too. That is what makes a sweep over `span`
    a robustness curve rather than a tuning knob.
    """

    placed = np.asarray(placed_power_w, dtype=float)
    if placed.ndim != 1 or not np.all(np.isfinite(placed)) or np.any(placed < 0):
        raise ValueError("placed power must be a finite nonnegative vector")
    if placed.shape != (len(blocks),):
        raise ValueError("block and placed-power dimensions differ")
    if not np.isfinite(activity_span) or activity_span <= 0:
        raise ValueError(f"activity_span must be finite and positive, got {activity_span}")
    total = float(np.sum(placed))
    if total <= 0:
        raise ValueError("placed power must have positive total")

    lower = np.maximum(placed * (1.0 - activity_span), 0.0)
    # Capped at the registered content bound so this set is a genuine SUBSET of the one the method
    # was frozen with. Without the cap a block whose placed power is close to its class total gets
    # `placed * (1 + span)` ABOVE that total, the two sets cross, and a bound proved here would not
    # be comparable with the registered one. A test caught exactly that at span 0.3.
    upper = np.minimum(placed * (1.0 + activity_span), content_upper_bounds(blocks, placed))
    if float(np.sum(lower)) > total or float(np.sum(upper)) < total:
        raise ValueError(
            "the activity box excludes the observed total, so the set would be empty; "
            f"span={activity_span} admits [{float(np.sum(lower)):.3f}, {float(np.sum(upper)):.3f}] "
            f"against a total of {total:.3f}"
        )

    rows: list[np.ndarray] = []
    rhs: list[float] = []
    if constrain_class_totals:
        labels = np.asarray(_module_labels(blocks))
        for label in sorted(set(labels.tolist())):
            member = (labels == label).astype(float)
            rows.append(member)
            rhs.append(float(np.sum(placed[labels == label])) * (1.0 + activity_span))
    return PowerPolytope(
        lower_w=lower,
        upper_w=upper,
        a_eq=np.ones((1, placed.size)),
        b_eq=np.array([total]),
        a_ub=np.asarray(rows) if rows else np.empty((0, placed.size)),
        b_ub=np.asarray(rhs) if rhs else np.empty(0),
    )


def envelope_is_singleton(space: PowerPolytope, *, relative_tolerance: float = 1e-12) -> bool:
    """Does the box, with the total equality, admit exactly ONE power map?

    `activity_bounded_power_space` caps each block at its content class's total
    (`content_upper_bounds`), which is necessary — without it the set would not be a subset of the
    registered one — and which **collapses the set to a point whenever every live block is alone in
    its class**: then `upper == placed`, `sum(upper) == total`, and the equality pins every
    coordinate. The supremum then equals the nominal point evaluation at EVERY span, and a driver
    that reports "certified to span 2.0" is saying the design tolerates +-200 % variation when it
    tolerates none.

    Measured on 127 routed traces: **one design** does this (`arxv034`, a single-core architecture)
    and it does it under both workloads. Under one it landed an ulp below the total and
    `_refuse_empty_rows` raised; under the other it landed exactly on it and the singleton passed
    silently. **The same structural condition decided by rounding** is what this predicate replaces:
    a caller can now ask, and get the same answer on both sides of that boundary.

    Symmetric in the two bounds because either can pin: `sum(upper) == total` forces every block up,
    `sum(lower) == total` forces every block down.
    """
    lower = np.asarray(space.lower_w, dtype=float)
    upper = np.asarray(space.upper_w, dtype=float)
    total = float(np.asarray(space.b_eq, dtype=float).ravel()[0])
    scale = max(abs(total), 1.0) * relative_tolerance
    return (abs(float(upper.sum()) - total) <= scale
            or abs(float(lower.sum()) - total) <= scale)


def deviation_bounded_power_space(
    placed_power_w: np.ndarray, *, deviation_fraction: float
) -> PowerPolytope:
    """Admit maps whose EVERY block deviates by at most `deviation_fraction` of TOTAL power.

    An L-infinity ball of half-width `deviation_fraction * sum(q)`, intersected with the
    total-power plane and the nonnegative orthant. Note what that is NOT: it is not a bound on how
    much power moves. Each of `n` blocks may take its full allowance at once, so the L1 distance it
    admits reaches `n * deviation_fraction * sum(q)`, which on a 237-block instance is two orders of
    magnitude more than an L1 transfer budget of the same nominal fraction.

    This function used to be called `relocation_bounded_power_space` and its docstring described the
    L1 body it does not build. Two distinct radii were reported under one name -- the box reaches a
    reject floor at 2.637% on arch_a/default/resnet50 where the exact L1 body needs 4.1% -- and the
    docstring asserted that "any bound proved on it remains valid", which is false in the direction
    that matters: the box is a SUPERSET of the L1 ball, so a lower bound on the box's minimum
    observation cost does NOT lower-bound the L1 problem's. A superset admits more SAFE/REJECT
    collisions and therefore demands at least as much observation. Peer review caught the claim; use
    `relocation_bounded_power_space` below when the conclusion must be about relocation.

    **What this set IS the right tool for.** Being an OUTER approximation, it transfers the claims
    the inscribed box cannot: if NO admissible map here is REJECT, then none is REJECT under L1
    relocation either, so the empty plan certifies and no measurement is needed. Universal safety
    and UPPER bounds travel down from a superset; existence and lower bounds travel up from a
    subset. Use this one to prove a design safe and the inscribed one to prove instrumentation
    necessary, and the true L1 answer is bracketed from both sides.
    """

    placed = np.asarray(placed_power_w, dtype=float)
    if placed.ndim != 1 or not np.all(np.isfinite(placed)) or np.any(placed < 0):
        raise ValueError("placed power must be a finite nonnegative vector")
    if not np.isfinite(deviation_fraction) or deviation_fraction <= 0:
        raise ValueError(
            f"deviation_fraction must be finite and positive, got {deviation_fraction}"
        )
    total = float(np.sum(placed))
    if total <= 0:
        raise ValueError("placed power must have positive total")
    budget = deviation_fraction * total
    return PowerPolytope(
        lower_w=np.maximum(placed - budget, 0.0),
        upper_w=placed + budget,
        a_eq=np.ones((1, placed.size)),
        b_eq=np.array([total]),
        a_ub=np.empty((0, placed.size)),
        b_ub=np.empty(0),
    )


def relocation_bounded_power_space(
    placed_power_w: np.ndarray, *, relocated_fraction: float
) -> PowerPolytope:
    """The largest box INSIDE `|p - q|_1 <= 2 * relocated_fraction * sum(q)`, total conserved.

    The uncertainty statement a power model can actually be held to: at most a fraction of the
    workload's own total power ends up somewhere other than predicted. It is scale-free and
    independent of how finely the design is decomposed into blocks, which a per-block relative box
    is not.

    The exact L1 body IS a polytope over `p` alone -- `s . (p - q) <= 2 b Q` for every sign vector
    `s`, or equivalently `sum_{i in S} (p_i - q_i) <= b Q` for every subset `S` once the total is
    conserved. What it is not is COMPACT: that is an exponential facet count, not an impossibility,
    and an earlier version of this docstring said "cannot be written over p alone with finitely many
    rows", which is false and contradicted this repository's own `l1_body.py`. A compact exact
    encoding exists too, by lifting to `(p, t)` with `t_i >= |p_i - q_i|` and `sum t <= 2 b Q`.

    What this function returns is a sound UNIFORM INSCRIBED box. With the total conserved,
    `sum(p - q) = 0`, so the deviations split into equal positive and negative parts and a box of
    half-width `h` admits `|p - q|_1 <= 2 * floor(n/2) * h`. Setting

        h = relocated_fraction * sum(q) / floor(n / 2)

    puts the box inside the L1 ball. It is the largest UNIFORM inscribed box; it is not the largest
    inscribed box, since non-uniform half-widths summing to the same budget also fit, and with
    `p >= 0` clamping and unequal `q_i` "largest" is not even well defined. Peer review corrected an
    earlier claim of "largest".

    **Which conclusions transfer, and in which direction.** A subset admits no more SAFE/REJECT
    collisions than the set containing it, so from this box the following travel UP to the L1
    problem: a collision EXISTS, a coarse-blind pair EXISTS, the minimum observation cost is AT
    LEAST `c`. The following do NOT: no collision exists, coarse reports suffice, no measurement is
    needed. Those are universal-safety claims and need the exact body or an OUTER approximation such
    as `deviation_bounded_power_space`. An earlier draft used this box to argue "no measurement
    needed under relocation", which is that error exactly -- and the concentrated relocations this
    box drops are the ones most likely to make a hotspot.
    """

    placed = np.asarray(placed_power_w, dtype=float)
    if placed.ndim != 1 or not np.all(np.isfinite(placed)) or np.any(placed < 0):
        raise ValueError("placed power must be a finite nonnegative vector")
    if not np.isfinite(relocated_fraction) or relocated_fraction <= 0:
        raise ValueError(
            f"relocated_fraction must be finite and positive, got {relocated_fraction}"
        )
    total = float(np.sum(placed))
    if total <= 0:
        raise ValueError("placed power must have positive total")
    budget = relocated_fraction * total / max(placed.size // 2, 1)
    return PowerPolytope(
        lower_w=np.maximum(placed - budget, 0.0),
        upper_w=placed + budget,
        a_eq=np.ones((1, placed.size)),
        b_eq=np.array([total]),
        a_ub=np.empty((0, placed.size)),
        b_ub=np.empty(0),
    )


def _groups(labels: Sequence[str]) -> list[tuple[str, np.ndarray]]:
    grouped: dict[str, list[int]] = {}
    for index, label in enumerate(labels):
        grouped.setdefault(label, []).append(index)
    return [
        (label, np.asarray(indices, dtype=int))
        for label, indices in sorted(grouped.items())
    ]


def _chiplet_labels(
    blocks: Sequence[str], architecture: Mapping[str, str]
) -> list[str]:
    nx, ny = int(architecture["chiplet_x"]), int(architecture["chiplet_y"])
    cut_x, cut_y = int(architecture["cut_x"]), int(architecture["cut_y"])
    widths = [nx // cut_x + (index < nx % cut_x) for index in range(cut_x)]
    heights = [ny // cut_y + (index < ny % cut_y) for index in range(cut_y)]
    x_edges, y_edges = np.cumsum(widths), np.cumsum(heights)
    labels = []
    for block in blocks:
        match = re.search(r"_(\d+)$", block)
        if match is None:
            labels.append("periphery")
            continue
        tile = int(match.group(1))
        x, y = tile % nx, tile // nx
        if y >= ny:
            labels.append("periphery")
            continue
        chip_x = int(np.searchsorted(x_edges, x, side="right"))
        chip_y = int(np.searchsorted(y_edges, y, side="right"))
        labels.append(f"y{chip_y}-x{chip_x}")
    return labels


def _region_labels(blocks: Sequence[str], floorplan_text: str) -> list[str]:
    geometry: dict[str, tuple[float, float]] = {}
    for line in floorplan_text.splitlines():
        fields = line.split()
        if len(fields) < 5 or fields[0].startswith("#"):
            continue
        geometry[fields[0]] = (
            float(fields[3]) + float(fields[1]) / 2,
            float(fields[4]) + float(fields[2]) / 2,
        )
    if any(block not in geometry for block in blocks):
        raise ValueError("floorplan geometry does not cover every power block")
    x = np.asarray([geometry[block][0] for block in blocks])
    y = np.asarray([geometry[block][1] for block in blocks])
    x_mid, y_mid = (float(np.min(x)) + float(np.max(x))) / 2, (
        float(np.min(y)) + float(np.max(y))
    ) / 2
    return [
        f"{'N' if yi >= y_mid else 'S'}{'E' if xi >= x_mid else 'W'}"
        for xi, yi in zip(x, y)
    ]


def build_measurement_library(
    candidate_id: str,
    blocks: Sequence[str],
    floorplan_text: str,
    architecture: Mapping[str, str],
    costs: Mapping[str, float],
) -> tuple[MeasurementAction, ...]:
    """Build and deduplicate module/chiplet/region/post-route channels."""

    n = len(blocks)
    required = ("module", "chiplet", "placement_region", "post_route")
    if set(costs) != set(required):
        raise ValueError(f"measurement costs must define exactly {required}")
    registries = (
        ("module", _groups(_module_labels(blocks))),
        ("chiplet", _groups(_chiplet_labels(blocks, architecture))),
        ("placement_region", _groups(_region_labels(blocks, floorplan_text))),
        (
            "post_route",
            [(block, np.asarray([index])) for index, block in enumerate(blocks)],
        ),
    )
    # Deduplication keeps the CHEAPEST equivalent action, not the first one encountered. Two
    # groups with the same support -- or with complementary supports, which read the same
    # difference under the polytope's fixed total -- are the same observation, so registering both
    # and keeping whichever came first would charge a caller for the more expensive one. It happens
    # to be safe for the monotone 1/2/4/8 ladder this project registers, since the classes are
    # visited cheapest-first, but the signature accepts any cost mapping and peer review was right
    # that nothing enforced the order. This does.
    ordered = sorted(registries, key=lambda entry: float(costs[entry[0]]))
    actions, seen = [], {(), tuple(range(n))}
    for action_class, groups in ordered:
        for label, indices in groups:
            key = tuple(indices.tolist())
            key_set = set(key)
            complement = tuple(index for index in range(n) if index not in key_set)
            if key in seen or complement in seen:
                continue
            seen.add(key)
            vector = np.zeros(n)
            vector[indices] = 1.0
            actions.append(
                MeasurementAction(
                    f"{candidate_id}::{action_class}::{label}",
                    vector,
                    cost=float(costs[action_class]),
                    candidate_id=candidate_id,
                )
            )
    return tuple(actions)
