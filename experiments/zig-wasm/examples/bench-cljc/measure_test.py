"""AI-assisted normal/empty/error checks for benchmark correctness gates."""
import sys
import unittest

sys.dont_write_bytecode = True
import measure


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
