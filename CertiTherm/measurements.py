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
