#!/usr/bin/env python3
"""AI-assisted host/target AOT regression; run in the Ubuntu build container."""
import json
import os
import pathlib
import shlex
import subprocess

ROOT = pathlib.Path(__file__).resolve().parents[1]
HOST = ROOT / "artifacts/build-host/jank"
SDK = ROOT / ".tools/wasm64-install/lib/jank/0.1"
OUT = ROOT / "artifacts/target-config-aot"
OUT.mkdir(exist_ok=True)
(OUT / "src").mkdir(exist_ok=True)
(OUT / "src/target_config_smoke.jank").write_text(
    '(ns target-config-smoke)\n(defn -main [] (println "target config native AOT passed"))\n'
)
env = dict(os.environ, LANG="C.UTF-8", LC_ALL="C.UTF-8",
           TMPDIR=str(ROOT / "artifacts/tmp"))


def run(name, args, success=True):
    result = subprocess.run([str(x) for x in args], cwd=OUT, env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (OUT / f"{name}.log").write_text(result.stdout)
    print(f"{name}: exit={result.returncode}", flush=True)
    if (result.returncode == 0) != success:
        raise AssertionError(result.stdout)
    return result.stdout


base = [HOST, "--module-path", OUT / "src"]
config = json.loads((SDK / "target_config.json").read_text())
driver = pathlib.Path(config["clang_bin"])
record = OUT / "commands.jsonl"
record.write_text("")
wrapper = OUT / "em++"
wrapper.write_text(
    '#!/usr/bin/python3\nimport json, os, shlex, sys\n'
    f'command = [{str(driver)!r}] + sys.argv[1:]\n'
    f'with open({str(record)!r}, "a") as out: out.write(json.dumps(command) + "\\n")\n'
    'print(shlex.join(command), flush=True)\nos.execv(command[0], command)\n'
)
wrapper.chmod(0o755)
config["clang_bin"] = str(wrapper)
recording_config = SDK / "recording-target_config.json"
recording_config.write_text(json.dumps(config))
cross_args = [*base, "--target-config", recording_config, "--target-dir", OUT / "wasm",
              "--output-target", "object", "compile-module", "target-config-smoke"]
try:
    run("wasm-object", cross_args)
    commands = [json.loads(line) for line in record.read_text().splitlines()]
    assert commands
    for command in commands:
        assert command[0] == str(driver)
        assert "--target=wasm64-unknown-emscripten" in command
        assert not any("/usr/lib/llvm-" in arg or "host-resources" in arg for arg in command)
        print(shlex.join(command), flush=True)
    objects = list((OUT / "wasm").rglob("target_config_smoke.o"))
    assert objects
    for obj in objects:
        print(run("wasm-file", ["file", obj]), end="")
        headers = run("wasm-headers", [driver.parents[2] / "bin/llvm-readobj", "--file-headers", obj])
        assert "Arch: wasm64" in headers
        print(headers, end="")

    config["clang_bin"] = str(OUT / "missing-compiler")
    recording_config.write_text(json.dumps(config))
    output = run("missing-compiler", cross_args, success=False)
    assert "Target compiler does not exist" in output
    wrapper.write_text("#!/bin/sh\necho deliberate-target-driver-failure >&2\nexit 7\n")
    config["clang_bin"] = str(wrapper)
    recording_config.write_text(json.dumps(config))
    output = run("failing-compiler", cross_args, success=False)
    assert "deliberate-target-driver-failure" in output

    run("native-default", [*base, "--target-dir", OUT / "native", "compile",
                           "target-config-smoke", "--name", "native-smoke"])
    output = run("native-run", [OUT / "native/native-smoke"])
    assert "target config native AOT passed" in output
    print(output, end="")
    native = json.loads((ROOT / "artifacts/build-host/target_config.json").read_text())
    native["clang_bin"] = ""
    native["triple"] = ""
    empty_config = OUT / "empty-target_config.json"
    empty_config.write_text(json.dumps(native))
    run("empty-compiler-fallback", [*base, "--target-config", empty_config,
                                   "--target-dir", OUT / "fallback", "--output-target", "object",
                                   "compile-module", "target-config-smoke"])
finally:
    recording_config.unlink(missing_ok=True)

print("target AOT: compiler selection, triple, wasm64 object, errors, native and empty fallback passed")
