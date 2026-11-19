#!/usr/bin/env python3
"""AI-assisted shared ClojureScript/native/wasm benchmark. Run on the host."""
import argparse
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import time

sys.dont_write_bytecode = True
PROJECT = Path(__file__).resolve().parent
ROOT = PROJECT.parents[1]
OUT = ROOT / 'artifacts/bench-cljc'
CLJS = '1.12.145'  # Latest stable listed at clojurescript.org/news on 2026-11-17.
CLJS_SHA256 = 'fe33197a3e0e8ca9d2c52c3b4413f216ca309a0d67b4cdffe919c236c7f19f0a'
EXPECTED = dict(fib27=196418, vector100k=4999950000, map100k=5000050000,
                lazy100k=2500050000, strings1k=7889, sort5k=41666665000)
SPEC = importlib.util.spec_from_file_location('jank_build', ROOT / 'scripts/jank-build.py')
jb = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = jb
SPEC.loader.exec_module(jb)
jb.LOGS = OUT


def wasm_file(bits, variant, suffix):
    prefix = 'wasm32-' if bits == '32' else ''
    return OUT / f'{prefix}{variant}.{suffix}'


def prerequisites_wasm32():
    archive = ROOT / 'artifacts/build-wasm32/libjank-static-runtime.a'
    if archive.is_file():
        return
    start = time.perf_counter()
    for step in ('deps', 'configure', 'build'):
        run(f'wasm32-runtime-{step}', jb.docker('env', 'WASM_BITS=32', 'bash',
            ROOT / 'scripts/build-wasm64-target.sh', step))
    elapsed = time.perf_counter() - start
    (OUT / 'wasm32-runtime-build.json').write_text(json.dumps(dict(wall_seconds=elapsed)) + '\n')
    print(f'wasm32 runtime deps/configure/build wall-seconds={elapsed:.3f}', flush=True)


def parse(output, code, gc_disabled=None, require_startup=False):
    if 'Out of Memory!' in output or 'std::bad_alloc' in output:
        raise ValueError('Out of memory / std::bad_alloc; benchmark incomplete (see run log)')
    if code or output.splitlines().count('BENCH PASS') != 1 or 'CHECKSUM FAIL' in output:
        raise ValueError('Nonzero exit, missing/duplicate success marker or checksum failure')
    rows = {}
    for name, checksum, first, median in re.findall(
            r'^BENCH (\w+) checksum=(\S+) first-ms=([^ ]+) median-ms=(\S+)$', output, re.M):
        if name in rows or EXPECTED.get(name) != float(checksum):
            raise ValueError('Unknown/duplicate kernel or wrong checksum')
        records = re.findall(rf'^SAMPLES {name} (.+)$', output, re.M)
        if len(records) != 1:
            raise ValueError('Missing/duplicate sample record')
        samples = list(map(float, records[0].split(',')))
        values = [float(first), float(median), *samples]
        if len(samples) != 10 or any(not math.isfinite(x) or x < 0 for x in values):
            raise ValueError('Invalid samples')
        if not math.isclose(float(median), statistics.median(samples), rel_tol=1e-8, abs_tol=1e-6):
            raise ValueError('Median does not match samples')
        rows[name] = dict(checksum=int(float(checksum)), first_ms=float(first),
                          median_ms=float(median), samples_ms=samples)
    if set(rows) != set(EXPECTED):
        raise ValueError('Missing kernels')
    def record(pattern):
        matches = re.findall(pattern, output, re.M)
        if len(matches) != 1 or not math.isfinite(float(matches[0])) or float(matches[0]) < 0:
            raise ValueError('Missing/invalid timing record')
        return float(matches[0])
    startup = record(r'^STARTUP ms=(\S+)$') if require_startup or gc_disabled is None or 'STARTUP ms=' in output else None
    init = record(r'^INIT clock-ms=(\S+)$')
    entry = record(r'^ENTRY clock-ms=(\S+)$')
    total = record(r'^FIRST_ENTRY ms=([^ ]+)(?: gc-disabled=[01])?$')
    if entry < init or entry - init > total:
        raise ValueError('Invalid first-entry boundaries')
    if gc_disabled is not None and not re.search(
            rf'^FIRST_ENTRY ms=\S+ gc-disabled={int(gc_disabled)}$', output, re.M):
        raise ValueError('Wrong GC policy')
    return dict(kernels=rows, pre_runtime_startup_ms=startup,
                init_to_entry_ms=entry-init, first_entry_including_kernels_ms=total)


def run(label, args, **kwargs):
    path = OUT / f'{label}.log'
    print(f'{label}: {shlex.join(map(str, args))}', flush=True)
    with path.open('w') as log:
        log.write(shlex.join(map(str, args)) + '\n')
        log.flush()
        subprocess.run(list(map(str, args)), stdout=log, stderr=subprocess.STDOUT,
                       check=True, **kwargs)


def build_cljs():
    jar = ROOT / f'.tools/cljs-{CLJS}.jar'
    if not jar.exists():
        run('cljs-download', ['curl', '-fL', '--retry', '2',
            f'https://github.com/clojure/clojurescript/releases/download/r{CLJS}/cljs.jar', '-o', jar])
    if hashlib.sha256(jar.read_bytes()).hexdigest() != CLJS_SHA256:
        raise RuntimeError('ClojureScript jar checksum mismatch')
    java = ROOT / '.tools/jdk-21.0.9+10-jre/bin/java'
    if not java.exists():
        archive = ROOT / '.tools/jre21.tar.gz'
        run('java-download', ['curl', '-fL', '--retry', '2',
            'https://github.com/adoptium/temurin21-binaries/releases/download/jdk-21.0.9%2B10/'
            'OpenJDK21U-jre_x64_linux_hotspot_21.0.9_10.tar.gz', '-o', archive])
        if hashlib.sha256(archive.read_bytes()).hexdigest() != (
                'aeab55d064a1a27a3744b0880b9b414077b4ed2b1790817eea3df60aec946431'):
            raise RuntimeError('JRE archive checksum mismatch')
        run('java-extract', ['tar', '-xzf', archive, '-C', ROOT / '.tools'])
    home = ROOT / '.tools/cljs-home'
    home.mkdir(exist_ok=True)
    options = '{:target :nodejs :optimizations :advanced :main bench.core :output-to "' + str(
        OUT / 'cljs.js') + '" :output-dir "' + str(OUT / 'cljs-cache') + '"}'
    run('cljs-compile', [java, '-Xmx2g', f'-Duser.home={home}', f'-Djava.io.tmpdir={OUT}', '-cp',
        f'{jar}:{PROJECT / "src"}', 'cljs.main', '-co', options, '-c', 'bench.core'], cwd=OUT)
    (OUT / 'cljs-run.cjs').write_text(
        'console.log("STARTUP ms=" + process.uptime()*1000);\n'
        'const start = performance.now(); console.log("INIT clock-ms=" + start);\n'
        'require("./cljs.js");\n'
        'console.log("FIRST_ENTRY ms=" + (performance.now()-start));\n')


def build_jank(platform, state):
    project = jb.load_project(PROJECT)
    stage = project.out / f'stage-{platform}'
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(PROJECT, stage, ignore=shutil.ignore_patterns('__pycache__'))
    def command(label, args, **kwargs):
        if label == 'link':
            state['compile'] = 'PASS'
        state['phase'] = {'link': 'link', 'spill': 'transform'}.get(label, 'compile')
        run(f'{project.name}-{platform}-{label}', jb.docker('env',
            f'EM_CONFIG={ROOT / ".tools/gc-wasm/emsdk/.emscripten"}', *args,
            workdir=kwargs.pop('cwd', stage)), **kwargs)
    modules, launcher = jb.generate_sources(project, stage, platform, stage / 'zig-out', command)
    text = launcher.read_text()
    text, count = re.subn(r'\bmain\s*\(', 'bench_entry(', text)
    if count != 1:
        raise RuntimeError(f'Expected one generated main, found {count}')
    launcher.write_text(text)
    if platform == 'native':
        launcher.write_text(text + '\n' + (PROJECT / 'timing.cpp').read_text())
        jb.build_native(project, stage, stage / 'zig-out', modules, launcher, command)
        return
    bits = platform.removeprefix('wasm')
    target = ROOT / f'artifacts/build-wasm{bits}'
    flags, cwd = jb.wasm_compile_flags(json.loads((target / 'compile_commands.json').read_text()))
    objects = []
    for i, source in enumerate([launcher, *modules, PROJECT / 'timing.cpp']):
        obj = stage / f'bench-{i}.o'
        command(f'cpp-{i}', [*flags, '-O2', '-g', '-c', source, '-o', obj], cwd=cwd)
        objects.append(obj)
    pre = OUT / 'pre.js'
    pre.write_text('Module.preRun = [function() {console.log("STARTUP ms=" + process.uptime()*1000);}];\n')
    command('link', [flags[0], '-O2', '-g', '--profiling-funcs', *(['-sMEMORY64=1'] if bits == '64' else []),
        '-fwasm-exceptions', '-sALLOW_MEMORY_GROWTH=1', '-sEXIT_RUNTIME=1', '-sSTACK_SIZE=4194304',
        '--pre-js', pre, *objects, target / 'libjank-static-runtime.a',
        '-Wl,--error-limit=0', '-o', wasm_file(bits, 'unsafe', 'js')])


def spill(bits='64'):
    source = wasm_file(bits, 'unsafe', 'wasm')
    output = wasm_file(bits, 'spill', 'wasm')
    shutil.copyfile(source, output)
    wasm_file(bits, 'spill', 'js').write_text(wasm_file(bits, 'unsafe', 'js').read_text().replace(source.name, output.name))
    optimizer = (['env', f'SPILL_WASM_OPT={ROOT / ".tools/gc-wasm/emsdk/upstream/bin/wasm-opt"}']
                 if bits == '32' else [])
    run(f'wasm{bits}-spill', jb.docker(*optimizer, 'python3', ROOT / 'wasm-probe/spill-pointers.py', ROOT, output))


def execute(target, node):
    if target == 'native':
        binary = jb.load_project(PROJECT).out / 'native/bench-cljc'
        script = ('import subprocess,time,json; t=time.perf_counter(); '
                  'r=subprocess.run([' + repr(str(binary)) + '],capture_output=True,text=True); '
                  'print(json.dumps(dict(code=r.returncode,output=r.stdout+r.stderr,'
                  'wall_ms=(time.perf_counter()-t)*1000)))')
        result = subprocess.run(jb.docker('python3', '-c', script), check=True,
                                capture_output=True, text=True, timeout=600)
        return json.loads(result.stdout)
    file = (OUT / 'cljs-run.cjs' if target == 'cljs-js' else
            wasm_file(target.split('-')[0].removeprefix('wasm'), target.split('-')[1], 'js'))
    args = [node, file, *(['unsafe-no-gc'] if target.endswith('-unsafe') else [])]
    start = time.perf_counter()
    result = subprocess.run(list(map(str, args)), capture_output=True, text=True, timeout=600)
    return dict(code=result.returncode, output=result.stdout+result.stderr,
                wall_ms=(time.perf_counter()-start)*1000)


def markdown(data):
    lines = ['| Target | Compile | Link/transform | Execute | Correctness | Process wall ms | Init → entry ms |',
             '| --- | --- | --- | --- | --- | ---: | ---: |']
    for target, row in data['targets'].items():
        wall = f'{row["wall_ms"]:.3f}' if 'wall_ms' in row else '—'
        entry = f'{row["init_to_entry_ms"]:.3f}' if 'init_to_entry_ms' in row else '—'
        lines.append(f'| {target} | {row["compile"]} | {row["link"]} | {row["execute"]} | '
                     f'{row["correctness"]} | {wall} | {entry} |')
    lines += ['', '| Target | Pre-runtime startup ms | First entry including kernels ms |',
              '| --- | ---: | ---: |']
    for target, row in data['targets'].items():
        startup = row.get('pre_runtime_startup_ms')
        total = row.get('first_entry_including_kernels_ms')
        lines.append(f'| {target} | ' + (f'{startup:.3f}' if startup is not None else 'N/A') +
                     ' | ' + (f'{total:.3f}' if total is not None else 'N/A') + ' |')
    lines += ['', '| Kernel | Target | Checksum | First ms | Warm median ms (10) |',
              '| --- | --- | ---: | ---: | ---: |']
    for target, row in data['targets'].items():
        for name, kernel in row.get('kernels', {}).items():
            lines.append(f'| {name} | {target} | {kernel["checksum"]} | {kernel["first_ms"]:.3f} | {kernel["median_ms"]:.3f} |')
    lines += ['', '| Wasm target | Module bytes |', '| --- | ---: |']
    for target, row in data['targets'].items():
        if 'module_bytes' in row:
            lines.append(f'| {target} | {row["module_bytes"]} |')
    lines += ['', '| Kernel | spill / cljs-js (warm) | spill / native (warm) |',
              '| --- | ---: | ---: |']
    targets = data['targets']
    for name in EXPECTED:
        ratios = []
        for baseline in ['cljs-js', 'native']:
            a = targets.get('wasm64-spill', {}).get('kernels', {}).get(name)
            b = targets.get(baseline, {}).get('kernels', {}).get(name)
            ratios.append(f'{a["median_ms"] / b["median_ms"]:.3f}×' if a and b and b['median_ms'] else 'N/A')
        lines.append(f'| {name} | ' + ' | '.join(ratios) + ' |')
    return '\n'.join(lines) + '\n'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--targets', nargs='+', choices=['cljs-js', 'native', 'wasm64-spill', 'wasm64-unsafe', 'wasm32-spill', 'wasm32-unsafe'],
                        default=['cljs-js', 'native', 'wasm64-spill', 'wasm64-unsafe'])
    parser.add_argument('--skip-build', action='store_true')
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    node = shutil.which('node')
    (ROOT / '.tools').mkdir(exist_ok=True)
    data = dict(metadata=dict(cljs=CLJS, node=subprocess.check_output([node, '--version'], text=True).strip(),
        node_path=node, source_sha256=hashlib.sha256((PROJECT / 'src/bench/core.cljc').read_bytes()).hexdigest(),
        jank_commit=subprocess.check_output(['git', '-C', ROOT, 'rev-parse', 'HEAD'], text=True).strip(),
        nproc=len(os.sched_getaffinity(0)), cpu=next(x.split(':', 1)[1].strip() for x in
        Path('/proc/cpuinfo').read_text().splitlines() if x.startswith('model name'))), targets={})
    data['metadata']['binaryen_patch_sha256'] = hashlib.sha256(
        (ROOT / 'wasm-probe/binaryen-memory64-stack.patch').read_bytes()).hexdigest()
    data['metadata']['java'] = 'Eclipse Temurin JRE 21.0.9+10 (local; system Java 17 is too old for Closure)'
    data['metadata']['zig'] = 'not used (pure Clojure project; experiment pin remains 0.17.1)'
    sdk = ROOT / '.tools/gc-wasm/emsdk/upstream/emscripten/emscripten-version.txt'
    data['metadata']['emsdk'] = sdk.read_text().strip() if sdk.exists() else 'not installed'
    prerequisite_error = None
    if not args.skip_build and any(t != 'cljs-js' for t in args.targets):
        try:
            jb.prerequisites(jb.load_project(PROJECT))
            if any(t.startswith('wasm32-') for t in args.targets):
                prerequisites_wasm32()
        except Exception as error:
            prerequisite_error = str(error)
        data['metadata']['emsdk'] = sdk.read_text().strip() if sdk.exists() else 'not installed'
    data['metadata']['cljs_jar_sha256'] = CLJS_SHA256
    built = set()
    failed = {}
    for target in args.targets:
        row = dict(compile='NOT RUN', link='NOT RUN', execute='NOT RUN', correctness='NOT CHECKED')
        data['targets'][target] = row
        group = target.split('-')[0] if target.startswith('wasm') else target
        state = dict(phase='compile')
        try:
            if group != 'cljs-js' and prerequisite_error:
                raise RuntimeError('Prerequisites failed: ' + prerequisite_error)
            if group in failed:
                message, previous = failed[group]
                state.update(previous)
                raise RuntimeError(message)
            if not args.skip_build and group not in built:
                try:
                    build_cljs() if group == 'cljs-js' else build_jank(group, state)
                except Exception as error:
                    failed[group] = str(error), dict(state)
                    raise
                built.add(group)
            row.update(compile='PASS', link='PASS' if group != 'cljs-js' else 'N/A (Closure advanced)')
            if target.endswith('-spill') and not args.skip_build:
                state['phase'] = 'transform'
                spill(group.removeprefix('wasm'))
            if target.startswith('wasm'):
                row['module_bytes'] = wasm_file(group.removeprefix('wasm'), target.split('-')[1], 'wasm').stat().st_size
            state['phase'] = 'execute'
            sample = execute(target, node)
            (OUT / f'{target}-run.log').write_text(sample['output'])
            row['wall_ms'] = sample['wall_ms']
            row['execute'] = f'exit {sample["code"]}'
            state['phase'] = 'correctness'
            row.update(parse(sample['output'], sample['code'],
                None if target == 'cljs-js' else target.endswith('-unsafe'),
                require_startup=target.startswith('wasm')))
            row['correctness'] = 'PASS'
        except Exception as error:
            if 'compile' in state:
                row['compile'] = state['compile']
            row[state['phase'] if state['phase'] in row else 'link'] = 'FAIL'
            row['error'] = str(error)
            print(f'{target}: FAIL ({state["phase"]}): {error}', flush=True)
        (OUT / 'results.json').write_text(json.dumps(data, indent=2) + '\n')
    table = markdown(data)
    (OUT / 'results.md').write_text(table)
    print(table)
    print('BENCHMARK VERDICT: ' + ('PASS' if all(r['correctness'] == 'PASS' for r in data['targets'].values()) else 'FAIL'))
    return 0 if all(r['correctness'] == 'PASS' for r in data['targets'].values()) else 1


if __name__ == '__main__':
    sys.exit(main())
