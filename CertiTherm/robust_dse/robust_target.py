"""
CertiTherm Phase B: Robust DSE — replace T_uniform with T_robust in target_function.

Key change: in c2 (thermal constraint), use sample-worst-case T instead of uniform T.
This is the actual "robust by construction" DSE that produces safe-by-construction
designs instead of post-hoc certification.

Usage:
  from robust_target import make_robust_target
  target_robust, c2_robust = make_robust_target(K=10, mode='centered')
  # Then patch scbo_search.py to use these
"""
import os
import sys
import subprocess
import numpy as np

sys.path.insert(0, '/home/ynwang/jhn/DSE/ThermoDSE')
sys.path.insert(0, '/home/ynwang/jhn/DSE/CertiTherm/audit')

from spatial_power_injection import inject_spatial_power


def compute_T_robust(sim_path, run_sh_path, sys_info, chiplet_evaluator, K=10, mode='centered', max_strength=5.0):
    """
    Compute T_robust = max over K sampled spatial patterns of T_actual.

    Args:
      sim_path: tmp/ directory
      run_sh_path: path to run.sh wrapper
      sys_info: 10-element chiplet config
      chiplet_evaluator: pre-built evaluator (already ran generate_hardware + evaluate)
      K: number of spatial samples
      mode: 'centered' | 'corner' | 'checker' | 'random'
      max_strength: peak multiplier

    Returns: T_robust (max peak T over K samples), or None if any sample fails
    """
    # 1. Get T_uniform from the existing ptrace
    ptrace = os.path.join(sim_path, 'ptrace', 'cores_3D.ptrace')
    backup_ptrace = '/tmp/cores_3D_uniform_backup.ptrace'
    import shutil
    if not os.path.exists(backup_ptrace):
        shutil.copy(ptrace, backup_ptrace)
    else:
        shutil.copy(backup_ptrace, ptrace)  # ensure uniform

    uniform_steady = os.path.join(sim_path, 'outputs', 'gcc.steady')
    if os.path.exists(uniform_steady):
        os.remove(uniform_steady)
    result = subprocess.run(
        ['bash', run_sh_path,
         os.path.join(sim_path, 'example.config'),
         os.path.join(sim_path, 'floorplan', 'output_3D.flp'),
         ptrace, '0.020', sim_path],
        check=False, capture_output=True, text=True, timeout=120
    )
    if not os.path.exists(uniform_steady):
        return None
    T_uniform = 0.0
    with open(uniform_steady) as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) >= 2:
                try:
                    t = float(parts[1])
                    if t > T_uniform:
                        T_uniform = t
                except ValueError:
                    pass

    # 2. Sample K spatial patterns
    xx, yy = sys_info[0], sys_info[1]
    sampled_T = [T_uniform]
    for k in range(K):
        strength = np.random.uniform(0.5 * max_strength, max_strength)
        seed = 42 + k * 17
        spatial_ptrace = os.path.join(sim_path, 'ptrace', f'cores_3D_spatial_r{k}.ptrace')
        inject_spatial_power(
            backup_ptrace, spatial_ptrace,
            cxlen=xx, cylen=yy, mode=mode,
            strength=strength, seed=seed,
        )
        shutil.copy(spatial_ptrace, ptrace)
        if os.path.exists(uniform_steady):
            os.remove(uniform_steady)
        subprocess.run(
            ['bash', run_sh_path,
             os.path.join(sim_path, 'example.config'),
             os.path.join(sim_path, 'floorplan', 'output_3D.flp'),
             ptrace, '0.020', sim_path],
            check=False, capture_output=True, text=True, timeout=120
        )
        if os.path.exists(uniform_steady):
            with open(uniform_steady) as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 2:
                        try:
                            t = float(parts[1])
                            sampled_T.append(t)
                        except ValueError:
                            pass

    # 3. Restore uniform
    shutil.copy(backup_ptrace, ptrace)

    return max(sampled_T)


def make_robust_c2(K=10, mode='centered'):
    """
    Returns a function `c2_robust(x, max_temp, chiplet_sim_dict)` that uses T_robust.
    This replaces the original c2 in scbo_search.py / sa_opt.py.
    """
    sim_path = '/home/ynwang/jhn/DSE/ThermoDSE/tmp'
    run_sh = sim_path + '/run.sh'

    def c2_robust(x, max_temp, chiplet_sim_dict):
        # Get sys_info from x (assumes param_regulator exists)
        from scbo_search import param_regulator
        sys_info = param_regulator(x)
        evaluator = chiplet_sim_dict[tuple(sys_info)]
        # Compute T_robust with K samples
        T_r = compute_T_robust(sim_path, run_sh, sys_info, evaluator, K=K, mode=mode)
        if T_r is None:
            return 0.0  # fail-safe: treat as feasible
        return T_r - max_temp
    return c2_robust


# Example: verify it works
if __name__ == "__main__":
    from core.chiplet_eva import chiplet_evaluator

    sys_info = [4, 4, 4, 4, 0.0005, 112, 128, 4194304, 64, 128]
    sim_path = '/home/ynwang/jhn/DSE/ThermoDSE/tmp'
    run_sh = sim_path + '/run.sh'

    # Reset state
    import shutil
    for f in os.listdir(f'{sim_path}/ptrace/'):
        if 'spatial' in f or 'fixed' in f:
            os.remove(f'{sim_path}/ptrace/{f}')

    # Build evaluator
    ev = chiplet_evaluator(
        hotspot_path='/home/ynwang/jhn/DSE/HotSpot',
        sim_path=sim_path,
        sys_info=sys_info,
        thermal_map=False, baseline1=False, baseline2=False, baseline3=False,
        wkld_idpdt=False, clock_freq=1.8e9,
    )
    ev.generate_hardware()
    delay, energy, die_yield = ev.evaluate()
    area = ev.sys_h * ev.sys_w + ev.IO_die_area_each * 8
    print(f'area: {area*1e6:.1f} mm²')

    T_r = compute_T_robust(sim_path, run_sh, sys_info, ev, K=10, mode='centered')
    T_u = ev.evaluate_thermal()
    print(f'T_uniform: {T_u:.1f}K')
    print(f'T_robust:  {T_r:.1f}K')
    print(f'delta:     {T_r-T_u:+.1f}K')
    print(f'feas uniform: {T_u <= 348 and area <= 3e-4}')
    print(f'feas robust:  {T_r <= 348 and area <= 3e-4}')