#!/usr/bin/env python3
"""AI-assisted driver regression tests; no SDK or browser needed."""
import importlib.util
import pathlib
import runpy
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
        self.assertEqual(project.libraries, ())
        self.assertEqual(project.include_dirs, ())
        self.assertIsNone(project.frame)

    def test_sdk_optional_expectations(self):
        del self.config['expect']
        (self.root / 'jank-build.json').write_text(driver.json.dumps(self.config))
        project = driver.load_project(self.root, require_expect=False)
        self.assertEqual(project.expected('browser'), ())
        with self.assertRaises(RuntimeError):
            driver.load_project(self.root)

    def test_c_library_options(self):
        self.config.update(libraries=['raylib'], include_dirs=['src'],
                           native={'link_flags': ['-lm']}, wasm={'link_flags': ['-sASSERTIONS=1']},
                           frame='hello.core/frame')
        project = self.load()
        native = driver.c_dependencies(project, 'native')
        wasm = driver.c_dependencies(project, 'wasm')
        self.assertIn(self.root / 'src', native.include_dirs)
        self.assertTrue(str(native.archives[0]).endswith('native/lib/libraygui.a'))
        self.assertTrue(str(wasm.archives[1]).endswith('wasm64/lib/libraylib.a'))
        self.assertIn('-sUSE_GLFW=3', wasm.link_flags)
        self.assertIn('-sASSERTIONS=1', wasm.link_flags)
        self.assertIn('-lGL', native.link_flags)
        self.assertEqual(project.frame, 'hello.core/frame')

    def test_empty_c_dependencies(self):
        self.config.update(libraries=[], include_dirs=[], native={'link_flags': []}, wasm={})
        for platform in ('native', 'wasm'):
            self.assertEqual(driver.c_dependencies(self.load(), platform), driver.CDependencies())

    def test_invalid_c_options_and_frame(self):
        for key, value in [('libraries', ['unknown']), ('libraries', ['raylib', 'raylib']),
                           ('libraries', 'raylib'), ('include_dirs', ['missing']),
                           ('include_dirs', [3]), ('native', []),
                           ('wasm', {'link_flags': [3]}), ('frame', 'not-qualified'),
                           ('frame', None), ('frame', 'ns/fn\"'), ('frame', 3)]:
            with self.subTest(key=key, value=value):
                self.config[key] = value
                with self.assertRaises(RuntimeError):
                    self.load()
                del self.config[key]

    def test_frame_excludes_diagnostic_mode(self):
        self.config.update(frame='hello.core/frame', wasm_check='spike-continuous')
        with self.assertRaisesRegex(RuntimeError, 'cannot be combined'):
            self.load()

    def test_wasm_driver_and_link_options(self):
        template = (driver.ROOT / 'scripts/app-index.html').read_text()
        (self.root / 'scripts').mkdir()
        (self.root / 'scripts/app-index.html').write_text(template)
        target = self.root / 'artifacts/build-wasm64'
        target.mkdir(parents=True)
        (target / 'compile_commands.json').write_text('[]')
        for frame in (None, 'hello.core/frame'):
            with self.subTest(frame=frame):
                if frame:
                    self.config['frame'] = frame
                self.config.update(libraries=['raylib'], wasm={'link_flags': ['-sASSERTIONS=1']})
                project = self.load()
                calls = []
                def run(label, args, **kwargs):
                    calls.append((label, args))
                    if label == 'link':
                        (project.out / 'wasm' / f'{project.name}.js').write_text('')
                with mock.patch.object(driver, 'ROOT', self.root), \
                        mock.patch.object(driver, 'OUT', self.root / 'artifacts/app'), \
                        mock.patch.object(driver, 'wasm_compile_flags', return_value=(['em++'], self.root)):
                    driver.build_wasm(project, self.root, [], self.root / 'main.cpp', run)
                    page = (project.out / 'wasm/index.html').read_text()
                link = next(args for label, args in calls if label == 'link')
                self.assertIn(f'-sEXIT_RUNTIME={0 if frame else 1}', link)
                self.assertIn('-sUSE_GLFW=3', link)
                self.assertIn('-sASSERTIONS=1', link)
                entry = next(args for label, args in calls if label == 'entry')
                self.assertTrue(any(str(arg).endswith('wasm-entry.cpp' if frame else 'raylib-loop-driver.cpp') for arg in entry))
                self.assertIn(target / ('libjank-wasm-entry.a' if frame else 'libjank-wasm-raylib-entry.a'), link)
                if frame:
                    self.assertIn('"hello.core"', (self.root / 'wasm-config.cpp').read_text())
                    self.assertIn('"frame"', (self.root / 'wasm-config.cpp').read_text())
                roots = (self.root / 'wasm-roots.cpp').read_text()
                self.assertIn('GC_add_roots(&__global_base, &__data_end)', roots)
                cpp = [arg for label, args in calls if label.startswith('cpp') for arg in args]
                self.assertIn(self.root / 'scripts/exception-roots.cpp', cpp)
                self.assertIn('-Wl,--wrap=__cxa_allocate_exception,--wrap=__cxa_free_exception', link)
                self.assertEqual('-sJSPI=1' in link, not bool(frame))
                self.assertEqual('-Wl,--wrap=EndDrawing' in link, not bool(frame))
                self.assertEqual('-Wl,--wrap=emscripten_sleep' in link, not bool(frame))
                self.assertEqual(any(str(arg).endswith('jspi-suspend-guard.js') for arg in link), not bool(frame))
                self.assertIn('"interactive": true', page)
                self.assertIn('"frame": ' + ('"hello.core/frame"' if frame else 'null'), page)

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

    def test_legacy_config_is_not_loaded(self):
        (self.root / 'jank-zig.json').write_text(driver.json.dumps(
            {**self.config, 'name': 'legacy', 'zig': 'native.zig'}))
        with self.assertRaisesRegex(RuntimeError, 'Cannot read project config'):
            driver.load_project(self.root)
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

    def test_wasm_size_modes(self):
        project = self.load()
        scripts = self.root / 'scripts'
        scripts.mkdir()
        (scripts / 'app-index.html').write_text('__PROJECT_CONFIG__')
        target = self.root / 'artifacts/build-wasm64'
        target.mkdir(parents=True)
        (target / 'compile_commands.json').write_text(driver.json.dumps([{
            'file': '/source/src/cpp/jank/runtime/context.cpp', 'directory': '/build',
            'command': 'em++ -O2 -c /source/src/cpp/jank/runtime/context.cpp'}]))
        calls = {}

        def run(label, args, **kwargs):
            calls[label] = args
            if label == 'link':
                args[-1].write_text('var Module = {};')

        for mode in (None, 'baseline', 'strip', 'Os', 'Oz', 'O3'):
            env = {'JANK_WASM_LTO': '1'}
            if mode is not None:
                env['JANK_WASM_BUILD_MODE'] = mode
                env['JANK_WASM_APP_OPT'] = '-Os'
            with self.subTest(mode=mode), mock.patch.dict(driver.os.environ, env, clear=True), \
                    mock.patch.object(driver, 'ROOT', self.root), \
                    mock.patch.object(driver, 'OUT', self.root / 'out'):
                driver.build_wasm(project, self.root, [], self.root / 'main.cpp', run)
            self.assertIn('-Os', calls['cpp-0'])
            self.assertIn('-flto', calls['cpp-0'])
            self.assertIn('-flto', calls['link'])
            self.assertEqual('-g' in calls['cpp-0'], mode == 'baseline')
            self.assertEqual('--profiling-funcs' in calls['link'], mode == 'baseline')
            self.assertEqual('-g2' in calls['link'], mode != 'baseline')
            self.assertEqual(calls['spill'][-1], mode or 'Oz')

    def test_invalid_wasm_size_options(self):
        for variable, value in [('JANK_WASM_BUILD_MODE', ''), ('JANK_WASM_BUILD_MODE', 'bad'),
                                ('JANK_WASM_APP_OPT', ''), ('JANK_WASM_APP_OPT', '-O0')]:
            with self.subTest(variable=variable, value=value), \
                    mock.patch.dict(driver.os.environ, {variable: value}):
                with self.assertRaises(ValueError):
                    driver.build_wasm(None, None, None, None, None)

    def test_spill_post_pass_order(self):
        root = self.root
        optimizer = root / 'artifacts/build-binaryen/bin/wasm-opt'
        optimizer.parent.mkdir(parents=True)
        optimizer.touch()
        wasm = root / 'input.wasm'
        wasm.write_bytes(b'wasm')
        script = driver.ROOT / 'wasm-probe/spill-pointers.py'
        for mode in ('baseline', 'strip', 'Os', 'Oz', 'O3'):
            calls = []

            def transform(args, **kwargs):
                calls.append(args)
                pathlib.Path(args[-1]).write_bytes(b'transformed')

            with self.subTest(mode=mode), mock.patch.object(sys, 'argv', [str(script), str(root), str(wasm), mode]), \
                    mock.patch.object(subprocess, 'run', side_effect=transform):
                runpy.run_path(str(script), run_name='__main__')
            self.assertIn('--spill-pointers', calls[0])
            self.assertIn('-g', calls[0])
            self.assertEqual(len(calls), 1 if mode == 'baseline' else 2)
            if mode != 'baseline':
                self.assertIn('--strip-debug', calls[1])
                self.assertNotIn('--spill-pointers', calls[1])
                self.assertNotIn('-g', calls[1])
                if mode != 'strip':
                    self.assertIn('--dce', calls[1])
                    self.assertIn(f'-{mode}', calls[1])

    def test_invalid_spill_mode(self):
        script = driver.ROOT / 'wasm-probe/spill-pointers.py'
        for mode in ('', 'bad'):
            with self.subTest(mode=mode), \
                    mock.patch.object(sys, 'argv', [str(script), str(self.root), str(self.root / 'input.wasm'), mode]), \
                    mock.patch.object(subprocess, 'run') as run:
                with self.assertRaisesRegex(SystemExit, 'Expected baseline'):
                    runpy.run_path(str(script), run_name='__main__')
                run.assert_not_called()

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
