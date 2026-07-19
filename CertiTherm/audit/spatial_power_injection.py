"""
CertiTherm: Spatial power injection (Stage 2 of audit)

Inject spatial power variation by multiplying the ptrace file's per-block
values by a spatial pattern (centered hot spot, edge cool, etc.). This
simulates what real SAIF/VCD + post-route power would look like — non-uniform
across chiplet blocks.

Then re-run HotSpot to get the spatial-power peak temperature.

Pattern modes:
  - centered: hot spot in middle, cooler at edges (Gaussian falloff)
  - corner: hot in one corner (workload concentrated on one chiplet)
  - checker: alternating hot/cold (representing interleaved workloads)
  - random: per-block random (worst case)
"""
import os
import sys
import numpy as np
import argparse

sys.path.insert(0, '/home/ynwang/jhn/DSE/ThermoDSE')


def make_pattern(cxlen, cylen, mode='centered', strength=5.0, seed=42):
    """Generate a spatial power multiplier pattern.

    Returns a 1D array of length cxlen*cylen (per-block multipliers)
    + 5 interposer multipliers at front.
    """
    np.random.seed(seed)
    pattern = np.ones((cylen, cxlen))
    cy_mid, cx_mid = (cylen - 1) / 2, (cxlen - 1) / 2
    for j in range(cylen):
        for i in range(cxlen):
            d2 = (i - cx_mid) ** 2 + (j - cy_mid) ** 2
            r2 = max(cx_mid, cy_mid) ** 2
            if mode == 'centered':
                # Gaussian hot spot at center
                pattern[j, i] = 1 + (strength - 1) * np.exp(-d2 / (r2 * 0.5))
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
                pattern[j, i] = np.random.uniform(0.1, strength)
    return pattern.flatten()


def inject_spatial_power(ptrace_path, output_path, cxlen, cylen, mode='centered', strength=5.0, seed=42):
    """Read ptrace, apply spatial pattern, write to output."""
    with open(ptrace_path) as f:
        lines = f.readlines()

    header = lines[0].rstrip().split('\t')
    # Header structure: interposer*5, then mtxu/vecu/ubuf/ibuf/obuf/io for each (j,i)
    # Number of NAME_LIST_3D blocks: 6 (mtxu,vecu,ubuf,ibuf,obuf,io) * cxlen*cylen each
    # + blockXY/blockY/blockX filler + eblk0..3

    # The data line: 5 interposer + N_blocks * cxlen * cylen + filler + eblk0..3
    data = lines[1].rstrip().split('\t')
    n_header = len(header)
    n_data = len(data)
    assert n_header == n_data, f'header={n_header}, data={n_data}'

    # Apply pattern to all per-block values (skip first 5 interposer)
    pattern = make_pattern(cxlen, cylen, mode, strength, seed)
    # The 5 interposer values are uniform — don't modify them
    modified = list(data[:5])
    # After interposer, the data is per-block (mtxu_*, vecu_*, etc.) for each chiplet grid position
    # Each chiplet grid position has 6 block types (NAME_LIST_3D has 6 entries)
    n_block_types = 6
    n_chips = cxlen * cylen
    expected_per_block = n_chips * n_block_types
    remaining = len(data) - 5
    # Interleave: for each (i,j), all 6 block types get the same multiplier
    for chip_idx in range(n_chips):
        mult = pattern[chip_idx] if chip_idx < len(pattern) else 1.0
        for bt in range(n_block_types):
            idx = 5 + chip_idx * n_block_types + bt
            if idx < len(data):
                try:
                    val = float(data[idx]) * mult
                    modified.append(f'{val:.4f}')
                except (ValueError, IndexError):
                    modified.append(data[idx])
    # Append any remaining (filler, eblk0..3) unchanged
    used = 5 + n_chips * n_block_types
    for i in range(used, len(data)):
        modified.append(data[i])

    # Write
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, 'w') as f:
        f.write('\t'.join(header) + '\n')
        f.write('\t'.join(modified) + '\n')

    return output_path


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', default='/home/ynwang/jhn/DSE/ThermoDSE/tmp/ptrace/cores_3D.ptrace')
    ap.add_argument('--output', default='/home/ynwang/jhn/DSE/CertiTherm/data/cores_3D_spatial.ptrace')
    ap.add_argument('--cxlen', type=int, default=4)
    ap.add_argument('--cylen', type=int, default=4)
    ap.add_argument('--mode', default='centered', choices=['centered', 'corner', 'checker', 'random'])
    ap.add_argument('--strength', type=float, default=5.0, help='max multiplier (vs 1.0 base)')
    ap.add_argument('--seed', type=int, default=42)
    args = ap.parse_args()

    out = inject_spatial_power(args.input, args.output, args.cxlen, args.cylen, args.mode, args.strength, args.seed)
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