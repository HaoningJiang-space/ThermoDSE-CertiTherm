"""
CertiTherm: Spatial power injection (Stage 2 of audit)

Inject a synthetic spatial stress pattern into a ThermoDSE ptrace while
preserving the obtainable component-total power observations.  This is a
pilot adversary, not a substitute for real SAIF/VCD plus placed instance power.

Then re-run HotSpot to get the spatial-power peak temperature.

Pattern modes:
  - centered: hot spot in middle, cooler at edges (Gaussian falloff)
  - corner: hot in one corner (workload concentrated on one chiplet)
  - checker: alternating hot/cold (representing interleaved workloads)
  - random: seeded per-block random stress (not a worst-case guarantee)
"""
import os
import math
import re
import numpy as np
import argparse


_COMPONENT_TYPES = (
    'mtxu', 'vecu', 'ubuf', 'ibuf', 'obuf', 'io_0', 'io_1', 'io_2', 'io_3'
)
_COMPONENT_COLUMN = re.compile(
    rf"^({'|'.join(re.escape(name) for name in _COMPONENT_TYPES)})_(\d+)$"
)


def make_pattern(cxlen, cylen, mode='centered', strength=5.0, seed=42):
    """Generate a spatial power multiplier pattern.

    Return one positive multiplier per chiplet-grid cell.
    """
    if not isinstance(cxlen, int) or not isinstance(cylen, int) or cxlen <= 0 or cylen <= 0:
        raise ValueError('grid dimensions must be positive integers')
    if mode not in {'centered', 'corner', 'checker', 'random'}:
        raise ValueError(f'unsupported spatial stress mode: {mode}')
    if not math.isfinite(strength) or strength <= 0:
        raise ValueError('spatial stress strength must be finite and positive')
    rng = np.random.default_rng(seed)
    pattern = np.ones((cylen, cxlen))
    cy_mid, cx_mid = (cylen - 1) / 2, (cxlen - 1) / 2
    for j in range(cylen):
        for i in range(cxlen):
            d2 = (i - cx_mid) ** 2 + (j - cy_mid) ** 2
            r2 = max(cx_mid, cy_mid) ** 2
            if mode == 'centered':
                # Gaussian hot spot at center
                pattern[j, i] = (
                    strength
                    if r2 == 0
                    else 1 + (strength - 1) * np.exp(-d2 / (r2 * 0.5))
                )
            elif mode == 'corner':
                # Hot in one corner
                if i == 0 and j == 0:
                    pattern[j, i] = strength
                elif i == cxlen - 1 and j == cylen - 1:
                    pattern[j, i] = strength
                else:
                    pattern[j, i] = 0.2
            elif mode == 'checker':
                pattern[j, i] = strength if (i + j) % 2 == 0 else 0.2
            elif mode == 'random':
                pattern[j, i] = rng.uniform(min(0.1, strength), strength)
    return pattern.flatten()


def _component_columns(header, chip_count):
    columns = {name: {} for name in _COMPONENT_TYPES}
    for index, identifier in enumerate(header):
        match = _COMPONENT_COLUMN.fullmatch(identifier)
        if match is None:
            continue
        component, chip_text = match.groups()
        chip_index = int(chip_text)
        if chip_index >= chip_count or chip_index in columns[component]:
            raise ValueError(f'invalid or duplicate component column: {identifier}')
        columns[component][chip_index] = index
    expected = set(range(chip_count))
    for component, by_chip in columns.items():
        if set(by_chip) != expected:
            raise ValueError(
                f'ptrace must contain one {component} column for every grid cell'
            )
    return columns


def _redistribute_row(data, columns, pattern, conservation):
    values = []
    for value in data:
        parsed = float(value)
        if not math.isfinite(parsed) or parsed < 0:
            raise ValueError('ptrace powers must be finite and non-negative')
        values.append(parsed)
    modified = list(values)

    groups = (
        tuple(columns.values())
        if conservation == 'per_component'
        else (dict(
            (chip_index + group_index * len(pattern), column_index)
            for group_index, by_chip in enumerate(columns.values())
            for chip_index, column_index in by_chip.items()
        ),)
    )
    for by_chip in groups:
        ordered = tuple(sorted(by_chip.items()))
        original_total = sum(values[column] for _, column in ordered)
        weighted_total = sum(
            values[column] * pattern[chip_index % len(pattern)]
            for chip_index, column in ordered
        )
        if original_total == 0:
            continue
        if weighted_total <= 0 or not math.isfinite(weighted_total):
            raise ValueError('spatial stress normalization is undefined')
        scale = original_total / weighted_total
        for chip_index, column in ordered:
            modified[column] = (
                values[column] * pattern[chip_index % len(pattern)] * scale
            )

    serialized = [f'{value:.12f}' for value in modified]
    for by_chip in groups:
        ordered = tuple(sorted(by_chip.items()))
        before = sum(values[column] for _, column in ordered)
        after = sum(float(serialized[column]) for _, column in ordered)
        tolerance = max(1.0e-9, abs(before) * 1.0e-10)
        if abs(after - before) > tolerance:
            raise ValueError('serialized spatial stress violates power conservation')
    return serialized


def inject_spatial_power(
    ptrace_path,
    output_path,
    cxlen,
    cylen,
    mode='centered',
    strength=5.0,
    seed=42,
    conservation='per_component',
):
    """Apply a typed, power-conserving synthetic spatial stress pattern."""
    if conservation not in {'per_component', 'global'}:
        raise ValueError('conservation must be per_component or global')
    with open(ptrace_path) as f:
        lines = [line.rstrip('\n') for line in f]
    if len(lines) < 2 or not lines[0].strip():
        raise ValueError('ptrace must contain a header and at least one power row')

    header = lines[0].rstrip('\t').split('\t')
    if len(header) != len(set(header)):
        raise ValueError('ptrace header identities must be unique')
    chip_count = cxlen * cylen
    columns = _component_columns(header, chip_count)
    pattern = make_pattern(cxlen, cylen, mode, strength, seed)
    output_rows = []
    for line in lines[1:]:
        if not line.strip():
            continue
        data = line.rstrip('\t').split('\t')
        if len(data) != len(header):
            raise ValueError(
                f'ptrace header/data width mismatch: {len(header)} != {len(data)}'
            )
        output_rows.append(
            _redistribute_row(data, columns, pattern, conservation)
        )

    os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
    with open(output_path, 'w') as f:
        f.write('\t'.join(header) + '\n')
        for row in output_rows:
            f.write('\t'.join(row) + '\n')

    return output_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', required=True)
    ap.add_argument('--output', required=True)
    ap.add_argument('--cxlen', type=int, default=4)
    ap.add_argument('--cylen', type=int, default=4)
    ap.add_argument('--mode', default='centered', choices=['centered', 'corner', 'checker', 'random'])
    ap.add_argument('--strength', type=float, default=5.0, help='max multiplier (vs 1.0 base)')
    ap.add_argument('--seed', type=int, default=42)
    ap.add_argument('--conservation', default='per_component', choices=['per_component', 'global'])
    args = ap.parse_args()

    out = inject_spatial_power(
        args.input, args.output, args.cxlen, args.cylen, args.mode,
        args.strength, args.seed, args.conservation,
    )
    print(f"Wrote spatial-power ptrace: {out}")
    # Print header + first 20 data values
    with open(out) as f:
        lines = f.readlines()
    print(f"Header has {len(lines[0].split(chr(9)))} columns")
    data = lines[1].rstrip().split('\t')
    print(f"Data row: {data[:15]}...")
    print(f"Total columns: {len(data)}")


if __name__ == "__main__":
    main()
