#!/usr/bin/env python3
"""AI-assisted driver regression tests; no SDK or browser needed."""
import importlib.util
import pathlib
import runpy
import subprocess
import sys
import tempfile
import unittest
from dataclasses import replace
from unittest import mock

sys.dont_write_bytecode = True
SPEC = importlib.util.spec_from_file_location('driver', pathlib.Path(__file__).with_name('jank-build.py'))
driver = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = driver
SPEC.loader.exec_module(driver)


class DriverTests(unittest.TestCase):
    def test_preflight(self):
        with mock.patch.object(driver.sys, 'version_info', (3, 9)):
            with self.assertRaisesRegex(RuntimeError, 'Python 3.10'):
                driver.preflight()
        for tool in ('docker', 'git', 'curl'):
            with self.subTest(tool=tool), mock.patch.object(driver.shutil, 'which',
                    side_effect=lambda name: None if name == tool else '/bin/' + name):
                with self.assertRaisesRegex(RuntimeError, tool):
                    driver.preflight()
        with mock.patch.object(driver.shutil, 'which', return_value='/bin/tool'), \
                mock.patch.object(driver.subprocess, 'run', return_value=subprocess.CompletedProcess([], 1)):
            with self.assertRaisesRegex(RuntimeError, 'Docker daemon unreachable'):
                driver.preflight()
        with mock.patch.object(driver.shutil, 'which', return_value='/bin/tool'), \
                mock.patch.object(driver.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)):
            driver.preflight()

    def test_chrome_resolution(self):
        with tempfile.TemporaryDirectory() as directory:
            tools = pathlib.Path(directory)
            chrome = tools / 'playwright/chromium-123/chrome-linux64/chrome'
            chrome.parent.mkdir(parents=True)
            chrome.touch(mode=0o755)
            with mock.patch.object(driver, 'TOOLS', tools), \
                    mock.patch.dict(driver.os.environ, {}, clear=True), \
                    mock.patch.object(driver.shutil, 'which', return_value=None):
                self.assertEqual(driver.resolve_chrome(), str(chrome))
                chrome.unlink()
                with self.assertRaisesRegex(RuntimeError, 'setup --browser'):
                    driver.resolve_chrome()
            with mock.patch.dict(driver.os.environ, {'CHROME': '/custom/chrome'}), \
                    mock.patch.object(driver.shutil, 'which', side_effect=lambda name: name):
                self.assertEqual(driver.resolve_chrome(), '/custom/chrome')
            with mock.patch.dict(driver.os.environ, {'CHROME': '/bad/chrome'}), \
                    mock.patch.object(driver.shutil, 'which', return_value=None):
                with self.assertRaisesRegex(RuntimeError, 'CHROME is not executable'):
                    driver.resolve_chrome()
            for executable in ('google-chrome', 'chromium'):
                with mock.patch.dict(driver.os.environ, {}, clear=True), \
                        mock.patch.object(driver.shutil, 'which', side_effect=lambda name:
                                          '/bin/' + name if name == executable else None):
                    self.assertEqual(driver.resolve_chrome(), '/bin/' + executable)

    def test_submodule_stamp(self):
        with tempfile.TemporaryDirectory() as directory, \
                mock.patch.object(driver, 'ROOT', pathlib.Path(directory)), \
                mock.patch.object(driver, 'submodule_status', return_value=('abc', True)), \
                mock.patch.object(driver, 'logged') as logged:
            stamp = pathlib.Path(directory) / 'artifacts/submodules.sha256'
            stamp.parent.mkdir()
            driver.ensure_submodules()
            self.assertEqual(stamp.read_text(), 'abc')
            logged.assert_called_once()
            logged.reset_mock()
            driver.ensure_submodules()
            logged.assert_not_called()
            stamp.write_text('old')
            driver.ensure_submodules()
            logged.assert_called_once()
            with mock.patch.object(driver, 'submodule_status', return_value=('abc', False)):
                with self.assertRaisesRegex(RuntimeError, 'pinned revisions'):
                    driver.ensure_submodules()

    def test_setup_check_is_read_only(self):
        for ready, status in ((True, 0), (False, 1)):
            with mock.patch.object(driver, 'preflight'), \
                    mock.patch.object(driver, 'load_project'), \
                    mock.patch.object(driver, 'setup_components', return_value=[('Node', 'pin', '/cache', ready)]), \
                    mock.patch.object(driver, 'prerequisites') as prerequisites, \
                    mock.patch.object(driver, 'logged') as logged:
                self.assertEqual(driver.setup(check=True), status)
                prerequisites.assert_not_called()
                logged.assert_not_called()

    def test_setup_browser_installs_pinned_local_playwright(self):
        rows = [('Chrome', 'pin', '/cache', True)]
        with mock.patch.object(driver, 'preflight'), mock.patch.object(driver, 'load_project'), \
                mock.patch.object(driver, 'setup_components', return_value=rows), \
                mock.patch.object(driver, 'prerequisites'), \
                mock.patch.object(driver, 'resolve_chrome', side_effect=RuntimeError('missing')), \
                mock.patch.object(driver, 'logged') as logged:
            self.assertEqual(driver.setup(browser=True), 0)
        args, kwargs = logged.call_args
        self.assertEqual(args[1][0], driver.NODE.with_name('npx'))
        self.assertIn(f'playwright@{driver.PLAYWRIGHT_VERSION}', args[1])
        self.assertEqual(kwargs['env']['PLAYWRIGHT_BROWSERS_PATH'], str(driver.TOOLS / 'playwright'))
        self.assertEqual(kwargs['env']['npm_config_cache'], str(driver.TOOLS / 'npm-cache'))

    def test_entry_archive_is_cached(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory)
            target = root / 'artifacts/build-wasm64'
            target.mkdir(parents=True)
            (root / 'sdk').mkdir()
            (root / 'sdk/wasm-entry.cpp').touch()
            (target / 'libjank-wasm-entry.a').touch()
            (target / 'compile_commands.json').write_text('[]')
            with mock.patch.object(driver, 'ROOT', root), \
                    mock.patch.object(driver, 'wasm_compile_flags', return_value=(['/sdk/em++'], '/build')), \
                    mock.patch.object(driver, 'logged') as logged:
                project = mock.Mock(libraries=())
                driver.ensure_entries(project)
                logged.assert_not_called()
                (target / 'libjank-wasm-entry.a').unlink()
                driver.ensure_entries(project)
                self.assertEqual(logged.call_count, 2)
                self.assertIn(f'EM_CONFIG={driver.TOOLS / "gc-wasm/emsdk/.emscripten"}',
                              logged.call_args_list[0].args[1])

    def test_raylib_provisions_missing_container_tools(self):
        for status in (0, 1):
            with tempfile.TemporaryDirectory() as directory, \
                    mock.patch.object(driver, 'TOOLS', pathlib.Path(directory)), \
                    mock.patch.object(driver.subprocess, 'run', return_value=subprocess.CompletedProcess([], status)) as probe, \
                    mock.patch.object(driver, 'logged') as logged:
                driver.build_raylib('native')
                self.assertIn('command -v unzip >/dev/null && command -v patch >/dev/null', probe.call_args.args[0])
                self.assertEqual([call.args[0] for call in logged.call_args_list],
                                 (['raylib-packages'] if status else []) + ['raylib-native'])
                self.assertIn('exec docker exec -i', (pathlib.Path(directory) / 'app-bin/patch').read_text())

    def test_scaffold(self):
        with tempfile.TemporaryDirectory() as directory:
            root = pathlib.Path(directory) / 'hello-world'
            driver.new_project(root)
            project = driver.load_project(root)
            self.assertEqual(project.main, 'hello-world.core')
            self.assertEqual(project.expected('native'), ('Hello from hello-world!',))
            source = root / 'src/hello_world/core.jank'
            self.assertIn('(defn -main', source.read_text())
            with self.assertRaisesRegex(RuntimeError, 'overwrite'):
                driver.new_project(root)
            driver.new_project(pathlib.Path(directory) / 'other', 'custom_name')
            self.assertEqual(driver.load_project(pathlib.Path(directory) / 'other').main, 'custom-name.core')
            for name in ('', '../bad', '1bad'):
                with self.assertRaisesRegex(RuntimeError, 'name must'):
                    driver.new_project(pathlib.Path(directory) / 'invalid', name)

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
        project = replace(driver.load_project(), wasm_check='spike-continuous')
        result = subprocess.CompletedProcess([], 0, '\n'.join(driver.MARKERS), '')
        rejected = subprocess.CompletedProcess([], 1, 'bad iterations', '')
        with mock.patch.object(driver, 'container'), \
                mock.patch.object(driver.subprocess, 'run', side_effect=[result, rejected]), \
                mock.patch.object(pathlib.Path, 'write_text'), \
                mock.patch.object(pathlib.Path, 'mkdir'):
            self.assertFalse(driver.execute('node', project=project)[0])

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
                        mock.patch.object(driver, 'resolve_chrome', return_value='chrome'), \
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
        self.config = {'main': 'hello.core', 'expect': ['done']}

    def load(self):
        (self.root / 'jank-build.json').write_text(driver.json.dumps(self.config))
        return driver.load_project(self.root)

    def test_warm_build_stamp(self):
        project = self.load()
        output = self.root / 'output' / project.name
        with mock.patch.object(driver, 'OUT', output.parent), \
                mock.patch.object(driver, 'prerequisites'), \
                mock.patch.object(driver, 'generate_sources', return_value=([], self.root / 'main.cpp')) as generate, \
                mock.patch.object(driver, 'build_native'), mock.patch.object(driver, 'build_wasm'):
            for path in (output / 'native' / project.name, output / 'wasm/index.html',
                         output / 'wasm' / f'{project.name}.js', output / 'wasm' / f'{project.name}.wasm'):
                path.parent.mkdir(parents=True, exist_ok=True)
                path.touch()
            with mock.patch.object(driver, 'build_digest', return_value='same'):
                (output / 'build.sha256').write_text('same')
                driver.build(self.root)
                generate.assert_not_called()
            with mock.patch.object(driver, 'build_digest', return_value='changed'), \
                    mock.patch.object(driver.shutil, 'copytree'):
                driver.build(self.root)
                self.assertEqual(generate.call_count, 2)
                self.assertEqual((output / 'build.sha256').read_text(), 'changed')

    def test_build_digest_tracks_sources_and_environment(self):
        project = self.load()
        with mock.patch.object(driver, 'ROOT', self.root):
            first = driver.build_digest(project)
            self.assertEqual(first, driver.build_digest(project))
            (self.root / 'src/main.jank').write_text('(println "changed")')
            second = driver.build_digest(project)
            self.assertNotEqual(first, second)
            with mock.patch.dict(driver.os.environ, {'JANK_WASM_BUILD_MODE': 'baseline'}):
                self.assertNotEqual(second, driver.build_digest(project))

    def test_defaults(self):
        project = self.load()
        self.assertEqual(project.name, self.root.name)
        self.assertEqual(project.jank, self.root / 'src')
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

    def test_between_frame_gc_requires_frame(self):
        self.assertFalse(self.load().between_frame_gc)
        self.config['wasm'] = {'gc': 'between-frames'}
        with self.assertRaisesRegex(RuntimeError, 'requires a returning frame'):
            self.load()
        self.config['frame'] = 'hello.core/frame'
        self.assertTrue(self.load().between_frame_gc)
        self.config['wasm']['link_flags'] = ['-pthread']
        with self.assertRaisesRegex(RuntimeError, 'does not support pthreads'):
            self.load()
        del self.config['wasm']['link_flags']
        self.config['wasm']['gc'] = 'garbage'
        with self.assertRaisesRegex(RuntimeError, 'wasm.gc must be'):
            self.load()

    def test_wasm_driver_and_link_options(self):
        template = (driver.ROOT / 'scripts/app-index.html').read_text()
        (self.root / 'scripts').mkdir()
        (self.root / 'scripts/app-index.html').write_text(template)
        target = self.root / 'artifacts/build-wasm64'
        target.mkdir(parents=True)
        (target / 'compile_commands.json').write_text('[]')
        for frame, gc in ((None, 'spill'), ('hello.core/frame', 'spill'),
                          ('hello.core/frame', 'between-frames')):
            with self.subTest(frame=frame, gc=gc):
                if frame:
                    self.config['frame'] = frame
                self.config.update(libraries=['raylib'], wasm={'link_flags': ['-sASSERTIONS=1'], 'gc': gc})
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
                if project.between_frame_gc:
                    self.assertIn('-sASYNCIFY=0', link)
                    self.assertIn('-sJSPI=0', link)
                    self.assertIn('-sSHARED_MEMORY=0', link)
                    self.assertNotIn('-g2', link)
                else:
                    self.assertIn('-g2', link)
                self.assertEqual(any(label == 'spill' for label, _ in calls), not project.between_frame_gc)
                entry = next(args for label, args in calls if label == 'entry')
                self.assertTrue(any(str(arg).endswith('wasm-entry.cpp' if frame else 'raylib-loop-driver.cpp') for arg in entry))
                self.assertIn(target / ('libjank-wasm-entry.a' if frame else 'libjank-wasm-raylib-entry.a'), link)
                if frame:
                    self.assertIn('"hello.core"', (self.root / 'wasm-config.cpp').read_text())
                    self.assertIn('"frame"', (self.root / 'wasm-config.cpp').read_text())
                    self.assertIn(f'jank_wasm_between_frame_gc = {int(project.between_frame_gc)}',
                                  (self.root / 'wasm-config.cpp').read_text())
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

    def test_example_and_default(self):
        default = driver.load_project()
        self.assertEqual(default.main, 'hello.core')
        self.assertEqual(default.jank, driver.ROOT / 'examples/hello-cljc/src')
        self.assertEqual(default.wasm_check, 'single')
        self.assertEqual(default.expected('native'), driver.MARKERS)
        project = driver.load_project(driver.ROOT / 'examples/hello-cljc')
        self.assertEqual(project.main, 'hello.core')
        self.assertIn('platform: browser', project.expected('browser'))

    def test_zig_projects_require_addon_branch(self):
        for value in ('library.zig', '', None, 3):
            self.config['zig'] = value
            with self.subTest(value=value), self.assertRaisesRegex(RuntimeError, 'zig-addon'):
                self.load()

    def test_legacy_config_is_not_loaded(self):
        (self.root / 'jank-zig.json').write_text(driver.json.dumps(
            {**self.config, 'name': 'legacy', 'zig': 'library.zig'}))
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
                mock.patch.object(driver, 'preflight'), \
                mock.patch.object(driver, 'ensure_submodules'), \
                mock.patch.object(driver, 'ensure_entries'), \
                mock.patch.object(driver, 'logged') as logged, \
                mock.patch.object(driver.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), \
                mock.patch.object(driver.subprocess, 'check_output') as output, \
                mock.patch.object(pathlib.Path, 'mkdir'), \
                mock.patch.object(pathlib.Path, 'is_file', autospec=True,
                                  return_value=True), \
                mock.patch.object(pathlib.Path, 'read_bytes', return_value=b'patch'), \
                mock.patch.object(pathlib.Path, 'read_text', return_value=digest):
            driver.prerequisites(project)
        output.assert_not_called()
        logged.assert_not_called()

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

    def test_wasm_page_settings(self):
        for flags, expected in [([], {'modularize': False, 'exportName': 'Module'}),
                (['-sMODULARIZE=1', '-sEXPORT_NAME=createLive'],
                 {'modularize': True, 'exportName': 'createLive'}),
                (['-s', 'MODULARIZE', '-s', 'EXPORT_NAME="createApp"'],
                 {'modularize': True, 'exportName': 'createApp'}),
                (['-sMODULARIZE=1', '-sMODULARIZE=0'],
                 {'modularize': False, 'exportName': 'Module'})]:
            with self.subTest(flags=flags):
                self.assertEqual(driver.wasm_page_settings(flags), expected)

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
