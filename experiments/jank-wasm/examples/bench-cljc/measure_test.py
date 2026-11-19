"""AI-assisted normal/empty/error checks for benchmark correctness gates."""
import sys
import unittest
from unittest.mock import patch
from pathlib import Path
import tempfile
import importlib.util

sys.dont_write_bytecode = True
import measure

spec = importlib.util.spec_from_file_location('verify_mem2', measure.ROOT / 'scripts/verify-bench-mem2.py')
verify_mem2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(verify_mem2)


class ParserTests(unittest.TestCase):
    def fixture(self):
        output = 'STARTUP ms=10\nINIT clock-ms=100\nENTRY clock-ms=120\n'
        for name, checksum in measure.EXPECTED.items():
            output += f'BENCH {name} checksum={checksum} first-ms=2 median-ms=1\n'
            output += f'SAMPLES {name} ' + ','.join(['1'] * 10) + '\n'
        return output + 'BENCH PASS\nFIRST_ENTRY ms=100 gc-disabled=0\n'

    def test_normal(self):
        result = measure.parse(self.fixture(), 0, False)
        self.assertEqual(len(result['kernels']), 6)
        self.assertEqual(result['init_to_entry_ms'], 20)
        self.assertEqual(result['pre_runtime_startup_ms'], 10)

    def test_empty(self):
        with self.assertRaises(ValueError):
            measure.parse('', 0)

    def test_wasm_variants(self):
        for bits in ('32', '64', '64-mem2'):
            for variant in ('spill', 'unsafe'):
                target = f'wasm{bits}-{variant}'
                disabled = variant == 'unsafe'
                output = self.fixture().replace('gc-disabled=0', f'gc-disabled={int(disabled)}')
                with self.subTest(target=target), patch.object(measure.subprocess, 'run') as run:
                    run.return_value.returncode = 0
                    run.return_value.stdout = output
                    run.return_value.stderr = ''
                    result = measure.execute(target, 'node')
                    expected = ['node', str(measure.wasm_file(bits, variant, 'js'))]
                    if disabled:
                        expected.append('unsafe-no-gc')
                    self.assertEqual(run.call_args.args[0], expected)
                    self.assertEqual(len(measure.parse(result['output'], result['code'], disabled,
                                                      require_startup=True)['kernels']), 6)
                    for invalid in ('', output.replace('BENCH PASS', 'CHECKSUM FAIL')):
                        with self.assertRaises(ValueError):
                            measure.parse(invalid, 0, disabled, require_startup=True)
                    with self.assertRaises(ValueError):
                        measure.parse(output, 0, not disabled, require_startup=True)

    def test_spill_optimizers_and_outputs(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(measure, 'OUT', Path(directory)), \
                patch.object(measure, 'run') as run:
            for bits in ('32', '64'):
                source = measure.wasm_file(bits, 'unsafe', 'wasm')
                source.write_bytes(b'fixture')
                measure.wasm_file(bits, 'unsafe', 'js').write_text(source.name)
                measure.spill(bits)
                output = measure.wasm_file(bits, 'spill', 'wasm')
                self.assertEqual(output.read_bytes(), b'fixture')
                self.assertEqual(measure.wasm_file(bits, 'spill', 'js').read_text(), output.name)
                command = list(map(str, run.call_args.args[1]))
                self.assertEqual(any(x.startswith('SPILL_WASM_OPT=') for x in command), bits == '32')

    def test_wasm32_prerequisites(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(measure, 'ROOT', Path(directory)), \
                patch.object(measure, 'OUT', Path(directory)), patch.object(measure, 'run') as run:
            measure.prerequisites_wasm32()
            self.assertEqual([call.args[0] for call in run.call_args_list],
                             ['wasm32-runtime-deps', 'wasm32-runtime-configure', 'wasm32-runtime-build'])
            self.assertTrue(all('WASM_BITS=32' in call.args[1] for call in run.call_args_list))
            run.reset_mock()
            run.side_effect = RuntimeError('build failed')
            with self.assertRaisesRegex(RuntimeError, 'build failed'):
                measure.prerequisites_wasm32()
            self.assertEqual(run.call_count, 1)

    def test_mem2_lowering(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(measure, 'OUT', Path(directory)), \
                patch.object(measure, 'run') as run:
            (Path(directory) / 'mem2-reference.js').write_text('mem2-reference.wasm')
            measure.prepare_mem2('spill')
            command = list(map(str, run.call_args_list[0].args[1]))
            self.assertIn(str(Path(directory) / 'spill.wasm'), command)
            self.assertIn('--memory64-lowering', command)
            self.assertIn('--table64-lowering', command)
            self.assertIn('--mvp-features', command)
            self.assertIn('--enable-exception-handling', command)
            self.assertNotIn('--all-features', command)
            self.assertNotIn('--spill-pointers', command)
            self.assertEqual((Path(directory) / 'wasm64-mem2-spill.js').read_text(),
                             'wasm64-mem2-spill.wasm')

    def test_mem2_verification(self):
        fixture = '''(module
 (import "env" "f" (func $f (param i64) (result i32)))
 (memory $0 1 2)
 (export "memory" (memory $0))
 (export "entry" (func $entry))
 (func $entry (param $0 i64) (result i32)
  (i64.store (i32.const 0) (i64.const 0))
  (memory.fill (i32.const 0) (i32.const 0) (i32.const 0))
  (global.set $__stack_pointer (i64.const 0))
 )
)
'''
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'module.wat'
            path.write_text(fixture)
            final = verify_mem2.inspect_wat(path)
            source = dict(final, memory64=True)
            unsafe = dict(final, counts=dict.fromkeys(final['counts'], 0))
            self.assertEqual(verify_mem2.verify(final, final, source, unsafe, 'spill')['abi'], 'PASS')
            with self.assertRaisesRegex(ValueError, 'Missing spill'):
                verify_mem2.verify(final, final, source, final, 'spill')
            with self.assertRaisesRegex(ValueError, 'signatures differ'):
                verify_mem2.verify(dict(final, imports={}), final, source, unsafe, 'spill')
            path.write_text('')
            with self.assertRaisesRegex(ValueError, 'Empty module'):
                verify_mem2.inspect_wat(path)

    def test_real_checksum(self):
        valid = self.fixture().replace('checksum=4999950000', 'checksum=4.99995e9')
        self.assertEqual(measure.parse(valid, 0, False)['kernels']['vector100k']['checksum'], 4999950000)

    def test_errors(self):
        valid = self.fixture()
        for invalid in [valid.replace('BENCH PASS\n', ''), valid + 'BENCH PASS\n',
                        valid.replace('checksum=196418', 'checksum=0'),
                        valid.replace('gc-disabled=0', 'gc-disabled=1'),
                        valid.replace('median-ms=1', 'median-ms=NaN'),
                        valid.replace('median-ms=1', 'median-ms=2'),
                        valid.replace('first-ms=2', 'first-ms=-1'),
                        valid.replace('INIT clock-ms=100', 'INIT clock-ms=200'),
                        valid.replace('ENTRY clock-ms=120\n', ''),
                        valid.replace('1,1,1,1,1,1,1,1,1,1', '1,1'),
                        valid + 'CHECKSUM FAIL\n', valid + 'std::bad_alloc\n',
                        valid + 'GC Warning: Out of Memory!\n']:
            with self.subTest(output=invalid), self.assertRaises(ValueError):
                measure.parse(invalid, 0, False)
        with self.assertRaises(ValueError):
            measure.parse(valid, 1, False)
        with self.assertRaises(ValueError):
            measure.parse(valid.replace('STARTUP ms=10\n', ''), 0, False, True)


if __name__ == '__main__':
    unittest.main()
