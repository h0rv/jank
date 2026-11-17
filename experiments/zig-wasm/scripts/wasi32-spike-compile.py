# AI-assisted real wasi-sdk compilation of jank-generated code and unchanged Zig.
import json
import pathlib
import shlex
import subprocess
import sys

root = pathlib.Path(sys.argv[1])
out = root / 'artifacts/wasi32-spike'
database = json.loads((root / 'artifacts/build-wasi32/compile_commands.json').read_text())
entry = next(x for x in database if x['file'].endswith('/src/cpp/jank/runtime/context.cpp'))
args = iter(shlex.split(entry['command']))
flags = [next(args)]
for arg in args:
    if arg in ('-o', '-MF', '-MT', '-MQ'):
        next(args)
    elif arg not in ('-c', '-MD', '-MMD', entry['file']):
        flags.append(arg)
version = (out / 'host-version').read_text().strip()
sources = [(out / 'main.cpp', 'main', ['-Dmain=jank_spike_main']),
           (root / f'jank/target/_cache/{version}/spike/core.cpp', 'core', []),
           (root / 'wasm-probe/startup-driver.cpp', 'driver', ['-DJANK_STARTUP_SPIKE_ONLY'])]
for source, label, extra in sources:
    subprocess.run(flags + ['-O2', '-g', *extra, '-c', str(source),
                            '-o', str(out / f'{label}.o')],
                   cwd=entry['directory'], check=True)
subprocess.run([str(root / '.tools/zig-x86_64-linux-0.17.1/zig'), 'build-obj',
                str(root / 'native.zig'), '-target', 'wasm32-wasi', '-O', 'ReleaseSafe',
                f'-femit-bin={out / "zig.o"}', '--cache-dir', str(root / '.zig-cache'),
                '--global-cache-dir', str(root / '.zig-cache/global')], check=True)
