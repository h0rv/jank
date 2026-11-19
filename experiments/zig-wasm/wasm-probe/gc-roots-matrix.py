# AI-assisted real-runtime strategy matrix; failures remain failures.
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import time

root = pathlib.Path(sys.argv[1])
width = sys.argv[2] if len(sys.argv) > 2 else None
if len(sys.argv) > 3 or width not in (None, '32', '64'):
    sys.exit('Usage: gc-roots-matrix.py <experiment-root> [32|64]')
wasm_target = f'wasm{width or "64"}'
out = root / ('artifacts/gc-roots' if width is None else f'artifacts/{wasm_target}-lifetime')
logs = root / 'artifacts/logs'
out.mkdir(exist_ok=True)
sdk = pathlib.Path(os.environ.get('EMSDK', root / '.tools/gc-wasm/emsdk'))
node = root / '.tools/node-v26.13.1-linux-x64/bin/node'
cases = ['locals', 'nested', 'temporary', 'runtime-internal', 'registered-global',
         'unregistered-global', 'reclaim-control', 'operand', 'exception-local',
         'exception-payload', 'exception-stack', 'exception-rethrow', 'exception-ptr',
         'exception-error']


def run(name, command, cwd=None):
    label = 'gc-roots' if width is None else 'lifetime'
    path = logs / f'{wasm_target}-{label}-{name}.log'
    with path.open('w') as log:
        print(shlex.join(map(str, command)), file=log, flush=True)
        start = time.monotonic()
        try:
            result = subprocess.run(list(map(str, command)), cwd=cwd, stdout=log,
                                    stderr=subprocess.STDOUT, timeout=240)
            code = result.returncode
        except subprocess.TimeoutExpired:
            code = 124
        print(f'exit={code}', file=log)
        print(f'elapsed-seconds={time.monotonic() - start:.6f}', file=log)
    return code, path.read_text()


def database(target):
    build = root / f'artifacts/build-{target}'
    return build, json.loads((build / 'compile_commands.json').read_text())


def flags(entry):
    command = re.sub(r'-Xclang -include-pch -Xclang \S+ -Xclang -include -Xclang \S+',
                     '', entry['command'])
    args = iter(shlex.split(command))
    result = [next(args)]
    for arg in args:
        if arg in ('-o', '-MF', '-MT', '-MQ', '-include-pch'):
            next(args)
        elif arg not in ('-c', '-MD', '-MMD', entry['file']):
            result.append(arg)
    return result


def async_archive():
    build, db = database('wasm64')
    variant = root / 'artifacts/build-wasm64-asyncify'
    variant.mkdir(exist_ok=True)
    archive = variant / 'libjank-static-runtime.a'
    shutil.copyfile(build / archive.name, archive)
    objects = []
    for entry in db:
        if '/gc.dir/' not in entry.get('output', ''):
            continue
        obj = variant / pathlib.Path(entry['output']).name
        code, _ = run('asyncify-collector-' + obj.name,
                      flags(entry) + ['-DEMSCRIPTEN_ASYNCIFY', '-c', entry['file'], '-o', obj],
                      entry['directory'])
        if code:
            return None
        objects.append(obj)
    if not objects:
        raise RuntimeError('No collector objects found')
    code, _ = run('asyncify-archive', [sdk / 'upstream/bin/llvm-ar', 'r', archive] + objects)
    return None if code else archive


results = []
automatic_pass = False
host_pass = False
for mode in (['host', 'default', 'static-roots', 'asyncify', 'spill', 'shadow']
             if width is None else ['spill']):
    native = mode == 'host'
    spilling = mode == 'spill'
    target = 'host' if native else wasm_target
    build, db = database(target)
    entry = next(x for x in db if x['file'].endswith('/src/cpp/jank/runtime/context.cpp'))
    compile_flags = flags(entry) + ['-O2']
    if mode == 'shadow':
        compile_flags.append('-DGC_ROOTS_SHADOW')
    obj = out / f'{mode}.o'
    stage = 'compile'
    code, _ = run(mode + '-compile', compile_flags + ['-c', root / 'wasm-probe/gc-roots.cpp', '-o', obj],
                  entry['directory'])
    archive = build / 'libjank-static-runtime.a'
    if not code and mode == 'asyncify':
        stage = 'collector-build'
        archive = async_archive()
        if archive is None:
            code = 1
    exe = out / (mode if native else mode + '.js')
    if not code:
        stage = 'link'
        link = [compile_flags[0], '-O2', obj, archive]
        if native:
            link += ['-lz', '-ldl', '-pthread']
        else:
            if wasm_target == 'wasm64':
                link.append('-sMEMORY64=1')
            link += ['-fwasm-exceptions', '-Wl,--error-limit=0']
            if width is not None:
                link += ['-sSTACK_SIZE=4194304', '-sENVIRONMENT=node', '-sEXIT_RUNTIME=1']
        if mode == 'asyncify':
            link += ['-sASYNCIFY', '-sASYNCIFY_STACK_SIZE=128000']
        if spilling:
            link += ['-g', '--profiling-funcs']
        code, _ = run(mode + '-link', link + ['-o', exe])
        if not code and spilling:
            stage = 'transform'
            pipeline = ['env', 'SPILL_PIPELINE=legacy'] if width is not None else []
            code, _ = run(mode + '-transform', [*pipeline, sys.executable,
                                               root / 'wasm-probe/spill-pointers.py',
                                               root, exe.with_suffix('.wasm')])
    statuses = []
    for case in cases:
        status = 'FAIL'
        detail = f'{stage}-failed exit={code}'
        if not code:
            command = [exe] if native else [node, exe]
            strategy = 'default' if native or mode == 'default' else 'static-roots'
            rc, output = run(mode + '-' + case, command + [strategy, case])
            marker = re.search(r'^CASE ' + re.escape(case) + r': (PASS|FAIL) collections=(\d+)\b',
                               output, re.M)
            if (rc == 0 and marker and marker[1] == 'PASS' and int(marker[2]) > 0
                    and 'GC ROOTS: 1 passed, 0 failed' in output):
                status = 'PASS'
            if not rc and not marker:
                detail = 'missing-case-result exit=0'
            elif status == 'FAIL' and marker:
                detail = f'exit={rc} marker={marker[1]} collections={marker[2]}'
            else:
                detail = f'exit={rc}'
        statuses.append(status)
        results.append(f'{mode} {case}: {status} ({detail})')
    passed = all(x == 'PASS' for x in statuses)
    if mode == 'host':
        host_pass = passed
    elif mode in ('default', 'static-roots', 'asyncify', 'spill'):
        automatic_pass |= passed

path = logs / ('wasm64-gc-roots.results' if width is None else f'{wasm_target}-lifetime.results')
path.write_text('\n'.join(results) + '\n')
print(path.read_text(), end='')
sys.exit(0 if (width is not None or host_pass) and automatic_pass else 1)
