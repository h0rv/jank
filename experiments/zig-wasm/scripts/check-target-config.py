#!/usr/bin/env python3
"""AI-assisted configure-only target JSON regressions; no SDK required."""
import json
import pathlib
import subprocess
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


if __name__ == "__main__":
    (ROOT / "artifacts").mkdir(exist_ok=True)
    unittest.main()
