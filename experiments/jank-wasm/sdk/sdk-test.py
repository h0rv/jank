#!/usr/bin/env python3
"""AI-assisted offline SDK packaging boundary tests."""
import importlib.util
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, pathlib.Path(__file__).with_name(filename))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


package = load('package', 'package.py')
driver = load('sdk_driver', 'jank-wasm.py')


class SDKTests(unittest.TestCase):
    def test_wrapper_uses_loader_and_relative_root(self):
        script = package.wrapper('jank', '../..')
        self.assertIn('--library-path "$root/host/lib"', script)
        self.assertIn('--preload "$root/host/lib/libjank-sdk-host.so"', script)
        self.assertNotIn(str(package.ROOT), script)

    def test_clang_child_dispatch_preserves_adapter(self):
        script = package.wrapper('clang', '../../..')
        self.assertIn('-cc1*', script)
        self.assertIn('--argv0 "$root/artifacts/host-resources/bin/clang++"', script)
        self.assertIn('-no-canonical-prefixes', script)

    def test_empty_flags(self):
        self.assertEqual(package.include_flags([], 'test'), [])

    def test_compiler_build_path_definitions_are_not_application_flags(self):
        flags = ['-O2', '-DJANK_RESOURCE_DIR="/build/resources"',
                 '-DJANK_CLANG_PATH="/build/clang"', '-DJANK_CLANG_PREFIX="/build/llvm"',
                 '-DJANK_CLANG_RESOURCE_DIR="/build/clang/lib"', '-DJANK_VERSION="0.1"']
        self.assertEqual(package.include_flags(flags, 'test'), ['-O2', '-DJANK_VERSION="0.1"'])

    def test_include_paths_are_copied_once_and_relocated(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            source = root / 'source'
            source.mkdir()
            (source / 'test.h').write_text('')
            with mock.patch.object(package, 'SDK', root / 'sdk'), \
                    mock.patch.object(package.common, 'REPO', root):
                flags = package.include_flags(['-O2', '-I', str(source), '-isystem' + str(source)], 'test')
            self.assertEqual(flags, ['-O2', '-I@SDK@/include/test/0', '-isystem@SDK@/include/test/0'])
            self.assertTrue((root / 'sdk/include/test/0/test.h').is_file())
            self.assertFalse((root / 'sdk/include/test/1').exists())

    def test_relative_include_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'relative include'):
            package.include_flags(['-Irelative'], 'test')

    def test_whitespace_sdk_is_rejected_before_writes(self):
        with mock.patch.object(driver, 'ROOT', pathlib.Path('/some path/sdk')):
            with self.assertRaisesRegex(RuntimeError, 'without whitespace'):
                driver.configure()

    def test_sdk_rejects_diagnostic_mode_before_staging(self):
        project = mock.Mock(wasm_check='spike-continuous')
        with self.assertRaisesRegex(RuntimeError, 'Diagnostic'):
            driver.build(project)

    def test_sdk_preserves_shared_log_names_and_cpp_launcher(self):
        with tempfile.TemporaryDirectory() as temp:
            root = pathlib.Path(temp)
            project = mock.Mock(wasm_check='single', root=root, out=root / 'dist')
            project.name = 'hello'
            def generate(project, stage, platform, prefix, run):
                run('launcher', ['env', 'compile', 'hello.core'])
                return [], stage / 'main.cpp'
            with mock.patch.object(driver.common, 'generate_sources', side_effect=generate), \
                    mock.patch.object(driver.common, 'build_wasm'), \
                    mock.patch.object(driver.common, 'logged') as logged:
                driver.build(project)
            self.assertEqual(logged.call_args.args[0], 'hello-wasm-launcher')
            self.assertEqual(logged.call_args.args[1],
                             ['env', '--output-target', 'cpp', 'compile', 'hello.core'])


if __name__ == '__main__':
    unittest.main()
