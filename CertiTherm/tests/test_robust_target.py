from __future__ import annotations

import subprocess
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

from CertiTherm.audit.spatial_power_injection import _COMPONENT_TYPES
from CertiTherm.robust_dse import robust_target


class SampledThermalTargetTest(unittest.TestCase):
    @staticmethod
    def _make_simulation_root(root: Path) -> tuple[Path, bytes]:
        for relative in ('ptrace', 'outputs', 'floorplan'):
            (root / relative).mkdir(parents=True, exist_ok=True)
        header = [
            'interposer', 'interposer_e0', 'interposer_e1',
            'interposer_e2', 'interposer_e3',
        ]
        header.extend(f'{component}_0' for component in _COMPONENT_TYPES)
        values = ['0.0'] * len(header)
        for index in range(5, len(values)):
            values[index] = '1.0'
        payload = (
            '\t'.join(header) + '\n' + '\t'.join(values) + '\n'
        ).encode()
        (root / 'ptrace' / 'cores_3D.ptrace').write_bytes(payload)
        (root / 'example.config').write_text('', encoding='utf-8')
        (root / 'floorplan' / 'output_3D.flp').write_text('', encoding='utf-8')
        (root / 'run.sh').write_text('', encoding='utf-8')
        return root, payload

    def test_nonzero_hotspot_status_is_unresolved_and_ptrace_is_restored(self):
        with tempfile.TemporaryDirectory() as directory:
            root, original = self._make_simulation_root(Path(directory))
            failed = subprocess.CompletedProcess([], 2, '', 'failed')
            with mock.patch.object(robust_target.subprocess, 'run', return_value=failed):
                result = robust_target.compute_T_sample_max(
                    str(root), str(root / 'run.sh'), [1, 1], object(), K=2
                )
            self.assertIsNone(result)
            self.assertEqual(
                (root / 'ptrace' / 'cores_3D.ptrace').read_bytes(), original
            )

    def test_constraint_wrapper_raises_instead_of_marking_failure_feasible(self):
        fake_search = types.ModuleType('scbo_search')
        fake_search.param_regulator = lambda value: value
        constraint = robust_target.make_robust_c2(K=1)
        with mock.patch.dict('sys.modules', {'scbo_search': fake_search}):
            with mock.patch.object(robust_target, 'compute_T_robust', return_value=None):
                with self.assertRaisesRegex(RuntimeError, 'unresolved'):
                    constraint((1, 1), 348.0, {(1, 1): object()})


if __name__ == '__main__':
    unittest.main()
