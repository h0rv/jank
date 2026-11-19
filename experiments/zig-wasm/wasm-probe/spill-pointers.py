# AI-assisted local Binaryen experiment; the emsdk installation is not modified.
import argparse
import os
import pathlib
import shutil
import subprocess
import time

parser = argparse.ArgumentParser()
parser.add_argument('root', type=pathlib.Path)
parser.add_argument('wasm', type=pathlib.Path)
parser.add_argument('mode', nargs='?', default='baseline', choices=('baseline', 'strip', 'Os', 'Oz', 'O3'))
parser.add_argument('--no-coalesce', action='store_true')
args = parser.parse_args()
root, wasm, mode = args.root, args.wasm, args.mode
optimizer = pathlib.Path(os.environ.get('SPILL_WASM_OPT', root / 'artifacts/build-binaryen/bin/wasm-opt'))
if not optimizer.is_file():
    parser.exit(1, f'Missing {optimizer}; build the local memory64-patched Binaryen as documented in README.md\n')
baseline = wasm.with_suffix('.unspilled.wasm')
transformed = wasm.with_suffix('.transformed.wasm')
shutil.copyfile(wasm, baseline)
start = time.monotonic()
features = ['--enable-memory64', '--enable-exception-handling', '--enable-bulk-memory',
            '--enable-mutable-globals', '--enable-nontrapping-float-to-int', '--enable-sign-ext',
            '--enable-reference-types', '--enable-multivalue']
cleanup = [] if args.no_coalesce else ['--reorder-locals', '--coalesce-locals', '--reorder-locals']
subprocess.run([str(optimizer), str(baseline), *features, '--flatten', '--spill-pointers',
                *cleanup, '-g',
                '-o', str(transformed)], check=True)
transformed.replace(wasm)
if mode != 'baseline':
    passes = ['--strip-debug', '--strip-producers']
    if mode != 'strip':
        passes += ['--dce', '--remove-unused-module-elements', '--remove-unused-names', f'-{mode}']
    subprocess.run([str(optimizer), str(wasm), *features, *passes,
                    '-o', str(transformed)], check=True)
    transformed.replace(wasm)
print(f'SPILL: input-bytes={baseline.stat().st_size} output-bytes={wasm.stat().st_size} '
      f'elapsed-seconds={time.monotonic() - start:.6f}', flush=True)
