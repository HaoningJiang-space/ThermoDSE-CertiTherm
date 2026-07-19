"""
CertiTherm exact: Full thermal resistance matrix R via single-block perturbation.

For design d with N blocks, R is N×N where:
  R[i,j] = T_at_block_i - T_ambient when only block j has power = 1W

This gives the linear thermal operator:
  T_d(p) = T_ambient + R · p    (vector form, then T_d = max over blocks)

Used as input to the exact LP-based decision-identifiability oracle.

The R matrix from theory/derive_R.py is only 12x12 (12 selected blocks). For
the decisive experiment we need the FULL R matrix covering all blocks in
the chiplet, not a subset.
"""
import os
import sys
import json
import argparse
import numpy as np

sys.path.insert(0, '/home/ynwang/jhn/DSE/ThermoDSE')


def parse_steady_peak(steady_file):
    """Parse gcc.steady for block name -> temperature."""
    temps = {}
    with open(steady_file) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2:
                name = parts[0]
                try:
                    t = float(parts[1])
                    temps[name] = t
                except ValueError:
                    pass
    return temps


def compute_full_R_matrix(sys_info, sim_path, hotspot_path, run_sh_path, blocks_to_use=None):
    """
    Compute full R matrix for all blocks in the chiplet (type-major, 9-component).
    R[i,j] = T_at_block_i - T_ambient when only block j has power 1W.

    Returns: R, T_ambient, block_list, raw_temps_dict
    """
    import subprocess
    import shutil
    from core.chiplet_eva import chiplet_evaluator

    # 1. Build evaluator + generate ptrace
    ev = chiplet_evaluator(
        hotspot_path=hotspot_path,
        sim_path=sim_path,
        sys_info=sys_info,
        thermal_map=False,
        baseline1=False,
        baseline2=False,
        baseline3=False,
        wkld_idpdt=False,
        clock_freq=1.8e9,
    )
    ev.generate_hardware()
    ev.evaluate()  # writes the type-major ptrace
    area = ev.sys_h * ev.sys_w + ev.IO_die_area_each * 8

    ptrace_path = os.path.join(sim_path, 'ptrace', 'cores_3D.ptrace')
    if not os.path.isfile(ptrace_path):
        return None, None, None, None

    # Backup the uniform ptrace
    backup_dir = '/tmp/R_matrix_backup'
    os.makedirs(backup_dir, exist_ok=True)
    backup_ptrace = os.path.join(backup_dir, 'uniform_backup.ptrace')
    shutil.copy2(ptrace_path, backup_ptrace)

    # Read header to get all block names
    with open(ptrace_path) as f:
        lines = f.readlines()
    header = lines[0].strip().split('\t')
    n_cols = len(header)

    if blocks_to_use is None:
        blocks_to_use = header  # use all blocks

    # 2. T_ambient: run with all-zero ptrace
    zero_row = ['0.0000'] * n_cols
    with open(ptrace_path, 'w') as f:
        f.write('\t'.join(header) + '\n')
        f.write('\t'.join(zero_row) + '\n')
    subprocess.run(
        ['bash', run_sh_path,
         os.path.join(sim_path, 'example.config'),
         os.path.join(sim_path, 'floorplan', 'output_3D.flp'),
         ptrace_path, '0.020', sim_path],
        check=False, capture_output=True, text=True, timeout=180
    )
    ambient_temps = parse_steady_peak(os.path.join(sim_path, 'outputs', 'gcc.steady'))
    T_ambient = float(np.mean(list(ambient_temps.values()))) if ambient_temps else 318.0

    # 3. Find block indices
    block_to_col = {b: i for i, b in enumerate(header)}
    valid_blocks = [b for b in blocks_to_use if b in block_to_col]

    # 4. For each block, perturb its power to 1.0, all others 0
    n_blocks = len(valid_blocks)
    R = np.zeros((n_blocks, n_blocks))
    raw_temps = {}

    for j_idx, target_block in enumerate(valid_blocks):
        perturbed = ['0.0000'] * n_cols
        col_idx = block_to_col[target_block]
        perturbed[col_idx] = '1.0000'
        with open(ptrace_path, 'w') as f:
            f.write('\t'.join(header) + '\n')
            f.write('\t'.join(perturbed) + '\n')

        subprocess.run(
            ['bash', run_sh_path,
             os.path.join(sim_path, 'example.config'),
             os.path.join(sim_path, 'floorplan', 'output_3D.flp'),
             ptrace_path, '0.020', sim_path],
            check=False, capture_output=True, text=True, timeout=180
        )
        temps = parse_steady_peak(os.path.join(sim_path, 'outputs', 'gcc.steady'))
        raw_temps[target_block] = temps

        for i_idx, queried_block in enumerate(valid_blocks):
            t_q = temps.get(queried_block, T_ambient)
            R[i_idx, j_idx] = t_q - T_ambient

    # 5. Restore uniform ptrace
    shutil.copy2(backup_ptrace, ptrace_path)

    return R, T_ambient, valid_blocks, raw_temps


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--sys-info', type=int, nargs=10, required=True,
                    help='10-element chiplet config: xx yy cx cy ci hsa wsa ubf nop dram')
    ap.add_argument('--sim-path', default='/home/ynwang/jhn/DSE/ThermoDSE/tmp')
    ap.add_argument('--hotspot-path', default='/home/ynwang/jhn/DSE/HotSpot')
    ap.add_argument('--output', default=None,
                    help='Output .npy file for the R matrix')
    ap.add_argument('--max-blocks', type=int, default=None,
                    help='Limit number of blocks (for speed; full is slow)')
    args = ap.parse_args()

    run_sh = os.path.join(args.sim_path, 'run.sh')
    output = args.output
    if output is None:
        output = f'/home/ynwang/jhn/DSE/CertiTherm/exact/R_design_{args.sys_info[0]}x{args.sys_info[1]}.npy'

    print(f"Computing full R matrix for design {args.sys_info[:4]}...")
    R, T_amb, blocks, raw = compute_full_R_matrix(
        args.sys_info, args.sim_path, args.hotspot_path, run_sh,
        blocks_to_use=None,
    )
    if R is None:
        print("ERROR: R matrix computation failed")
        return

    if args.max_blocks is not None and len(blocks) > args.max_blocks:
        # Subsample for speed
        idx = np.linspace(0, len(blocks) - 1, args.max_blocks, dtype=int)
        R = R[np.ix_(idx, idx)]
        blocks = [blocks[i] for i in idx]
        print(f"Subsampled to {args.max_blocks} blocks for speed")

    print(f"\n=== R MATRIX (full) ===")
    print(f"  Shape: {R.shape}")
    print(f"  T_ambient: {T_amb:.2f} K")
    print(f"  Diagonal mean (self-R): {np.diag(R).mean():.4f} K/W")
    print(f"  Off-diagonal mean: {(R - np.diag(np.diag(R))).mean():.4f} K/W")
    print(f"  λ_max(R) (spectral): {np.linalg.norm(R, 2):.4f} K/W")
    print(f"  ||R||_1 (max col sum): {np.linalg.norm(R, 1):.4f}")

    # Save R matrix and metadata
    os.makedirs(os.path.dirname(output), exist_ok=True)
    np.save(output, R)
    meta = {
        'sys_info': args.sys_info,
        'T_ambient': T_amb,
        'blocks': blocks,
        'R_diagonal_mean': float(np.diag(R).mean()),
        'R_offdiag_mean': float((R - np.diag(np.diag(R))).mean()),
        'R_lambda_max': float(np.linalg.norm(R, 2)),
        'R_1norm': float(np.linalg.norm(R, 1)),
        'shape': list(R.shape),
    }
    with open(output.replace('.npy', '_meta.json'), 'w') as f:
        json.dump(meta, f, indent=2)
    print(f"\nSaved R to {output}")
    print(f"Saved meta to {output.replace('.npy', '_meta.json')}")


if __name__ == "__main__":
    main()