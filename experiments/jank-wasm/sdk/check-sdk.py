#!/usr/bin/env python3
"""AI-assisted extracted SDK acceptance check; builds never call Docker."""
import argparse
import importlib.util
import os
import pathlib
import shutil
import subprocess
import sys

sys.dont_write_bytecode = True

ROOT = pathlib.Path(__file__).resolve().parent.parent


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', type=pathlib.Path)
    args = parser.parse_args()
    destination = args.destination.resolve()
    destination.mkdir(parents=True, exist_ok=False)
    archive = ROOT / 'artifacts/sdk/jank-wasm-sdk-linux-x86_64.tar.gz'
    subprocess.run(['tar', '-xzf', archive, '-C', destination], check=True)
    sdk = destination / 'jank-wasm-sdk-linux-x86_64'
    env = {**os.environ, 'PATH': '/usr/bin:/bin'}
    for name in ('EM_CONFIG', 'EMSDK', 'SPILL_WASM_OPT', 'JANK_EXTRA_FLAGS', 'CXX', 'LD_LIBRARY_PATH'):
        env.pop(name, None)
    for name in ('hello-cljc', 'flappy-bird'):
        project = destination / name
        shutil.copytree(ROOT / 'examples' / name, project,
                        ignore=shutil.ignore_patterns('dist', 'target', '__pycache__'))
        subprocess.run([sdk / 'bin/jank-wasm', 'build', project], env=env, check=True)
        if name == 'hello-cljc':
            subprocess.run([sdk / 'bin/jank-wasm', 'run', project], env=env, check=True)
            spec = importlib.util.spec_from_file_location('sdk_driver', sdk / 'scripts/jank-wasm.py')
            module = importlib.util.module_from_spec(spec)
            sys.modules[spec.name] = module
            spec.loader.exec_module(module)
            common = module.common
            app = module.Project(**vars(common.load_project(project)))
            common.LOGS = project / 'dist/logs'
            ok, output = common.browser_check(app)
            print(output, flush=True)
            print(f'SDK HELLO BROWSER: {"PASS" if ok else "FAIL"}', flush=True)
            if not ok:
                return 1
        print(f'SDK {name.upper()} BUILD: PASS', flush=True)
    print(f'SDK ACCEPTANCE: PASS ({destination})', flush=True)
    return 0


if __name__ == '__main__':
    sys.exit(main())
