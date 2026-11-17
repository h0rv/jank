#!/usr/bin/env python3
"""AI-assisted driver regression tests; no SDK or browser needed."""
import importlib.util
import pathlib
import subprocess
import sys
import unittest
from unittest import mock

sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location('driver', pathlib.Path(__file__).with_name('jank-zig.py'))
driver = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(driver)


class DriverTests(unittest.TestCase):
    def test_markers(self):
        self.assertTrue(driver.valid_markers('\n'.join(driver.MARKERS)))

    def test_empty_and_partial_markers(self):
        for output in ['', driver.MARKERS[0], 'prefix ' + '\n'.join(driver.MARKERS)]:
            with self.subTest(output=output):
                self.assertFalse(driver.valid_markers(output))

    def test_page(self):
        page = driver.PageResult()
        page.feed('<html data-status="pass"><pre id="stdout">jank -&gt; Zig: test\n</pre></html>')
        self.assertEqual(page.status, 'pass')
        self.assertEqual(page.output, 'jank -> Zig: test\n')

    def test_page_ignores_script_markers(self):
        page = driver.PageResult()
        page.feed('<html data-status="running"><script>' + '\n'.join(driver.MARKERS) + '</script>')
        self.assertEqual(page.output, '')
        self.assertNotEqual(page.status, 'pass')

    def test_bad_app_before_bootstrap(self):
        with mock.patch.object(driver, 'prerequisites') as setup:
            with self.assertRaisesRegex(RuntimeError, 'App must contain'):
                driver.build(driver.ROOT / 'artifacts/no-such-app')
            setup.assert_not_called()

    def test_native_nonzero_with_markers_fails(self):
        result = subprocess.CompletedProcess([], 1, '\n'.join(driver.MARKERS), '')
        with mock.patch.object(driver, 'container'), \
                mock.patch.object(driver.subprocess, 'run', return_value=result), \
                mock.patch.object(pathlib.Path, 'write_text'), \
                mock.patch.object(pathlib.Path, 'mkdir'):
            self.assertFalse(driver.execute('native')[0])

    def test_node_validator_failure_fails(self):
        result = subprocess.CompletedProcess([], 0, '\n'.join(driver.MARKERS), '')
        rejected = subprocess.CompletedProcess([], 1, 'bad iterations', '')
        with mock.patch.object(driver, 'container'), \
                mock.patch.object(driver.subprocess, 'run', side_effect=[result, rejected]), \
                mock.patch.object(pathlib.Path, 'write_text'), \
                mock.patch.object(pathlib.Path, 'mkdir'):
            self.assertFalse(driver.execute('node')[0])

    def test_browser_verdict(self):
        for status, output, exitcode, expected in [
            ('pass', '\n'.join(driver.MARKERS), 0, True),
            ('pass', '', 0, False),
            ('running', '\n'.join(driver.MARKERS), 0, False),
            ('fail', '\n'.join(driver.MARKERS), 0, False),
            ('pass', '\n'.join(driver.MARKERS), 1, False),
        ]:
            with self.subTest(status=status, exitcode=exitcode, output=output):
                result = subprocess.CompletedProcess([], exitcode,
                    f'<html data-status="{status}"><pre id="stdout">{output}</pre></html>', '')
                with mock.patch.object(driver, 'server') as server, \
                        mock.patch.object(driver.subprocess, 'run', return_value=result), \
                        mock.patch.object(pathlib.Path, 'write_text'):
                    server.return_value.__enter__.return_value = 'http://127.0.0.1/'
                    self.assertEqual(driver.browser_check()[0], expected)


if __name__ == '__main__':
    unittest.main()
