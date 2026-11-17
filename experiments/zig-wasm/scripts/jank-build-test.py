#!/usr/bin/env python3
"""AI-assisted driver regression tests; no SDK or browser needed."""
import importlib.util
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location('driver', pathlib.Path(__file__).with_name('jank-build.py'))
driver = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = driver
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
            with self.assertRaisesRegex(RuntimeError, 'Cannot read project config'):
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


class ProjectTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = pathlib.Path(self.temp.name)
        (self.root / 'src').mkdir()
        (self.root / 'native.zig').write_text('')
        self.config = {'main': 'hello.core', 'expect': ['done']}

    def load(self):
        (self.root / 'jank-build.json').write_text(driver.json.dumps(self.config))
        return driver.load_project(self.root)

    def test_defaults(self):
        project = self.load()
        self.assertEqual(project.name, self.root.name)
        self.assertEqual(project.jank, self.root / 'src')
        self.assertIsNone(project.zig)
        self.assertEqual(project.expected('browser'), ('done',))
        self.assertEqual(project.wasm_check, 'single')

    def test_per_target_expect(self):
        self.config['expect'] = {target: [target] for target in ('native', 'node', 'browser')}
        project = self.load()
        for target in ('native', 'node', 'browser'):
            self.assertEqual(project.expected(target), (target,))

    def test_missing_required_keys(self):
        for key in ('main', 'expect'):
            original = self.config.pop(key)
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                self.load()
            self.config[key] = original

    def test_bad_paths(self):
        for key in ('jank', 'zig'):
            for value in ('missing', '../outside', '/etc/passwd', '', 3):
                self.config[key] = value
                with self.subTest(key=key, value=value), self.assertRaises(RuntimeError):
                    self.load()
            del self.config[key]

    def test_symlink_escape(self):
        (self.root / 'escape').symlink_to(self.root.parent, target_is_directory=True)
        self.config['jank'] = 'escape'
        with self.assertRaisesRegex(RuntimeError, 'Invalid jank'):
            self.load()

    def test_invalid_expect(self):
        for value in (None, [], [''], [3], ['two\nlines'], {'native': ['done']},
                      {'native': [], 'node': ['done'], 'browser': ['done']}):
            self.config['expect'] = value
            with self.subTest(value=value), self.assertRaises(RuntimeError):
                self.load()

    def test_invalid_names_and_mode(self):
        for key, value in [('name', '../oops'), ('main', ''), ('main', 3),
                           ('wasm_check', 'unknown')]:
            self.config[key] = value
            with self.subTest(key=key), self.assertRaises(RuntimeError):
                self.load()
            self.config = {'main': 'hello.core', 'expect': ['done']}

    def test_invalid_json_and_shape(self):
        for text in ('', '[]', '{'):
            (self.root / 'jank-build.json').write_text(text)
            with self.subTest(text=text), self.assertRaises(RuntimeError):
                driver.load_project(self.root)

    def test_example_and_spike(self):
        self.assertEqual(driver.load_project().wasm_check, 'spike-continuous')
        project = driver.load_project(driver.ROOT / 'examples/hello-cljc')
        self.assertEqual(project.main, 'hello.core')
        self.assertIsNone(project.zig)
        self.assertIn('platform: browser', project.expected('browser'))

    def test_optional_zig_source(self):
        self.config['zig'] = 'native.zig'
        self.assertEqual(self.load().zig, self.root / 'native.zig')
        self.assertIsNotNone(driver.load_project().zig)

    def test_legacy_config_fallback_and_new_config_precedence(self):
        (self.root / 'jank-zig.json').write_text(driver.json.dumps(
            {**self.config, 'name': 'legacy', 'zig': 'native.zig'}))
        self.assertEqual(driver.load_project(self.root).name, 'legacy')
        self.assertEqual(self.load().name, self.root.name)
        (self.root / 'jank-build.json').write_text('{')
        with self.assertRaisesRegex(RuntimeError, 'Cannot read project config'):
            driver.load_project(self.root)

    def test_pure_jank_bootstrap_never_probes_zig(self):
        project = self.load()
        digest = driver.hashlib.sha256(b'patch').hexdigest()
        with mock.patch.object(driver, 'container'), \
                mock.patch.object(driver, 'logged') as logged, \
                mock.patch.object(driver.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), \
                mock.patch.object(driver.subprocess, 'check_output') as output, \
                mock.patch.object(pathlib.Path, 'mkdir'), \
                mock.patch.object(pathlib.Path, 'is_file', autospec=True,
                                  side_effect=lambda path: path != driver.ZIG), \
                mock.patch.object(pathlib.Path, 'read_bytes', return_value=b'patch'), \
                mock.patch.object(pathlib.Path, 'read_text', return_value=digest):
            driver.prerequisites(project)
        output.assert_not_called()
        self.assertEqual([call.args[0] for call in logged.call_args_list], ['submodules'])

    def test_pure_jank_build_skips_zig_build_file(self):
        self.load()
        with mock.patch.object(driver, 'OUT', self.root / 'artifacts/app'), \
                mock.patch.object(driver, 'prerequisites'), \
                mock.patch.object(driver, 'logged') as logged, \
                mock.patch.object(driver, 'generate_sources', return_value=([], self.root / 'main.cpp')), \
                mock.patch.object(driver, 'build_native'), \
                mock.patch.object(driver, 'build_wasm'):
            driver.build(self.root)
        logged.assert_not_called()
        for platform in ('native', 'wasm'):
            self.assertFalse((self.root / 'artifacts/app' / self.root.name /
                              f'stage-{platform}/build.zig').exists())

    def test_compile_flags_strip_outputs(self):
        flags, directory = driver.wasm_compile_flags([{
            'file': '/source/src/cpp/jank/runtime/context.cpp', 'directory': '/build',
            'command': 'em++ -O2 -MD -MT target -MF deps -o out -c /source/src/cpp/jank/runtime/context.cpp'}])
        self.assertEqual(flags, ['em++', '-O2'])
        self.assertEqual(directory, '/build')

    def test_dom_output(self):
        page = driver.PageResult()
        page.feed('<html data-status="pass"><pre id="app">platform: browser\ndone\n</pre></html>')
        self.assertTrue(driver.valid_markers(page.output, ('platform: browser', 'done')))

    def test_generic_execution_requires_stdout_and_zero_exit(self):
        project = self.load()
        for status, stdout, stderr, expected in [
                (0, 'done\n', '', True), (0, '', '', False),
                (0, '', 'done\n', False), (1, 'done\n', '', False)]:
            result = subprocess.CompletedProcess([], status, stdout, stderr)
            with self.subTest(status=status, stdout=stdout, stderr=stderr), \
                    mock.patch.object(driver, 'container'), \
                    mock.patch.object(driver.subprocess, 'run', return_value=result), \
                    mock.patch.object(pathlib.Path, 'write_text'), \
                    mock.patch.object(pathlib.Path, 'mkdir'):
                self.assertEqual(driver.execute('native', project)[0], expected)


if __name__ == '__main__':
    unittest.main()
