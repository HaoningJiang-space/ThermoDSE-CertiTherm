"""
CertiTherm Phase B pilot: replace T_uniform with a sampled spatial-stress
maximum in target_function.

The sampled maximum is not a worst-case bound or a safety certificate.  This
module is retained as a stress-test baseline for the exact identifiability
path, and therefore fails closed whenever a sample cannot be evaluated.

Usage:
  from robust_target import make_robust_target
  target_robust, c2_robust = make_robust_target(K=10, mode='centered')
  # Then patch scbo_search.py to use these
"""
import os
import sys
import subprocess
import shutil
import tempfile
import numpy as np

sys.path.insert(0, '/home/ynwang/jhn/DSE/ThermoDSE')
sys.path.insert(0, '/home/ynwang/jhn/DSE/CertiTherm/audit')

try:
    from ..audit.spatial_power_injection import inject_spatial_power
except ImportError:  # direct script execution from the legacy directory
    from spatial_power_injection import inject_spatial_power


def _run_hotspot_peak(sim_path, run_sh_path, ptrace):
    steady = os.path.join(sim_path, 'outputs', 'gcc.steady')
    if os.path.exists(steady):
        os.remove(steady)
    try:
        result = subprocess.run(
            [
                'bash', run_sh_path,
                os.path.join(sim_path, 'example.config'),
                os.path.join(sim_path, 'floorplan', 'output_3D.flp'),
                ptrace, '0.020', sim_path,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return None
    if result.returncode != 0 or not os.path.isfile(steady):
        return None
    temperatures = []
    with open(steady) as stream:
        for line in stream:
            parts = line.strip().split()
            if len(parts) < 2:
                continue
            try:
                value = float(parts[1])
            except ValueError:
                continue
            if np.isfinite(value) and value > 0:
                temperatures.append(value)
    return max(temperatures) if temperatures else None


def compute_T_sample_max(
    sim_path,
    run_sh_path,
    sys_info,
    chiplet_evaluator,
    K=10,
    mode='centered',
    max_strength=5.0,
    seed=42,
):
    """
    Compute the maximum over K power-conserving synthetic stress samples.

    Args:
      sim_path: tmp/ directory
      run_sh_path: path to run.sh wrapper
      sys_info: 10-element chiplet config
      chiplet_evaluator: pre-built evaluator (already ran generate_hardware + evaluate)
      K: number of spatial samples
      mode: 'centered' | 'corner' | 'checker' | 'random'
      max_strength: peak multiplier

    Return the sampled peak maximum, or None if any registered run fails.
    """
    del chiplet_evaluator  # the caller owns evaluator construction and provenance
    if not isinstance(K, int) or isinstance(K, bool) or K <= 0:
        raise ValueError('K must be a positive integer')
    ptrace = os.path.join(sim_path, 'ptrace', 'cores_3D.ptrace')
    if not os.path.isfile(ptrace):
        return None
    xx, yy = sys_info[0], sys_info[1]
    rng = np.random.default_rng(seed)
    temporary_root = os.environ.get('TMPDIR', '/tmp')
    with tempfile.TemporaryDirectory(
        prefix='certitherm-sampled-', dir=temporary_root
    ) as directory:
        backup_ptrace = os.path.join(directory, 'uniform.ptrace')
        shutil.copy2(ptrace, backup_ptrace)
        try:
            uniform_temperature = _run_hotspot_peak(
                sim_path, run_sh_path, ptrace
            )
            if uniform_temperature is None:
                return None
            sampled_temperatures = [uniform_temperature]
            for sample_index in range(K):
                strength = rng.uniform(0.5 * max_strength, max_strength)
                spatial_ptrace = os.path.join(
                    directory, f'spatial-{sample_index}.ptrace'
                )
                inject_spatial_power(
                    backup_ptrace,
                    spatial_ptrace,
                    cxlen=xx,
                    cylen=yy,
                    mode=mode,
                    strength=strength,
                    seed=seed + sample_index * 17,
                    conservation='per_component',
                )
                shutil.copy2(spatial_ptrace, ptrace)
                temperature = _run_hotspot_peak(
                    sim_path, run_sh_path, ptrace
                )
                if temperature is None:
                    return None
                sampled_temperatures.append(temperature)
            return max(sampled_temperatures)
        finally:
            shutil.copy2(backup_ptrace, ptrace)


def compute_T_robust(*args, **kwargs):
    """Compatibility alias; the returned value is only a sampled maximum."""

    return compute_T_sample_max(*args, **kwargs)


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
        # Compute a sampled stress maximum with K samples.
        T_r = compute_T_robust(sim_path, run_sh, sys_info, evaluator, K=K, mode=mode)
        if T_r is None:
            raise RuntimeError('sampled thermal constraint is unresolved')
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
