#!/usr/bin/env python3
"""AI-assisted configure-only target JSON regressions; no SDK required."""
import json
import pathlib
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SOURCE = ROOT.parents[1] / "compiler+runtime"


class TargetConfigTests(unittest.TestCase):
    def configure(self, driver, options=(), setup="", success=True):
        with tempfile.TemporaryDirectory(dir=ROOT / "artifacts") as tmp:
            path = pathlib.Path(tmp)
            compiler = path / "compiler"
            compiler.write_text("#!/bin/sh\n" + driver + "\n")
            compiler.chmod(0o755)
            (path / "CMakeLists.txt").write_text(
                'cmake_minimum_required(VERSION 3.22)\nproject(config_test NONE)\n'
                'add_library(jank_common_lib INTERFACE)\n'
                + setup + f'\ninclude("{SOURCE}/cmake/target_json.cmake")\n'
            )
            result = subprocess.run(
                ["cmake", "-S", str(path), "-B", str(path / "build"),
                 f"-DCMAKE_CXX_COMPILER={compiler}", *options],
                capture_output=True, text=True,
            )
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
            if success:
                return json.loads((path / "build/target_config.json").read_text())
            self.assertIn("Failed to query target triple", result.stderr)

    def test_query_receives_tokenized_flags(self):
        config = self.configure(
            '[ "$1" = "--probe=two words" ] && [ "$2" = "-print-target-triple" ] || exit 1\n'
            'echo wasm64-unknown-emscripten',
            ['-DCMAKE_CXX_FLAGS=--probe="two words"'],
        )
        self.assertEqual(config["triple"], "wasm64-unknown-emscripten")

    def test_explicit_triple_skips_query(self):
        config = self.configure("exit 1", ["-Djank_target_triple=explicit-target"])
        self.assertEqual(config["triple"], "explicit-target")

    def test_query_failure(self):
        self.configure("echo broken >&2; exit 1", success=False)

    def test_empty_query(self):
        self.configure("exit 0", success=False)

    def test_missing_link_directories(self):
        config = self.configure("echo native-target")
        self.assertNotIn("NOTFOUND", config["aot_flags"])

    def test_link_directories_preserved(self):
        config = self.configure(
            "echo native-target",
            setup='set_property(TARGET jank_common_lib PROPERTY LINK_DIRECTORIES /target/one /target/two)',
        )
        self.assertEqual(config["aot_flags"], "-L/target/one -L/target/two")

    def test_host_paths_filtered_only_when_cross_compiling(self):
        setup = '''
set(LLVM_INCLUDE_DIRS /host/llvm/include)
set(CLANG_INCLUDE_DIRS /host/clang/include)
set(LLVM_LIBRARY_DIRS /host/libraries)
set(llvm_dir /host/llvm)
set(jank_resource_dir /host/resources)
set(jank_common_compiler_flags -DJANK_RESOURCE_DIR="/host/resources" -DKEEP=1)
set(jank_lib_includes -I/host/llvm/include -I /host/clang/include -I/target/include -I/host/llvm-target)
set(jank_linker_flags -L/host/llvm/lib -L /host/libraries -L/target/lib)
'''
        cross = self.configure("echo wasm64-target", ["-Djank_cross_compile=ON"], setup)
        self.assertEqual(cross["jit_flags"], "-DKEEP=1 -I/target/include -I/host/llvm-target")
        self.assertEqual(cross["aot_flags"], "-L/target/lib")
        native = self.configure("echo native-target", setup=setup)
        self.assertIn("/host/llvm/include", native["jit_flags"])
        self.assertIn("/host/libraries", native["aot_flags"])


if __name__ == "__main__":
    (ROOT / "artifacts").mkdir(exist_ok=True)
    if len(sys.argv) == 3 and sys.argv[1] == "--generated":
        config = json.loads(pathlib.Path(sys.argv[2]).read_text())
        assert config["triple"] == "wasm64-unknown-emscripten"
        for name in ("jit_flags", "aot_flags"):
            assert "NOTFOUND" not in config[name]
            assert "/usr/lib/llvm-" not in config[name]
            assert "artifacts/host-resources" not in config[name]
        print(json.dumps(config, indent=2))
        print("wasm64 JSON: triple, NOTFOUND, host LLVM and resource checks passed")
    else:
        unittest.main()
