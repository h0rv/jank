"""AI-assisted regression: gc-spill-pointers skips only non-collecting code."""
import os
from pathlib import Path
import re
import subprocess

root = Path(__file__).resolve().parents[1]
out = root / 'artifacts/gc-spill-callgraph-test'
out.mkdir(parents=True, exist_ok=True)
optimizer = Path(os.environ.get('SPILL_WASM_OPT', root / 'artifacts/build-binaryen/bin/wasm-opt'))
features = ['--enable-memory64', '--enable-exception-handling', '--enable-bulk-memory',
            '--enable-mutable-globals', '--enable-reference-types']
report = out / 'skipped.txt'
text = subprocess.run(
    [optimizer, root / 'wasm-probe/gc-spill-callgraph.wat', *features, '-g',
     '--pass-arg=gc-spill-pointers-collectors@GC_malloc*,GC_gcollect*',
     '--pass-arg=gc-spill-pointers-safe-imports@env.now',
     f'--pass-arg=gc-spill-pointers-report@{report}', '--gc-spill-pointers', '--print'],
    check=True, capture_output=True, text=True)
print(text.stderr, end='')
bodies = dict(re.findall(r'^ \(func \$(\S+)(.*?)(?=^ \(func |\Z)', text.stdout, re.M | re.S))
stores = {name: body.count('i64.store') for name, body in bodies.items()}
expected_skipped = ['fib', 'leaf_indirect', 'leaf_target']
expected_stores = {'fib': 0, 'leaf_indirect': 0, 'leaf_target': 0, 'alloc_indirect': 1,
                   'mixed': 1, 'via_callback': 1, 'via_caller': 1}
skipped = report.read_text().split()
print(f'GC SPILL CALLGRAPH: skipped={skipped} stores={stores}')
if skipped != expected_skipped:
    raise AssertionError(f'Expected skipped {expected_skipped}')
if any(stores.get(name) != count for name, count in expected_stores.items()):
    raise AssertionError(f'Expected spill stores {expected_stores}')
if 'global.set $__stack_pointer' in bodies['fib'] or 'block' in bodies['leaf_target']:
    raise AssertionError('Skipped functions were transformed')
print('GC SPILL CALLGRAPH VERDICT: PASS')
