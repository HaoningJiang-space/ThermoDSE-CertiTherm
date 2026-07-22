"""
CertiTherm Theory: Compute the thermal resistance matrix R from HotSpot
by single-block perturbation.

Theorem: T_actual = T_uniform + R · (p - p_uniform·1)
where R is the block-to-block thermal resistance matrix.

Method: For each block i, set p_i = 1, all others = 0, run HotSpot, get
steady-state temps. Then R[:,i] = T_at_block_j - T_ambient.

Output: R matrix as numpy array, R[i,j] = thermal resistance from block j to block i.
"""
import os
import sys
import subprocess
import numpy as np
import json
import argparse
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
THERMODSE_ROOT = REPO_ROOT / 'ThermoDSE'
sys.path.insert(0, str(THERMODSE_ROOT))


def parse_steady_temps(steady_file):
    """Parse gcc.steady for block name → temperature."""
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


def compute_R_matrix(sim_path, run_sh_path, blocks_to_perturb):
    """
    Compute R[i,j] for i,j in blocks_to_perturb.

    Strategy:
    1. Run baseline (uniform power = 0). All temps should be T_ambient (~318K).
    2. For each block j, set ptrace[j] = small_value, all others 0.
       Run HotSpot. Read T_i at all blocks. R[:,j] = (T_i - T_ambient) / p_j.
    3. Repeat for all j.

    Note: R[i,j] has units of K/W. We use a small p_j (e.g., 1W) so
    T_i - T_ambient is in K = R[i,j] × 1W directly.
    """
    # First, save the current ptrace (which has uniform power from chiplet_evaluator)
    ptrace_uniform = os.path.join(sim_path, 'ptrace', 'cores_3D.ptrace')
    backup_ptrace = '/tmp/cores_3D_uniform_backup.ptrace'
    if not os.path.exists(backup_ptrace):
        import shutil
        shutil.copy(ptrace_uniform, backup_ptrace)

    # Read the header to find block names
    with open(backup_ptrace) as f:
        header = f.readline().strip().split('\t')
        f.readline()
    n_cols = len(header)

    # Find indices of blocks_to_perturb
    block_indices = []
    for b in blocks_to_perturb:
        if b in header:
            block_indices.append((header.index(b), b))
        else:
            print(f"  WARN: block '{b}' not in ptrace header")

    R = np.zeros((len(block_indices), len(block_indices)))
    raw_temps = {}

    # First, get T_ambient baseline (run with all zeros)
    print("  Running T_ambient baseline...")
    zero_row = ['0.0000'] * n_cols
    with open(ptrace_uniform, 'w') as f:
        f.write('\t'.join(header) + '\n')
        f.write('\t'.join(zero_row) + '\n')
    subprocess.run(
        ['bash', run_sh_path,
         os.path.join(sim_path, 'example.config'),
         os.path.join(sim_path, 'floorplan', 'output_3D.flp'),
         ptrace_uniform, '0.020', sim_path],
        check=False, capture_output=True, text=True, timeout=120
    )
    ambient_temps = parse_steady_temps(os.path.join(sim_path, 'outputs', 'gcc.steady'))
    T_amb = np.mean(list(ambient_temps.values())) if ambient_temps else 318.0
    print(f"  T_ambient (avg) = {T_amb:.2f} K")

    # Now perturb each block
    for i, (col_idx, block_name) in enumerate(block_indices):
        # Set this block's power to 1.0, all others 0
        perturbed = ['0.0000'] * n_cols
        perturbed[col_idx] = '1.0000'
        with open(ptrace_uniform, 'w') as f:
            f.write('\t'.join(header) + '\n')
            f.write('\t'.join(perturbed) + '\n')

        # Run HotSpot
        subprocess.run(
            ['bash', run_sh_path,
             os.path.join(sim_path, 'example.config'),
             os.path.join(sim_path, 'floorplan', 'output_3D.flp'),
             ptrace_uniform, '0.020', sim_path],
            check=False, capture_output=True, text=True, timeout=120
        )
        temps = parse_steady_temps(os.path.join(sim_path, 'outputs', 'gcc.steady'))
        raw_temps[block_name] = temps

        # Extract R[:, i] (column i corresponds to perturbing block i)
        for j, (_, name_j) in enumerate(block_indices):
            t_j = temps.get(name_j, T_amb)
            R[j, i] = t_j - T_amb  # R[i,j] = T_at_block_i when block_j=1
            # = R_ij (thermal resistance from j to i)

    # Restore uniform ptrace
    import shutil
    shutil.copy(backup_ptrace, ptrace_uniform)

    return R, T_amb, block_indices, raw_temps


def main():
    """Compute R matrix for a representative design and analyze its spectral properties."""
    from core.chiplet_eva import chiplet_evaluator

    parser = argparse.ArgumentParser()
    parser.add_argument('--sim-path', required=True)
    parser.add_argument(
        '--hotspot-path',
        default=str(REPO_ROOT / '.build' / 'hotspot'),
    )
    parser.add_argument(
        '--output-dir',
        default=str(Path(__file__).resolve().parent),
    )
    args = parser.parse_args()

    sys_info = [4, 4, 4, 4, 0.0005, 112, 128, 4194304, 64, 128]  # paper's TESA SA ideal best

    sim_path = args.sim_path
    run_sh = os.path.join(sim_path, 'run.sh')

    # Generate the floorplan
    ev = chiplet_evaluator(
        hotspot_path=args.hotspot_path,
        sim_path=sim_path,
        sys_info=sys_info,
        thermal_map=False,
        baseline1=False, baseline2=False, baseline3=False,
        wkld_idpdt=False,
        clock_freq=1.8e9,
    )
    ev.generate_hardware()

    # Read ptrace header to get block names
    ptrace = os.path.join(sim_path, 'ptrace', 'cores_3D.ptrace')
    with open(ptrace) as f:
        header = f.readline().strip().split('\t')
    # Filter to just the inner block names (not interposer, eblk*, blockX*, etc.)
    # Inner blocks: mtxu_*, vecu_*, ubuf_*, ibuf_*, obuf_*, io_*
    inner_blocks = [b for b in header if any(
        b.startswith(prefix) for prefix in ['mtxu_', 'vecu_', 'ubuf_', 'ibuf_', 'obuf_', 'io_']
    )]
    print(f"Found {len(inner_blocks)} inner blocks: {inner_blocks[:5]}...")

    # Compute R matrix (inner blocks only for speed)
    # Limit to first 12 blocks to keep eval time manageable
    blocks_subset = inner_blocks[:12]
    print(f"Computing R matrix for {len(blocks_subset)} blocks (1 HotSpot run per block + 1 baseline)")

    R, T_amb, block_info, _raw_temps = compute_R_matrix(
        sim_path, run_sh, blocks_subset
    )

    print(f"\n=== R MATRIX (K/W) ===")
    print(f"  Shape: {R.shape}")
    print(f"  T_ambient: {T_amb:.2f} K")
    print(f"  Diagonal mean (self-resistance): {np.diag(R).mean():.4f} K/W")
    print(f"  Off-diagonal mean (cross-resistance): {(R - np.diag(np.diag(R))).mean():.4f} K/W")
    print(f"  Max cross-R: {np.max(R - np.diag(np.diag(R))):.4f} K/W")
    print(f"  ||R||_F (Frobenius): {np.linalg.norm(R, 'fro'):.4f}")
    print(f"  ||R||_1 (max col sum): {np.linalg.norm(R, 1):.4f}")
    print(f"  ||R||_inf (max row sum): {np.linalg.norm(R, np.inf):.4f}")
    eigvals = np.linalg.eigvals(R)
    print(f"  λ_max(R) (spectral norm): {np.max(np.abs(eigvals)):.4f}")
    print(f"  λ_min(R): {np.min(np.real(eigvals)):.4f}")

    # Save R matrix
    out_dir = args.output_dir
    os.makedirs(out_dir, exist_ok=True)
    np.save(os.path.join(out_dir, 'R_matrix_paper_design.npy'), R)
    with open(os.path.join(out_dir, 'R_matrix_meta.json'), 'w') as f:
        json.dump({
            'sys_info': sys_info,
            'T_ambient': T_amb,
            'blocks': [b for _, b in block_info],
            'R_diagonal_mean': float(np.diag(R).mean()),
            'R_offdiag_mean': float((R - np.diag(np.diag(R))).mean()),
            'R_max_offdiag': float(np.max(R - np.diag(np.diag(R)))),
            'R_frobenius': float(np.linalg.norm(R, 'fro')),
            'R_1norm': float(np.linalg.norm(R, 1)),
            'R_infnorm': float(np.linalg.norm(R, np.inf)),
            'lambda_max': float(np.max(np.abs(eigvals))),
            'lambda_min': float(np.min(np.real(eigvals))),
        }, f, indent=2)

    # Predict g for various sigma_W values
    print(f"\n=== CLOSED-FORM g PREDICTIONS ===")
    print(f"  g(C, σ_W) = σ_W × λ_max(R) × P_total")
    print(f"  P_total ≈ sum of all block powers (from ptrace)")
    # Read P_total from the ptrace data row (uniform)
    ptrace_vals = [float(x) for x in open(ptrace).readlines()[1].strip().split('\t')]
    P_total = sum(ptrace_vals)
    print(f"  P_total = {P_total:.4f} W")
    lambda_max = float(np.max(np.abs(eigvals)))
    print(f"  λ_max(R) = {lambda_max:.4f} K/W")
    for sigma in [0.1, 0.2, 0.3, 0.4, 0.5]:
        g = sigma * lambda_max * P_total
        print(f"  σ_W = {sigma:.1f}: g = {g:.2f} K")


if __name__ == "__main__":
    main()
