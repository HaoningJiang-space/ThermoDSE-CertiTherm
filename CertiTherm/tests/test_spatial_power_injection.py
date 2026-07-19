from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from CertiTherm.audit.spatial_power_injection import (
    _COMPONENT_TYPES,
    inject_spatial_power,
)


class SpatialPowerInjectionTest(unittest.TestCase):
    def _write_ptrace(self, root: Path, xlen: int, ylen: int) -> Path:
        chip_count = xlen * ylen
        header = [
            'interposer', 'interposer_e0', 'interposer_e1',
            'interposer_e2', 'interposer_e3',
        ]
        header.extend(
            f'{component}_{chip}'
            for component in _COMPONENT_TYPES
            for chip in range(chip_count)
        )
        header.extend(('blockX_0', 'eblk0'))
        values = [0.5, 0.0, 0.0, 0.0, 0.0]
        values.extend(
            1.0 + component_index / 10.0
            for component_index, _ in enumerate(_COMPONENT_TYPES)
            for _ in range(chip_count)
        )
        values.extend((0.0, 0.0))
        path = root / 'input.ptrace'
        path.write_text(
            '\t'.join(header) + '\n' +
            '\t'.join(str(value) for value in values) + '\n',
            encoding='utf-8',
        )
        return path

    @staticmethod
    def _read(path: Path):
        lines = path.read_text(encoding='utf-8').splitlines()
        return lines[0].split('\t'), tuple(float(value) for value in lines[1].split('\t'))

    def test_type_major_header_is_mapped_and_component_totals_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._write_ptrace(root, 3, 3)
            output = root / 'output.ptrace'
            inject_spatial_power(source, output, 3, 3, strength=5.0)
            header, before = self._read(source)
            _, after = self._read(output)

            for component in _COMPONENT_TYPES:
                indices = [header.index(f'{component}_{chip}') for chip in range(9)]
                self.assertAlmostEqual(
                    sum(before[index] for index in indices),
                    sum(after[index] for index in indices),
                    places=8,
                )
                center = header.index(f'{component}_4')
                corner = header.index(f'{component}_0')
                self.assertGreater(
                    after[center] / before[center],
                    after[corner] / before[corner],
                )

            self.assertEqual(after[header.index('interposer')], 0.5)
            self.assertEqual(after[header.index('blockX_0')], 0.0)

    def test_seeded_random_stress_is_replayable(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._write_ptrace(root, 2, 2)
            first = root / 'first.ptrace'
            replay = root / 'replay.ptrace'
            other = root / 'other.ptrace'
            inject_spatial_power(source, first, 2, 2, mode='random', seed=7)
            inject_spatial_power(source, replay, 2, 2, mode='random', seed=7)
            inject_spatial_power(source, other, 2, 2, mode='random', seed=8)
            self.assertEqual(first.read_bytes(), replay.read_bytes())
            self.assertNotEqual(first.read_bytes(), other.read_bytes())

    def test_single_cell_and_malformed_identity_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = self._write_ptrace(root, 1, 1)
            output = root / 'output.ptrace'
            inject_spatial_power(source, output, 1, 1, strength=5.0)
            header, before = self._read(source)
            _, after = self._read(output)
            for component in _COMPONENT_TYPES:
                index = header.index(f'{component}_0')
                self.assertAlmostEqual(before[index], after[index], places=10)

            malformed = root / 'malformed.ptrace'
            malformed.write_text(
                source.read_text(encoding='utf-8').replace('io_3_0', 'missing_0'),
                encoding='utf-8',
            )
            with self.assertRaisesRegex(ValueError, 'io_3'):
                inject_spatial_power(malformed, root / 'rejected.ptrace', 1, 1)


if __name__ == '__main__':
    unittest.main()
