# AI-assisted local Binaryen experiment; the emsdk installation is not modified.
import os
import pathlib
import shutil
import subprocess
import sys
import time

# Seeds of the GC-reachability call graph; every function that can transitively
# call one of these (directly, through a matching table signature, or through an
# import not listed below) is flattened and spilled.
COLLECTORS = ['GC_malloc*', 'GC_generic_malloc*', 'GC_realloc*', 'GC_gcollect*',
              'GC_try_to_collect*', 'GC_collect_a_little*', 'GC_collect_or_expand',
              'GC_stopped_mark', 'GC_mark_some', 'GC_debug_malloc*', 'GC_debug_realloc*',
              'GC_memalign', 'GC_posix_memalign', 'GC_strdup', 'GC_strndup']
# Emscripten/WASI host imports that never call back into Wasm. Any other import
# (JS library code, raylib/GL, JSPI) is assumed to be able to collect.
SAFE_IMPORTS = ['wasi_snapshot_preview1.*', 'env.__syscall_*', 'env.emscripten_resize_heap',
                'env.emscripten_get_heap_max', 'env._abort_js', 'env.emscripten_date_now',
                'env.emscripten_get_now', 'env._emscripten_get_now_is_monotonic',
                'env._tzset_js', 'env._localtime_js', 'env._gmtime_js', 'env._mktime_js',
                'env._timegm_js', 'env._mmap_js', 'env._munmap_js', 'env._emscripten_memcpy_js',
                'env.emscripten_err', 'env.emscripten_out', 'env.emscripten_dbg',
                'env._emscripten_runtime_keepalive_clear', 'env._emscripten_throw_longjmp']

root, wasm = map(pathlib.Path, sys.argv[1:3])
mode = sys.argv[3] if len(sys.argv) > 3 else 'baseline'
if mode not in ('baseline', 'strip', 'Os', 'Oz', 'O3'):
    sys.exit('Expected baseline, strip, Os, Oz or O3')
optimizer = pathlib.Path(os.environ.get('SPILL_WASM_OPT', root / 'artifacts/build-binaryen/bin/wasm-opt'))
if not optimizer.is_file():
    sys.exit(f'Missing {optimizer}; build the local memory64-patched Binaryen as documented in README.md')
pipeline = os.environ.get('SPILL_PIPELINE')
if not pipeline:
    # Stock Binaryen (e.g. the wasm32 route's emsdk wasm-opt) lacks the private pass.
    try:
        with subprocess.Popen([str(optimizer), '--help'], stdout=subprocess.PIPE, text=True) as probe:
            usage = probe.communicate()[0]
    except OSError:
        usage = ''
    pipeline = 'gc-aware' if '--gc-spill-pointers' in usage else 'legacy'
baseline = wasm.with_suffix('.unspilled.wasm')
transformed = wasm.with_suffix('.transformed.wasm')
shutil.copyfile(wasm, baseline)
start = time.monotonic()
features = ['--enable-memory64', '--enable-exception-handling', '--enable-bulk-memory',
            '--enable-mutable-globals', '--enable-nontrapping-float-to-int', '--enable-sign-ext',
            '--enable-reference-types', '--enable-multivalue']
compact = ['--reorder-locals', '--coalesce-locals', '--reorder-locals']
collectors = COLLECTORS + [p for p in os.environ.get('SPILL_COLLECTORS', '').split(',') if p]
gc_aware = [f'--pass-arg=gc-spill-pointers-collectors@{",".join(collectors)}',
            f'--pass-arg=gc-spill-pointers-safe-imports@{",".join(SAFE_IMPORTS)}',
            f'--pass-arg=gc-spill-pointers-report@{wasm.with_suffix(".nospill.txt")}',
            '--strip-dwarf', '--gc-spill-pointers']
passes = {
    'legacy': ['--flatten', '--spill-pointers', *compact],
    'legacy-o3': ['--strip-dwarf', '--flatten', '--spill-pointers', '-O3'],
    'gc-aware-compact': [*gc_aware, *compact],
    'gc-aware': [*gc_aware, '-O3'],
}
if pipeline not in passes:
    sys.exit(f'SPILL_PIPELINE must be one of {", ".join(passes)}')
subprocess.run([str(optimizer), str(baseline), *features, *passes[pipeline], '-g',
                '-o', str(transformed)], check=True)
transformed.replace(wasm)
if mode != 'baseline':
    passes = ['--strip-debug', '--strip-producers']
    if mode != 'strip':
        passes += ['--dce', '--remove-unused-module-elements', '--remove-unused-names', f'-{mode}']
    subprocess.run([str(optimizer), str(wasm), *features, *passes,
                    '-o', str(transformed)], check=True)
    transformed.replace(wasm)
print(f'SPILL: pipeline={pipeline} input-bytes={baseline.stat().st_size} '
      f'output-bytes={wasm.stat().st_size} elapsed-seconds={time.monotonic() - start:.6f}', flush=True)
