"""AI-assisted spike cost probe. Run inside jank-host-build after ./jank-build build."""
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import statistics
import subprocess
import sys


def parse_sample(output: str, wasm: bool, disabled: bool) -> tuple[float, float | None, float, int, int]:
    for marker in ['jank -> Zig: scalar and wide result checks passed',
                   'jank -> Zig: borrowed-buffer checks passed']:
        if output.splitlines().count(marker) != 2:
            raise ValueError('Incorrect markers')
    timing = re.search(r'^COST ns-per-call=([\d.]+) collections-before=(\d+) '
                       r'collections-after=(\d+) gc-disabled=([01])$', output, re.M)
    if timing is None or timing[4] != str(int(disabled)) or int(timing[3]) < int(timing[2]):
        raise ValueError('Missing or invalid timing/GC record')
    startup = re.search(r'^STARTUP ms=([\d.]+)$', output, re.M)
    if wasm and startup is None:
        raise ValueError('Missing startup record')
    first_entry = re.search(r'^FIRST_ENTRY ms=([\d.]+)$', output, re.M)
    if first_entry is None:
        raise ValueError('Missing first-entry record')
    gc = re.search(r'^FIRST_ENTRY_GC collections=(\d+) ms=(\d+)$', output, re.M)
    if gc is None or (disabled and (int(gc[1]) != 0 or timing[2] != timing[3])):
        raise ValueError('Missing GC measurement')
    return (float(timing[1]), float(startup[1]) if startup else None,
            float(first_entry[1]), int(gc[1]), int(gc[2]))


if sys.argv[1:] == ['--self-test']:
    fixture = ('jank -> Zig: scalar and wide result checks passed\n'
               'jank -> Zig: borrowed-buffer checks passed\n') * 2
    record = 'COST ns-per-call=123.0 collections-before=1 collections-after=1 gc-disabled=1\n'
    valid = fixture + record + 'STARTUP ms=20.0\nFIRST_ENTRY ms=100.0\nFIRST_ENTRY_GC collections=0 ms=0\n'
    assert parse_sample(valid, True, True) == (123.0, 20.0, 100.0, 0, 0)
    assert parse_sample(valid.replace('STARTUP ms=20.0\n', ''), False, True) == (
        123.0, None, 100.0, 0, 0)
    for invalid in ['', fixture, valid.replace('passed', 'failed'),
                    valid.replace('gc-disabled=1', 'gc-disabled=0'),
                    valid.replace('STARTUP ms=20.0\n', ''),
                    valid.replace('FIRST_ENTRY ms=100.0\n', ''),
                    valid.replace('FIRST_ENTRY_GC collections=0', 'FIRST_ENTRY_GC collections=1'),
                    valid.replace('collections-after=1', 'collections-after=2'),
                    valid.replace('FIRST_ENTRY_GC collections=0 ms=0\n', '')]:
        try:
            parse_sample(invalid, True, True)
        except ValueError:
            continue
        raise AssertionError('Accepted invalid sample')
    print('SPILL COST SELF-TEST: PASS (normal, empty, missing records, markers, GC state)')
    sys.exit(0)
compare_startup = sys.argv[1:] == ['--compare-startup']
if sys.argv[1:] and not compare_startup:
    sys.exit('Usage: measure-spill-cost.py [--self-test|--compare-startup]')

ROOT = Path(__file__).resolve().parents[1]
os.chdir(ROOT)
OUT = ROOT / 'artifacts/spill-cost'
OUT.mkdir(exist_ok=True)
SDK = ROOT / '.tools/gc-wasm/emsdk'
os.environ['EM_CONFIG'] = str(SDK / '.emscripten')
os.environ['ZIG_GLOBAL_CACHE_DIR'] = str(ROOT / '.zig-cache/global')
NODE = ROOT / '.tools/node-v26.13.1-linux-x64/bin/node'
ZIG = ROOT / '.tools/zig-x86_64-linux-0.17.1/zig'
APP = ROOT / 'artifacts/app/spike'


def run(args: list[str | Path]) -> None:
    print(shlex.join(map(str, args)), flush=True)
    subprocess.run(args, check=True)


def flags(build: Path) -> list[str]:
    database = json.loads((build / 'compile_commands.json').read_text())
    entry = next(x for x in database if x['file'].endswith('/src/cpp/jank/runtime/context.cpp'))
    command = shlex.split(entry['command'])
    if '-include-pch' in command:
        command = command[:command.index('-include-pch') - 1]
    args = iter(command)
    result = [next(args)]
    for arg in args:
        if arg in ('-o', '-MF', '-MT', '-MQ'):
            next(args)
        elif arg not in ('-c', '-MD', '-MMD', entry['file']):
            result.append(arg)
    return result


for target, build in [('native', 'build-target'), ('wasm', 'build-wasm64')]:
    stage = APP / f'stage-{target}'
    modules = list((stage / 'target/_cache').glob('*/spike/core.cpp'))
    if len(modules) != 1 or not (stage / 'main.cpp').is_file():
        sys.exit(f'Missing/ambiguous spike sources in {stage}; run ./jank-build build first')
    build_dir = ROOT / 'artifacts' / build
    compile_flags = flags(build_dir)
    objects = []
    for source, label, extra in [
        (stage / 'main.cpp', 'main', ['-Dmain=jank_spike_main']),
        (modules[0], 'core', []),
        (ROOT / 'wasm-probe/spill-cost.cpp', 'driver', []),
    ]:
        obj = OUT / f'{target}-{label}.o'
        run([*compile_flags, '-O2', '-g', *extra, '-c', source, '-o', obj])
        objects.append(obj)
    zig = OUT / f'{target}-zig.o'
    run([ZIG, 'build-obj', stage / 'native.zig', '-O', 'ReleaseSafe',
         *(['-target', 'wasm64-freestanding'] if target == 'wasm' else []),
         f'-femit-bin={zig}', '--cache-dir', ROOT / '.zig-cache'])
    if target == 'native':
        run(['g++-14', *objects, zig, build_dir / 'libjank-static-runtime.a',
             '-pthread', '-ldl', '-o', OUT / 'native'])
    else:
        run([compile_flags[0], '-O2', '-g', '--profiling-funcs', '-sMEMORY64=1', '-fwasm-exceptions',
             '-sALLOW_MEMORY_GROWTH=1', '-sEXIT_RUNTIME=1', '-sSTACK_SIZE=4194304',
             '--pre-js', ROOT / 'wasm-probe/spill-cost-pre.js',
             *objects, zig, build_dir / 'libjank-static-runtime.a',
             '-Wl,--error-limit=0', '-o', OUT / 'base.js'])

features = ['--enable-memory64', '--enable-exception-handling', '--enable-bulk-memory',
            '--enable-mutable-globals', '--enable-nontrapping-float-to-int', '--enable-sign-ext',
            '--enable-reference-types', '--enable-multivalue']
optimizer = ROOT / 'artifacts/build-binaryen/bin/wasm-opt'
patch_digest = hashlib.sha256((ROOT / 'wasm-probe/binaryen-memory64-stack.patch').read_bytes()).hexdigest()
if (optimizer.parent / 'jank-memory64-patch.sha256').read_text() != patch_digest:
    sys.exit('Binaryen patch stamp is stale; refresh it with ./jank-build build first')
for variant in ['plain', *(['spill-before'] if compare_startup else []), 'spill']:
    shutil.copyfile(OUT / 'base.wasm', OUT / f'{variant}.wasm')
    if variant == 'spill':
        run([sys.executable, ROOT / 'wasm-probe/spill-pointers.py', ROOT, OUT / 'spill.wasm'])
    elif variant == 'spill-before':
        run([optimizer, OUT / 'base.wasm', *features, '--flatten', '--spill-pointers', '-g',
             '-o', OUT / 'spill-before.wasm'])
    run([optimizer, OUT / f'{variant}.wasm', *features, '--strip-debug',
         '-o', OUT / f'{variant}.stripped.wasm'])
    (OUT / f'{variant}.js').write_text((OUT / 'base.js').read_text().replace('base.wasm', f'{variant}.wasm'))

rows = []
for variant, mode in [('native', 'continuous'), ('plain', 'no-gc'),
                      *([('spill-before', 'no-gc'), ('spill-before', 'continuous')]
                        if compare_startup else []),
                      ('spill', 'no-gc'), ('spill', 'continuous')]:
    samples = []
    startups = []
    first_entries = []
    gc_collections = []
    gc_times = []
    binary = OUT / ('native' if variant == 'native' else f'{variant}.wasm')
    for sample in range(7):
        args = [binary, mode] if variant == 'native' else [NODE, OUT / f'{variant}.js', mode]
        result = subprocess.run(args, capture_output=True, text=True, timeout=120)
        output = result.stdout + result.stderr
        (OUT / f'{variant}-{mode}-{sample}.log').write_text(output)
        result.check_returncode()
        timing, startup, first_entry, collections, gc_ms = parse_sample(
            output, variant != 'native', mode == 'no-gc')
        samples.append(timing)
        first_entries.append(first_entry)
        gc_collections.append(collections)
        gc_times.append(gc_ms)
        if startup is not None:
            startups.append(startup)
    row = dict(variant=variant, mode=mode, bytes=binary.stat().st_size,
               gzip_bytes=len(gzip.compress(binary.read_bytes(), mtime=0)),
               stripped_bytes=(OUT / f'{variant}.stripped.wasm').stat().st_size
               if variant != 'native' else None,
               startup_ms=statistics.median(startups) if startups else None,
               first_entry_ms=statistics.median(first_entries), samples_first_entry_ms=first_entries,
               first_entry_gc_collections=gc_collections, first_entry_gc_ms=statistics.median(gc_times),
               ns_per_call=statistics.median(samples), samples_ns=samples,
               samples_startup_ms=startups, correctness='PASS')
    rows.append(row)
    print(json.dumps(row), flush=True)
(OUT / 'results.json').write_text(json.dumps(rows, indent=2) + '\n')
print('SPILL COST VERDICT: PASS')
