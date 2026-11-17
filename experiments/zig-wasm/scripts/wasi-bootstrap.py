#!/usr/bin/env python3
"""AI-assisted reuse of the existing container/bootstrap path for the WASI spike."""
import importlib.util
import os
import pathlib
import shutil
import subprocess
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('jank_zig', ROOT / 'scripts/jank-zig.py')
driver = importlib.util.module_from_spec(spec)
spec.loader.exec_module(driver)
source = ROOT / '.tools/binaryen-a9141c8cc'
patch = ROOT / 'wasm-probe/binaryen-memory64-stack.patch'
if source.is_dir():
    env = {**os.environ, 'GIT_CEILING_DIRECTORIES': str(source.parent)}
    def applies(*flags):
        return subprocess.run(['git', '-C', str(source), 'apply', *flags, '--check', str(patch)],
                              env=env, capture_output=True).returncode == 0
    if not applies('--reverse') and not applies():
        backup = ROOT / f'.tools/wasi/binaryen-previous-{time.time_ns()}'
        backup.parent.mkdir(parents=True, exist_ok=True)
        print(f'Preserving obsolete private Binaryen source at {backup}', flush=True)
        shutil.move(str(source), backup)

driver.prerequisites()
driver.logged('wasi-native-spike', driver.docker('bash', ROOT / 'scripts/build-host-linux.sh', 'spike'))
driver.logged('wasi-startup-spill', driver.docker('bash', ROOT / 'scripts/build-wasm64-target.sh', 'startup-spill'))
