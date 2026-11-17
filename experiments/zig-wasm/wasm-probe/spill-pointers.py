# AI-assisted local Binaryen experiment; the emsdk installation is not modified.
import os
import pathlib
import shutil
import subprocess
import sys
import time

root, wasm = map(pathlib.Path, sys.argv[1:])
optimizer = pathlib.Path(os.environ.get('SPILL_WASM_OPT', root / 'artifacts/build-binaryen/bin/wasm-opt'))
if not optimizer.is_file():
    sys.exit(f'Missing {optimizer}; build the local memory64-patched Binaryen as documented in README.md')
baseline = wasm.with_suffix('.unspilled.wasm')
transformed = wasm.with_suffix('.transformed.wasm')
shutil.copyfile(wasm, baseline)
start = time.monotonic()
features = ['--enable-memory64', '--enable-exception-handling', '--enable-bulk-memory',
            '--enable-mutable-globals', '--enable-nontrapping-float-to-int', '--enable-sign-ext',
            '--enable-reference-types', '--enable-multivalue']
subprocess.run([str(optimizer), str(baseline), *features, '--flatten', '--spill-pointers',
                '--reorder-locals', '--coalesce-locals', '--reorder-locals', '-g',
                '-o', str(transformed)], check=True)
transformed.replace(wasm)
print(f'SPILL: input-bytes={baseline.stat().st_size} output-bytes={wasm.stat().st_size} '
      f'elapsed-seconds={time.monotonic() - start:.6f}', flush=True)
