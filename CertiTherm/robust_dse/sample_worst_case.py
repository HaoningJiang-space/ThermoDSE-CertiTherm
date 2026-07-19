"""Power-conserving sampled spatial-stress pilot for CertiTherm.

The maximum over finitely many synthetic samples is an empirical stress
statistic.  It is not a supremum, a PAC worst-case bound, or a thermal safety
certificate.  Claim-bearing certification belongs to the exact
identifiability path; this module supplies only a comparison baseline.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path

import numpy as np

try:
    from ..audit.spatial_power_injection import inject_spatial_power
    from .robust_target import _run_hotspot_peak
except ImportError:  # direct script execution from the legacy directory
    from spatial_power_injection import inject_spatial_power
    from robust_target import _run_hotspot_peak


def _unresolved(sys_info, reason, *, area_mm2=None, expected=0, observed=0):
    return {
        'schema_version': 'certitherm.sampled-spatial-stress.v1',
        'status': 'UNRESOLVED',
        'unresolved_reason': reason,
        'sys_info': list(sys_info),
        'area_mm2': area_mm2,
        'T_uniform': None,
        'T_sample_max': None,
        'T_samples': [],
        'sample_count_expected': expected,
        'sample_count_observed': observed,
        'stress_semantics': 'POWER_CONSERVING_SYNTHETIC_NOT_A_CERTIFICATE',
    }


def sample_worst_case_T(
    sys_info,
    sim_path,
    hotspot_path,
    run_sh_path,
    K=10,
    mode='centered',
    max_strength=5.0,
    peak_T_budget=348.0,
    area_budget_m2=3e-4,
    seed=42,
):
    """Return a fail-closed sampled stress receipt.

    The legacy function name is retained for callers.  The receipt deliberately
    uses ``T_sample_max`` and never presents the statistic as a bound.
    """

    if not isinstance(K, int) or isinstance(K, bool) or K <= 0:
        raise ValueError('K must be a positive integer')
    try:
        from core.chiplet_eva import chiplet_evaluator

        evaluator = chiplet_evaluator(
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
        evaluator.generate_hardware()
        evaluator.evaluate()
        area = evaluator.sys_h * evaluator.sys_w + evaluator.IO_die_area_each * 8
    except Exception as error:
        return _unresolved(
            sys_info,
            f'EVALUATOR_FAILURE:{type(error).__name__}',
            expected=K,
        )

    ptrace_path = os.path.join(sim_path, 'ptrace', 'cores_3D.ptrace')
    if not os.path.isfile(ptrace_path):
        return _unresolved(
            sys_info,
            'MISSING_UNIFORM_PTRACE',
            area_mm2=area * 1e6,
            expected=K,
        )

    rng = np.random.default_rng(seed)
    temporary_root = os.environ.get('TMPDIR', '/tmp')
    with tempfile.TemporaryDirectory(
        prefix='certitherm-stress-', dir=temporary_root
    ) as directory:
        backup_ptrace = os.path.join(directory, 'uniform.ptrace')
        shutil.copy2(ptrace_path, backup_ptrace)
        samples = []
        try:
            uniform_temperature = _run_hotspot_peak(
                sim_path, run_sh_path, ptrace_path
            )
            if uniform_temperature is None:
                return _unresolved(
                    sys_info,
                    'UNIFORM_THERMAL_RUN_FAILURE',
                    area_mm2=area * 1e6,
                    expected=K,
                )
            for sample_index in range(K):
                strength = rng.uniform(0.5 * max_strength, max_strength)
                spatial_ptrace = os.path.join(
                    directory, f'spatial-{sample_index}.ptrace'
                )
                inject_spatial_power(
                    backup_ptrace,
                    spatial_ptrace,
                    cxlen=sys_info[0],
                    cylen=sys_info[1],
                    mode=mode,
                    strength=strength,
                    seed=seed + sample_index * 17,
                    conservation='per_component',
                )
                shutil.copy2(spatial_ptrace, ptrace_path)
                temperature = _run_hotspot_peak(
                    sim_path, run_sh_path, ptrace_path
                )
                if temperature is None:
                    return _unresolved(
                        sys_info,
                        'SPATIAL_THERMAL_RUN_FAILURE',
                        area_mm2=area * 1e6,
                        expected=K,
                        observed=len(samples),
                    )
                samples.append(temperature)
        finally:
            shutil.copy2(backup_ptrace, ptrace_path)

    sample_max = max([uniform_temperature, *samples])
    uniform_feasible = (
        uniform_temperature <= peak_T_budget and area <= area_budget_m2
    )
    sampled_feasible = sample_max <= peak_T_budget and area <= area_budget_m2
    return {
        'schema_version': 'certitherm.sampled-spatial-stress.v1',
        'status': 'RESOLVED_STRESS_PILOT',
        'unresolved_reason': None,
        'sys_info': list(sys_info),
        'area_mm2': area * 1e6,
        'T_uniform': uniform_temperature,
        'T_sample_max': sample_max,
        'T_samples': samples,
        'sample_count_expected': K,
        'sample_count_observed': len(samples),
        'uniform_feasible': uniform_feasible,
        'sampled_feasible': sampled_feasible,
        'flip_under_sampled_stress': uniform_feasible != sampled_feasible,
        'stress_semantics': 'POWER_CONSERVING_SYNTHETIC_NOT_A_CERTIFICATE',
        'seed': seed,
        'mode': mode,
        'maximum_pattern_strength': max_strength,
    }


def main():
    parser = argparse.ArgumentParser()
    repository = Path(__file__).resolve().parents[2]
    parser.add_argument(
        '--thermodse-root',
        default=os.environ.get('THERMODSE_ROOT', str(repository / 'ThermoDSE')),
    )
    parser.add_argument('--sim-path', default=None)
    parser.add_argument('--hotspot-path', required=True)
    parser.add_argument('--K', type=int, default=10)
    parser.add_argument('--mode', default='centered')
    parser.add_argument('--seed', type=int, default=42)
    parser.add_argument(
        '--output',
        default=str(repository / 'CertiTherm' / 'results' / 'sampled_stress_eval.json'),
    )
    arguments = parser.parse_args()
    thermodse_root = Path(arguments.thermodse_root).resolve()
    sys.path.insert(0, str(thermodse_root))
    sim_path = arguments.sim_path or str(thermodse_root / 'tmp')
    run_sh = os.path.join(sim_path, 'run.sh')

    test_designs = [
        [7, 3, 1, 1, 0.0014, 144, 128, 524288, 144, 128],
        [6, 2, 6, 2, 0.0005, 128, 256, 4194304, 128, 128],
        [4, 4, 4, 4, 0.0005, 112, 128, 4194304, 64, 128],
        [5, 4, 1, 2, 0.0005, 208, 128, 1048576, 240, 128],
        [4, 5, 2, 1, 0.0017, 128, 128, 1048576, 112, 224],
        [6, 3, 6, 3, 0.0005, 112, 128, 4194304, 64, 128],
        [2, 2, 1, 1, 0.0005, 64, 64, 524288, 64, 128],
        [3, 3, 3, 3, 0.001, 128, 128, 1048576, 128, 128],
    ]
    results = [
        sample_worst_case_T(
            design,
            sim_path,
            arguments.hotspot_path,
            run_sh,
            K=arguments.K,
            mode=arguments.mode,
            seed=arguments.seed,
        )
        for design in test_designs
    ]
    output = Path(arguments.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(results, indent=2, sort_keys=True, allow_nan=False) + '\n',
        encoding='utf-8',
    )
    unresolved = sum(result['status'] == 'UNRESOLVED' for result in results)
    print(json.dumps({'output': str(output), 'unresolved': unresolved}))
    return 0 if unresolved == 0 else 2


if __name__ == '__main__':
    raise SystemExit(main())
