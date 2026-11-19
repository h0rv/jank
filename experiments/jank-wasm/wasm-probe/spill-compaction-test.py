"""AI-assisted regression: local compaction must preserve spill effects."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
out = root / 'artifacts/spill-compaction-test'
out.mkdir(exist_ok=True)
optimizer = root / 'artifacts/build-binaryen/bin/wasm-opt'
node = root / '.tools/node-v26.13.1-linux-x64/bin/node'
features = ['--enable-memory64', '--enable-exception-handling', '--enable-bulk-memory',
            '--enable-mutable-globals', '--enable-nontrapping-float-to-int', '--enable-sign-ext',
            '--enable-reference-types', '--enable-multivalue']


def run(args: list[str | Path]) -> str:
    return subprocess.check_output(args, text=True)


run([optimizer, root / 'wasm-probe/spill-memory64.wat', *features, '-g', '-o', out / 'input.wasm'])
run([optimizer, out / 'input.wasm', *features, '--flatten', '--spill-pointers', '-g',
     '-o', out / 'before.wasm'])
shutil.copyfile(out / 'input.wasm', out / 'after.wasm')
print(subprocess.check_output([sys.executable, root / 'wasm-probe/spill-pointers.py', root, out / 'after.wasm'],
                              text=True, env={**os.environ, 'SPILL_PIPELINE': 'legacy'}), end='')
metrics = []
for variant in ['before', 'after']:
    output = run([optimizer, out / f'{variant}.wasm', *features, '--metrics'])
    metrics.append({key: int(value) for key, value in
                    re.findall(r'^\s*(\S+)\s*:\s*(\d+)', output, re.M)})
    print(run([node, root / 'wasm-probe/spill-memory64.mjs', out / f'{variant}.wasm']), end='')
before, after = metrics
for key in ['Store', 'MemoryFill', 'GlobalSet', 'Call', 'CallIndirect', 'Try', 'Rethrow']:
    if before.get(key, 0) == 0 or before.get(key) != after.get(key):
        raise AssertionError(f'Compaction changed or fixture lacks {key}')
if after['[vars]'] >= before['[vars]']:
    raise AssertionError('Compaction did not reduce locals')
print('SPILL COMPACTION VERDICT: PASS (stores, zeroing, calls and unwind effects retained)')
