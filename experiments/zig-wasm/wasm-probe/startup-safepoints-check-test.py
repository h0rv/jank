# AI-assisted regression tests for strict per-iteration marker validation.
import pathlib
import subprocess
import sys
import tempfile
import unittest

checker = pathlib.Path(__file__).with_name('startup-safepoints-check.py')
scalar = 'jank -> Zig: scalar and wide result checks passed\n'
buffer = 'jank -> Zig: borrowed-buffer checks passed\n'


def fixture(mode):
    prefix = 'STARTUP' if mode in ('continuous', 'no-gc-reentry') else 'SAFEPOINT'
    increment = {'safepoint': 1, 'safepoint-churn': 2, 'continuous': 3, 'no-gc-reentry': 0}[mode]
    disabled = int(mode != 'continuous')
    output = 'startup memory: phase=before-spike collections=1 heap-bytes=100 gc-disabled=%d\n' % disabled
    for i in range(1, 3):
        output += (f'{prefix} BEGIN: iteration={i}/2\n' + scalar + buffer
                   + f'{prefix} ITERATION {i}/2: collections={1 + i * increment} '
                   'used-bytes=50 heap-bytes=100 status=0\n')
    return output + f'startup diagnostic: exit=0 collections={1 + 2 * increment} gc-disabled={disabled}\n'


class Check(unittest.TestCase):
    def check(self, output, expected, mode='continuous', code=0):
        with tempfile.TemporaryDirectory() as directory:
            path = pathlib.Path(directory) / 'run.log'
            path.write_text(output)
            result = subprocess.run([sys.executable, str(checker), str(path), mode, '2', str(code)],
                                    capture_output=True, text=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)

    def test_normal_modes(self):
        for mode in ['safepoint', 'safepoint-churn', 'continuous', 'no-gc-reentry']:
            with self.subTest(mode=mode):
                self.check(fixture(mode), 0, mode)

    def test_empty(self):
        self.check('', 1)

    def test_missing_or_duplicate_marker(self):
        for replacement in ['', scalar + scalar]:
            self.check(fixture('continuous').replace(scalar, replacement, 1), 1)

    def test_nonzero_exit(self):
        self.check(fixture('continuous'), 1, code=1)

    def test_missing_iteration(self):
        self.check(fixture('continuous').replace('iteration=2/2', 'iteration=3/2'), 1)

    def test_wrong_gc_state(self):
        self.check(fixture('continuous').replace('gc-disabled=0', 'gc-disabled=1'), 1)

    def test_no_continuous_collection(self):
        output = fixture('no-gc-reentry').replace('gc-disabled=1', 'gc-disabled=0')
        self.check(output, 1)

    def test_collection_while_disabled(self):
        self.check(fixture('continuous').replace('gc-disabled=0', 'gc-disabled=1'), 1,
                   mode='no-gc-reentry')

    def test_backwards_collection_count(self):
        self.check(fixture('continuous').replace('collections=7', 'collections=3'), 1)


unittest.main()
