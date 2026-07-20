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
    actions, seen = [], {(), tuple(range(n))}
    for action_class, groups in registries:
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
