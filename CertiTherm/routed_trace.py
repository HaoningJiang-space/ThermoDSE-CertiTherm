"""Route-aware, energy-conserving lowering to an augmented HotSpot floorplan.

ThermoDSE exposes communication events before its aliased ``link_hops`` index.  This
module uses only those events and their already-reconciled aggregate channel energies.
It does not trust or copy the corrupted link array.

Placement contract
------------------
* Core component energy retains the exact ThermoDSE floorplan block mapping.
* A deterministic XY union tree supplies the physical edges for each event.  NoC/NoP
  energy is recomputed from event volume, explicit edge class, and the evaluator's
  per-hop costs, then reconciled against the physical evaluator's monitor counters.
* Same-chiplet NoC energy is split between the two facing ``io_*`` endpoint blocks.
* Cross-chiplet NoP energy is placed on the intervening ``blockX_*``/``blockY_*`` block.
* ThermoDSE deliberately excludes the external DRAM edge from NoP hop energy.  No energy
  is invented for that uncharacterized edge; DRAM-access energy is placed on the DRAM die.
* DRAM-access energy is divided equally over the DRAM locations, matching ThermoDSE's
  ``unicast_dram``/``unicast_to_dram`` convention.

ThermoDSE specifies IO-die area and corner coordinates but no aspect ratio.  The augmented
floorplan defaults to equal-area square dies (the minimum-perimeter neutral choice) and
records the chosen width/height aspect ratio. It is a sensitivity parameter, not a
discovered fact.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from math import sqrt
from types import MappingProxyType
from typing import Dict, Mapping, Sequence, Tuple

import numpy as np

from CertiTherm.phase_trace import PhaseTrace
from CertiTherm.thermodse_trace import ThermoDSETraceLowering

Coord = Tuple[int, int]
Edge = Tuple[Coord, Coord]


def _canonical_edge(a: Coord, b: Coord) -> Edge:
    if abs(a[0] - b[0]) + abs(a[1] - b[1]) != 1:
        raise ValueError(f"route edge is not Manhattan-adjacent: {a} -> {b}")
    return (a, b) if a <= b else (b, a)


def _xy_path(source: Coord, destination: Coord, nx: int) -> Tuple[Edge, ...]:
    """Deterministic path that never routes vertically in an external DRAM column."""

    x, y = source
    edges = []

    def horizontal(target_x: int) -> None:
        nonlocal x
        step = 1 if target_x > x else -1
        while x != target_x:
            nxt = (x + step, y)
            edges.append(_canonical_edge((x, y), nxt))
            x += step

    def vertical(target_y: int) -> None:
        nonlocal y
        step = 1 if target_y > y else -1
        while y != target_y:
            nxt = (x, y + step)
            edges.append(_canonical_edge((x, y), nxt))
            y += step

    # Core -> external DRAM exits at the DRAM row.  External DRAM -> core enters at
    # the DRAM row.  Both avoid inventing a vertical router column outside the package.
    external_x = (0, nx + 1)
    if destination[0] in external_x:
        vertical(destination[1])
        horizontal(destination[0])
    elif source[0] in external_x:
        horizontal(destination[0])
        vertical(destination[1])
    else:
        horizontal(destination[0])
        vertical(destination[1])
    if (x, y) != destination:
        raise RuntimeError("route construction did not reach its destination")
    return tuple(edges)


def _parse_floorplan(text: str) -> Tuple[Tuple[str, float, float, float, float], ...]:
    rows = []
    for line in text.splitlines():
        fields = line.split()
        if not fields or fields[0].startswith("#"):
            continue
        if len(fields) < 5:
            raise ValueError(f"invalid floorplan line: {line}")
        rows.append(
            (
                fields[0],
                float(fields[1]),
                float(fields[2]),
                float(fields[3]),
                float(fields[4]),
            )
        )
    names = [row[0] for row in rows]
    if not rows or len(set(names)) != len(names):
        raise ValueError("floorplan must contain unique, non-empty block rows")
    if any(
        not np.all(np.isfinite(row[1:])) or row[1] <= 0.0 or row[2] <= 0.0
        for row in rows
    ):
        raise ValueError("floorplan geometry must be finite with positive dimensions")
    return tuple(rows)


@dataclass(frozen=True)
class AugmentedFloorplan:
    """Original compute floorplan plus explicit DRAM dies and side filler."""

    text: str
    block_ids: Tuple[str, ...]
    original_block_ids: Tuple[str, ...]
    dram_blocks: Mapping[Coord, str]
    io_die_area_each_m2: float
    io_die_aspect_ratio: float = 1.0

    def __post_init__(self) -> None:
        blocks = tuple(self.block_ids)
        original = tuple(self.original_block_ids)
        dram = MappingProxyType(dict(self.dram_blocks))
        if len(set(blocks)) != len(blocks) or not set(original).issubset(blocks):
            raise ValueError("augmented floorplan block registry is inconsistent")
        if not dram or not set(dram.values()).issubset(blocks):
            raise ValueError("every DRAM location must name an augmented block")
        if (
            not np.isfinite(self.io_die_area_each_m2)
            or self.io_die_area_each_m2 <= 0.0
            or not np.isfinite(self.io_die_aspect_ratio)
            or self.io_die_aspect_ratio <= 0.0
        ):
            raise ValueError("IO-die geometry receipt is invalid")
        object.__setattr__(self, "block_ids", blocks)
        object.__setattr__(self, "original_block_ids", original)
        object.__setattr__(self, "dram_blocks", dram)


def augment_floorplan_with_dram(
    floorplan_text: str,
    *,
    io_die_area_each_m2: float,
    dram_locations: Sequence[Coord],
    compute_shape: Tuple[int, int],
    io_die_aspect_ratio: float = 1.0,
) -> AugmentedFloorplan:
    """Add equal-area DRAM dies at the external coordinates specified by ThermoDSE."""

    rows = _parse_floorplan(floorplan_text)
    locations = tuple((int(x), int(y)) for x, y in dram_locations)
    if not locations or len(set(locations)) != len(locations):
        raise ValueError("dram_locations must be unique and non-empty")
    nx, ny = (int(compute_shape[0]), int(compute_shape[1]))
    if nx < 1 or ny < 1:
        raise ValueError("compute_shape must be positive")
    if any(x not in (0, nx + 1) or not (0 <= y < ny) for x, y in locations):
        raise ValueError("DRAM coordinates must sit in the two external columns")
    if not np.isfinite(io_die_area_each_m2) or io_die_area_each_m2 <= 0.0:
        raise ValueError("io_die_area_each_m2 must be finite and positive")
    if not np.isfinite(io_die_aspect_ratio) or io_die_aspect_ratio <= 0.0:
        raise ValueError("io_die_aspect_ratio must be finite and positive")

    old_width = max(x + width for _, width, _, x, _ in rows)
    old_height = max(y + height for _, _, height, _, y in rows)
    die_width = sqrt(float(io_die_area_each_m2) * float(io_die_aspect_ratio))
    die_height = sqrt(float(io_die_area_each_m2) / float(io_die_aspect_ratio))
    if die_height > old_height:
        raise ValueError("IO die is taller than the package floorplan")

    augmented_rows = []
    dram_blocks: Dict[Coord, str] = {}
    intervals_by_side: Dict[str, list] = {"left": [], "right": []}
    for x, y in locations:
        side_name = "left" if x == 0 else "right"
        if ny == 1:
            bottom = 0.5 * (old_height - die_height)
        else:
            bottom = (float(y) / float(ny - 1)) * (old_height - die_height)
        left = 0.0 if side_name == "left" else die_width + old_width
        name = f"dram_x{x}_y{y}"
        dram_blocks[(x, y)] = name
        intervals_by_side[side_name].append((bottom, bottom + die_height))
        augmented_rows.append((name, die_width, die_height, left, bottom))

    # The side strips must not overlap.  Fill uncovered intervals with zero-power
    # package blocks so the augmented floorplan remains a rectangular tiling.
    for side_name, intervals in intervals_by_side.items():
        intervals.sort()
        cursor = 0.0
        left = 0.0 if side_name == "left" else die_width + old_width
        fill_index = 0
        for bottom, top in intervals:
            if bottom < cursor - 1e-12:
                raise ValueError("square IO dies overlap on one package side")
            if bottom > cursor + 1e-12:
                augmented_rows.append(
                    (
                        f"io_fill_{side_name}_{fill_index}",
                        die_width,
                        bottom - cursor,
                        left,
                        cursor,
                    )
                )
                fill_index += 1
            cursor = top
        if cursor < old_height - 1e-12:
            augmented_rows.append(
                (
                    f"io_fill_{side_name}_{fill_index}",
                    die_width,
                    old_height - cursor,
                    left,
                    cursor,
                )
            )

    # Preserve every original block identity and relative coordinate, shifting it
    # between the newly added left/right IO strips.
    augmented_rows.extend(
        (name, width, height, x + die_width, y)
        for name, width, height, x, y in rows
    )
    for index_a, row_a in enumerate(augmented_rows):
        _, width_a, height_a, x_a, y_a = row_a
        if x_a < -1e-15 or y_a < -1e-15:
            raise ValueError("augmented floorplan has a negative coordinate")
        for row_b in augmented_rows[index_a + 1 :]:
            _, width_b, height_b, x_b, y_b = row_b
            overlap_x = min(x_a + width_a, x_b + width_b) - max(x_a, x_b)
            overlap_y = min(y_a + height_a, y_b + height_b) - max(y_a, y_b)
            if overlap_x > 1e-12 and overlap_y > 1e-12:
                raise ValueError(
                    f"augmented floorplan blocks overlap: {row_a[0]} and {row_b[0]}"
                )
    text = "".join(
        f"{name}\t{width:.12g}\t{height:.12g}\t{x:.12g}\t{y:.12g}\n"
        for name, width, height, x, y in augmented_rows
    )
    return AugmentedFloorplan(
        text=text,
        block_ids=tuple(row[0] for row in augmented_rows),
        original_block_ids=tuple(row[0] for row in rows),
        dram_blocks=dram_blocks,
        io_die_area_each_m2=float(io_die_area_each_m2),
        io_die_aspect_ratio=float(io_die_aspect_ratio),
    )


def _core_index(cluster_coord: Coord, nx: int, ny: int) -> int:
    x, y = cluster_coord
    if not (1 <= x <= nx and 0 <= y < ny):
        raise ValueError(f"coordinate is not a compute core: {cluster_coord}")
    return y * nx + (x - 1)


def _facing_io_block(core: Coord, neighbour: Coord, nx: int, ny: int) -> str:
    index = _core_index(core, nx, ny)
    dx, dy = neighbour[0] - core[0], neighbour[1] - core[1]
    # ThermoDSE floorplan names: io_0=left, io_1=bottom, io_2=right, io_3=top.
    side = {(1, 0): 2, (-1, 0): 0, (0, 1): 3, (0, -1): 1}.get((dx, dy))
    if side is None:
        raise ValueError("IO endpoints must be adjacent")
    return f"io_{side}_{index}"


def _chiplet_id(
    core: Coord, nx: int, ny: int, cut_x: int, cut_y: int
) -> Tuple[int, int]:
    index_x, index_y = core[0] - 1, core[1]
    step_x, step_y = nx // cut_x, ny // cut_y
    if step_x < 1 or step_y < 1:
        raise ValueError("chiplet cuts exceed the compute shape")
    return min(index_x // step_x, cut_x - 1), min(index_y // step_y, cut_y - 1)


def _edge_channel(
    edge: Edge, nx: int, ny: int, cut_x: int, cut_y: int
) -> str:
    a, b = edge
    if a[0] in (0, nx + 1) or b[0] in (0, nx + 1):
        return "nop"
    return (
        "noc"
        if _chiplet_id(a, nx, ny, cut_x, cut_y)
        == _chiplet_id(b, nx, ny, cut_x, cut_y)
        else "nop"
    )


def _event_edge_weights(event: Mapping[str, object], nx: int) -> Counter:
    kind = str(event["kind"])
    weights: Counter = Counter()

    def coord(value: object) -> Coord:
        pair = tuple(int(item) for item in value)  # type: ignore[arg-type]
        if len(pair) != 2:
            raise ValueError("route coordinate must have two entries")
        return pair  # type: ignore[return-value]

    def coords(value: object) -> Tuple[Coord, ...]:
        return tuple(coord(item) for item in value)  # type: ignore[arg-type]

    if kind == "core_to_core":
        source_core = coord(event["source"])
        source = (source_core[0] + 1, source_core[1])
        destinations = tuple((x + 1, y) for x, y in coords(event["destinations"]))
        tree = set()
        for destination in destinations:
            tree.update(_xy_path(source, destination, nx))
        for edge in tree:
            weights[edge] += 1.0
    elif kind == "dram_read":
        destinations = tuple((x + 1, y) for x, y in coords(event["destinations"]))
        dram = coords(event["dram_locations"])
        for source in dram:
            tree = set()
            for destination in destinations:
                tree.update(_xy_path(source, destination, nx))
            for edge in tree:
                weights[edge] += 1.0 / len(dram)
    elif kind == "dram_write":
        source_core = coord(event["source"])
        source = (source_core[0] + 1, source_core[1])
        dram = coords(event["dram_locations"])
        for destination in dram:
            for edge in _xy_path(source, destination, nx):
                weights[edge] += 1.0 / len(dram)
    else:
        raise ValueError(f"unknown communication event kind: {kind}")
    if not weights:
        # A local same-core reuse can legitimately have zero communication energy.
        if any(float(event[name]) != 0.0 for name in ("noc_energy_pj", "nop_energy_pj")):
            raise ValueError("positive communication energy has an empty route")
    return weights


def _place_edge_energy(
    target_j: np.ndarray,
    *,
    edge: Edge,
    energy_j: float,
    channel: str,
    floorplan: AugmentedFloorplan,
    block_index: Mapping[str, int],
    nx: int,
    ny: int,
    endpoint_split: float = 0.5,
) -> None:
    """`endpoint_split` is the share taken by the FIRST of the two endpoint blocks.

    The lowering has to decide how a link's dissipation divides between the two blocks it connects,
    and `0.5` is a modelling choice rather than a measurement -- `docs/ADVERSARIAL_SELF_REVIEW.md` B3
    lists it as a named, unmeasured degree of freedom. Making it a parameter is what turns it into a
    sensitivity that can be swept, and the sweep is a matvec because the FLOORPLAN does not change:
    the same two blocks receive the energy, only in different proportion.
    """
    if not (0.0 <= endpoint_split <= 1.0) or endpoint_split != endpoint_split:
        raise ValueError(f"endpoint_split must lie in [0, 1], got {endpoint_split!r}")
    if energy_j == 0.0:
        return
    a, b = edge
    external = a if a[0] in (0, nx + 1) else b if b[0] in (0, nx + 1) else None
    if external is not None:
        core = b if external == a else a
        dram_block = floorplan.dram_blocks.get(external)
        if dram_block is None:
            raise ValueError(f"external route has no DRAM block: {external}")
        io_block = _facing_io_block(core, external, nx, ny)
        for name, share in ((dram_block, endpoint_split), (io_block, 1.0 - endpoint_split)):
            if name not in block_index:
                raise ValueError(f"route target is absent from floorplan: {name}")
            target_j[block_index[name]] += share * energy_j
        return

    if channel == "noc":
        for (core, neighbour), share in (((a, b), endpoint_split), ((b, a), 1.0 - endpoint_split)):
            name = _facing_io_block(core, neighbour, nx, ny)
            if name not in block_index:
                raise ValueError(f"NoC endpoint block is absent: {name}")
            target_j[block_index[name]] += share * energy_j
        return

    if a[1] == b[1]:
        left_x = min(a[0], b[0]) - 1
        index = a[1] * nx + left_x
        name = f"blockX_{index}"
    else:
        compute_x = a[0] - 1
        bottom_y = min(a[1], b[1])
        index = bottom_y * nx + compute_x
        name = f"blockY_{index}"
    if name not in block_index:
        raise ValueError(f"NoP gap block is absent: {name}")
    target_j[block_index[name]] += energy_j


def _is_external_edge(edge: Edge, nx: int) -> bool:
    return any(coord[0] in (0, nx + 1) for coord in edge)


COMPONENTS: Tuple[str, ...] = ("core", "noc", "nop", "dram")


def _resolved_components(components) -> frozenset:
    """Validate a component mask. `None` means every component, i.e. today's behaviour."""

    if components is None:
        return frozenset(COMPONENTS)
    resolved = frozenset(str(name) for name in components)
    unknown = resolved - frozenset(COMPONENTS)
    if unknown:
        raise ValueError(f"unknown power components: {sorted(unknown)}")
    if not resolved:
        raise ValueError("a component mask must retain at least one component")
    return resolved


@dataclass(frozen=True)
class RoutedThermoDSETrace:
    floorplan: AugmentedFloorplan
    trace: PhaseTrace
    source_energy_j: float
    route_energy_j: float
    monitor_source_energy_j: float
    monitor_route_energy_j: float
    physical_channel_hops: Tuple[float, float]
    monitor_channel_hops: Tuple[float, float]
    # Component attribution. `component_energy_j` is the FULL per-component ledger and is
    # populated identically whether or not a mask is applied, so a masked run can be
    # checked against an unmasked one. `retained_components` records what the emitted
    # trace actually deposits; `source_energy_j` is the RETAINED source energy, because
    # the conservation identity below is what makes a masked trace replayable at all.
    component_energy_j: Mapping[str, float] = field(default_factory=dict)
    retained_components: Tuple[str, ...] = COMPONENTS
    full_source_energy_j: float = 0.0

    def __post_init__(self) -> None:
        if self.trace.dimension != len(self.floorplan.block_ids):
            raise ValueError("trace and augmented floorplan dimensions differ")
        if (
            len(self.physical_channel_hops) != 2
            or len(self.monitor_channel_hops) != 2
        ):
            raise ValueError("channel-hop receipts must contain NoC and NoP")
        if not np.isclose(
            float(self.trace.energy_j().sum()),
            float(self.source_energy_j),
            rtol=1e-11,
            atol=1e-18,
        ):
            raise ValueError("complete routed trace does not conserve source energy")
        values = (
            self.source_energy_j,
            self.route_energy_j,
            self.monitor_source_energy_j,
            self.monitor_route_energy_j,
            *self.physical_channel_hops,
            *self.monitor_channel_hops,
        )
        if any(not np.isfinite(value) or value < 0.0 for value in values):
            raise ValueError("routed trace energy receipts must be finite and non-negative")
        retained = _resolved_components(self.retained_components)
        split = dict(self.component_energy_j)
        if split:
            if frozenset(split) != frozenset(COMPONENTS):
                raise ValueError("component_energy_j must cover every component")
            if any(not np.isfinite(v) or v < 0.0 for v in split.values()):
                raise ValueError("component energies must be finite and non-negative")
            # The retained components must account for the emitted trace exactly, and the
            # full split must account for the full source. Checking both is what lets a
            # masked run be compared against an unmasked one.
            if not np.isclose(sum(split[name] for name in retained),
                              float(self.source_energy_j), rtol=1e-11, atol=1e-18):
                raise ValueError("retained component energies do not match source_energy_j")
            if self.full_source_energy_j and not np.isclose(
                sum(split.values()), float(self.full_source_energy_j),
                rtol=1e-11, atol=1e-18):
                raise ValueError("component split does not match full_source_energy_j")
        object.__setattr__(
            self, "physical_channel_hops", tuple(self.physical_channel_hops)
        )
        object.__setattr__(self, "monitor_channel_hops", tuple(self.monitor_channel_hops))
        object.__setattr__(self, "component_energy_j", MappingProxyType(split))
        object.__setattr__(self, "retained_components",
                           tuple(name for name in COMPONENTS if name in retained))


def lower_routed_trace(
    core: ThermoDSETraceLowering,
    *,
    floorplan: AugmentedFloorplan,
    events: Sequence[Mapping[str, object]],
    compute_shape: Tuple[int, int],
    chiplet_cuts: Tuple[int, int],
    noc_hop_cost_pj: float,
    nop_hop_cost_pj: float,
    batch_factor: int = 1,
    endpoint_split: float = 0.5,
    components=None,
) -> RoutedThermoDSETrace:
    """Combine exact core energy with physically reclassified communication energy.

    Captured monitor counters and independently lowered physical edges must reconcile for
    every order.  This makes routing, performance/energy accounting, and heat placement
    share one fact source.

    `components` optionally restricts which sources are DEPOSITED into the trace, for
    causal isolation of a thermal result. `None` reproduces the unmasked behaviour exactly.
    Masking gates deposition ONLY: every route reconciliation receipt is still computed and
    enforced against the full ledger, because those receipts validate the route lowering
    itself and are independent of which sources are placed. A mask that skipped them would
    be testing a different, unverified lowering.
    """

    retained = _resolved_components(components)

    nx, ny = int(compute_shape[0]), int(compute_shape[1])
    cut_x, cut_y = int(chiplet_cuts[0]), int(chiplet_cuts[1])
    if nx < 1 or ny < 1 or cut_x < 1 or cut_y < 1 or batch_factor < 1:
        raise ValueError("shape, cuts, and batch_factor must be positive")
    costs_pj = {"noc": float(noc_hop_cost_pj), "nop": float(nop_hop_cost_pj)}
    if any(not np.isfinite(cost) or cost <= 0.0 for cost in costs_pj.values()):
        raise ValueError("NoC/NoP hop costs must be finite and positive")
    index = {name: column for column, name in enumerate(floorplan.block_ids)}
    if not set(core.block_ids).issubset(index):
        raise ValueError("augmented floorplan does not contain the core trace registry")

    energy_j = np.zeros((core.trace.n_phases, len(floorplan.block_ids)), dtype=float)
    core_energy = core.trace.powers_w * core.trace.durations_s[:, None]
    if "core" in retained:
        for old_column, name in enumerate(core.block_ids):
            energy_j[:, index[name]] = core_energy[:, old_column]
    component_energy_j = {name: 0.0 for name in COMPONENTS}
    component_energy_j["core"] = float(core.represented_energy_j)

    monitor_external_by_order_j = np.zeros((core.trace.n_phases, 3), dtype=float)
    physical_external_by_order_j = np.zeros((core.trace.n_phases, 3), dtype=float)
    physical_channel_hops = np.zeros(2, dtype=float)
    monitor_channel_hops = np.zeros(2, dtype=float)
    route_total_j = 0.0
    for event in events:
        order = int(event["order"])
        if not (0 <= order < core.trace.n_phases):
            raise ValueError("communication event order is outside the phase trace")
        weights = _event_edge_weights(event, nx)
        volume = float(event["volume"])
        if not np.isfinite(volume) or volume < 0.0:
            raise ValueError("communication event volume must be finite and non-negative")
        for channel_column, channel in enumerate(("noc", "nop")):
            monitor_j = (
                float(event[f"{channel}_energy_pj"]) * batch_factor * 1e-12
            )
            monitor_external_by_order_j[order, channel_column] += monitor_j
            monitor_channel_hops[channel_column] += monitor_j / (
                costs_pj[channel] * 1e-12
            )
            selected = {
                edge: weight
                for edge, weight in weights.items()
                if _edge_channel(edge, nx, ny, cut_x, cut_y) == channel
                and not _is_external_edge(edge, nx)
            }
            for edge, weight in selected.items():
                edge_hops = volume * float(weight) * batch_factor
                physical_channel_hops[channel_column] += edge_hops
                edge_j = (
                    edge_hops
                    * costs_pj[channel]
                    * 1e-12
                )
                route_total_j += edge_j
                physical_external_by_order_j[order, channel_column] += edge_j
                component_energy_j[channel] += edge_j
                if channel in retained:
                    _place_edge_energy(
                        energy_j[order],
                        edge=edge,
                        energy_j=edge_j,
                        channel=channel,
                        floorplan=floorplan,
                        block_index=index,
                        nx=nx,
                        ny=ny,
                        endpoint_split=endpoint_split,
                    )

        dram_j = float(event["dram_energy_pj"]) * batch_factor * 1e-12
        monitor_external_by_order_j[order, 2] += dram_j
        physical_external_by_order_j[order, 2] += dram_j
        route_total_j += dram_j
        component_energy_j["dram"] += dram_j
        if dram_j:
            locations = tuple(
                (int(value[0]), int(value[1]))
                for value in event["dram_locations"]  # type: ignore[union-attr]
            )
            if not locations:
                raise ValueError("positive DRAM energy has no DRAM location")
            # The location check runs even when DRAM is masked out, so a masked run cannot
            # pass on inputs an unmasked run would reject.
            for location in locations:
                name = floorplan.dram_blocks.get(location)
                if name is None:
                    raise ValueError(f"DRAM location is absent: {location}")
                if "dram" in retained:
                    energy_j[order, index[name]] += dram_j / len(locations)

    if not np.allclose(
        monitor_external_by_order_j,
        core.unplaced_energy_j,
        rtol=1e-11,
        atol=1e-18,
    ):
        raise ValueError("route events do not reconcile with per-order monitor energy")
    if not np.allclose(
        physical_external_by_order_j,
        core.unplaced_energy_j,
        rtol=1e-11,
        atol=1e-18,
    ):
        # NAME THE ORDER AND THE MAGNITUDE. A refusal that says only "does not reconcile" cannot be
        # told apart from a rounding tolerance that is too tight, and three archive designs were
        # excluded from a census on this message with no way to know which it was.
        #
        # AN ERROR PATH MUST NEVER BE ABLE TO RAISE. The first version of this message indexed the
        # worst order without checking that the two arrays have the same length -- and they do not
        # on the designs that fail, so the refusal died with an IndexError instead of printing. The
        # shape check is therefore first, and the mismatch is itself the diagnosis: a per-order
        # ledger of a different LENGTH is not a tolerance problem.
        got = np.asarray(physical_external_by_order_j, dtype=float).ravel()
        want = np.asarray(core.unplaced_energy_j, dtype=float).ravel()
        if got.shape != want.shape:
            raise ValueError(
                "physical route energy does not reconcile with per-order monitor energy: the "
                f"physical ledger has {got.size} orders and the monitor {want.size}. This is a "
                "structural mismatch, not a tolerance one -- the two ledgers do not agree on how "
                "many orders the workload has, so no per-order comparison is defined."
            )
        scale = np.maximum(np.abs(want), 1e-300)
        relative = np.abs(got - want) / scale
        worst = int(np.argmax(relative))
        raise ValueError(
            "physical route energy does not reconcile with per-order monitor energy: worst at "
            f"order {worst} of {relative.size}, {got[worst]!r} against {want[worst]!r}, relative "
            f"{relative[worst]:.6e} against rtol 1e-11; {int(np.count_nonzero(relative > 1e-11))} "
            "orders disagree"
        )

    powers_w = energy_j / core.trace.durations_s[:, None]
    trace = PhaseTrace(core.trace.durations_s, powers_w)
    full_source_energy_j = core.represented_energy_j + route_total_j
    source_energy_j = sum(component_energy_j[name] for name in retained)
    return RoutedThermoDSETrace(
        floorplan=floorplan,
        trace=trace,
        source_energy_j=source_energy_j,
        route_energy_j=route_total_j,
        monitor_source_energy_j=core.thermal_energy_j,
        monitor_route_energy_j=core.residual_energy_j,
        physical_channel_hops=tuple(float(value) for value in physical_channel_hops),
        monitor_channel_hops=tuple(float(value) for value in monitor_channel_hops),
        component_energy_j=component_energy_j,
        retained_components=tuple(name for name in COMPONENTS if name in retained),
        full_source_energy_j=full_source_energy_j,
    )
