#!/usr/bin/env python3
"""AI-assisted native + experimental memory64 application driver."""
import argparse
import contextlib
import hashlib
import html.parser
import http.server
import json
import os
import pathlib
import shutil
import subprocess
import sys
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = ROOT.parent.parent
OUT = ROOT / 'artifacts/app'
LOGS = ROOT / 'artifacts/logs/app'
TOOLS = ROOT / '.tools'
CONTAINER = 'jank-host-build'
ZIG = TOOLS / 'zig-x86_64-linux-0.17.1/zig'
NODE = TOOLS / 'node-v26.13.1-linux-x64/bin/node'
MARKERS = ('jank -> Zig: scalar and wide result checks passed',
           'jank -> Zig: borrowed-buffer checks passed')


def command(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def docker(*args, root=False):
    user = [] if root else ['--user', f'{os.getuid()}:{os.getgid()}']
    return ['docker', 'exec', *user, CONTAINER, *map(str, args)]


def logged(name, args, **kwargs):
    LOGS.mkdir(parents=True, exist_ok=True)
    path = LOGS / f'{name}.log'
    print(f'Building {name} (log: {path.relative_to(ROOT)})', flush=True)
    with path.open('w') as log:
        try:
            command(args, stdout=log, stderr=subprocess.STDOUT, **kwargs)
        except subprocess.CalledProcessError:
            print(path.read_text()[-6000:], file=sys.stderr)
            raise


def container():
    result = subprocess.run(['docker', 'inspect', CONTAINER], capture_output=True, text=True)
    if result.returncode:
        command(['docker', 'run', '-d', '--name', CONTAINER,
                 '-v', f'{REPO}:{REPO}', '-w', ROOT, 'ubuntu:24.04', 'tail', '-f', '/dev/null'])
    else:
        info = json.loads(result.stdout)[0]
        if info['Config']['Image'] != 'ubuntu:24.04' or not any(
                m['Source'] == str(REPO) and m['Destination'] == str(REPO)
                for m in info['Mounts']):
            raise RuntimeError(f'{CONTAINER} must be ubuntu:24.04 with {REPO} bind-mounted at the same path')
        if not info['State']['Running']:
            command(['docker', 'start', CONTAINER])


def prerequisites():
    (ROOT / 'artifacts/tmp').mkdir(parents=True, exist_ok=True)
    TOOLS.mkdir(exist_ok=True)
    container()
    probe = subprocess.run(docker('bash', '-c',
        'test -x /usr/lib/llvm-23/bin/clang && command -v g++-14 cmake ninja >/dev/null'),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if probe.returncode:
        logged('container', docker('bash', ROOT / 'scripts/setup-app-container.sh', root=True))
    logged('submodules', ['git', '-C', REPO, 'submodule', 'update', '--init', '--recursive'])
    for tool, url, archive in [
        (ZIG, 'https://ziglang.org/download/0.17.1/zig-x86_64-linux-0.17.1.tar.xz', 'zig.tar.xz'),
        (NODE, 'https://nodejs.org/dist/v26.13.1/node-v26.13.1-linux-x64.tar.xz', 'node.tar.xz'),
    ]:
        if not tool.is_file():
            logged(archive, ['curl', '-fL', '--retry', '2', url, '-o', TOOLS / archive])
            command(['tar', '-xJf', TOOLS / archive, '-C', TOOLS])
    if subprocess.check_output([ZIG, 'version'], text=True).strip() != '0.17.1':
        raise RuntimeError('Zig must be exactly 0.17.1')
    sdk = TOOLS / 'gc-wasm/emsdk'
    if not (sdk / 'upstream/emscripten/em++').is_file() or not (sdk / '.emscripten').is_file():
        logged('emsdk', ['bash', ROOT / 'scripts/check-gc-wasm.sh', 'explicit'],
               env={**os.environ, 'BOOTSTRAP': '1', 'NODE_BIN': str(NODE)}, cwd=ROOT)
    host = ROOT / 'scripts/build-host-linux.sh'
    for artifact, step in [
        ('artifacts/build-host/jank', 'host'),
        ('artifacts/build-host/jank-phase-1', 'host'),
        ('artifacts/build-target/libjank-static-runtime.a', 'target'),
        ('.tools/host-install/lib/jank/0.1/include/jank/c_api.h', 'install'),
    ]:
        if not (ROOT / artifact).is_file():
            logged(step, docker('bash', host, step))
    if not (ROOT / 'artifacts/build-wasm64/libjank-static-runtime.a').is_file():
        for step in ['deps', 'configure', 'build']:
            logged(f'wasm-{step}', docker('bash', ROOT / 'scripts/build-wasm64-target.sh', step))
    optimizer = ROOT / 'artifacts/build-binaryen/bin/wasm-opt'
    stamp = optimizer.parent / 'jank-memory64-patch.sha256'
    patch = ROOT / 'wasm-probe/binaryen-memory64-stack.patch'
    digest = hashlib.sha256(patch.read_bytes()).hexdigest()
    if not optimizer.is_file() or not stamp.is_file() or stamp.read_text() != digest:
        archive = TOOLS / 'binaryen.tar.gz'
        source = TOOLS / 'binaryen-a9141c8cc'
        if not archive.is_file():
            logged('binaryen-download', ['curl', '-fL', '--retry', '2',
                   'https://codeload.github.com/WebAssembly/binaryen/tar.gz/a9141c8cc', '-o', archive])
        if hashlib.sha256(archive.read_bytes()).hexdigest() != 'e67fe7ca3eaf0ff562ff1fb0a4aa682857de16cc61ede27ff8ca4792cf2084ad':
            raise RuntimeError('Binaryen archive checksum mismatch')
        if not source.is_dir():
            command(['tar', '-xzf', archive, '-C', TOOLS])
        env = {**os.environ, 'GIT_CEILING_DIRECTORIES': str(TOOLS)}
        reverse = subprocess.run(['git', '-C', str(source), 'apply', '--reverse', '--check', str(patch)],
                                 env=env, capture_output=True)
        if reverse.returncode:
            command(['git', '-C', source, 'apply', '--check', patch], env=env)
            command(['git', '-C', source, 'apply', patch], env=env)
        logged('binaryen-configure', docker('cmake', '-S', source, '-B', optimizer.parent.parent,
               '-GNinja', '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_TESTS=OFF', '-DBUILD_SHARED_LIBS=OFF'))
        logged('binaryen', docker('cmake', '--build', optimizer.parent.parent, '--target', 'wasm-opt', '-j6'))
        stamp.write_text(digest)


def build(app):
    app = pathlib.Path(app).resolve()
    for name in ['native.zig', 'jank/src/spike/core.jank']:
        if not (app / name).is_file():
            raise RuntimeError(f'App must contain {name}: {app}')
    prerequisites()
    stage = OUT / 'source'
    if app == stage or stage in app.parents:
        raise RuntimeError('App sources must be outside artifacts/app/source')
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    shutil.copyfile(app / 'native.zig', stage / 'native.zig')
    shutil.copyfile(app / 'build.zig' if (app / 'build.zig').is_file() else ROOT / 'build.zig', stage / 'build.zig')
    shutil.copytree(app / 'jank/src', stage / 'jank/src', dirs_exist_ok=True)
    host = ROOT / 'scripts/build-host-linux.sh'
    logged('native', docker('env', f'JANK_ZIG_APP={stage}', 'bash', host, 'target-spike'))
    logged('wasm-spill', docker('env', f'JANK_ZIG_APP={stage}', 'JANK_ZIG_APP_MODE=1', 'bash',
                              ROOT / 'scripts/build-wasm64-target.sh', 'startup-spill'))
    native = OUT / 'native'
    native.mkdir(exist_ok=True)
    shutil.copy2(ROOT / 'artifacts/jank-zig-cpp/jank-zig', native / 'spike')
    wasm = OUT / 'wasm'
    wasm.mkdir(exist_ok=True)
    source = ROOT / 'artifacts/wasm64-spike'
    shutil.copyfile(source / 'startup-spill.wasm', wasm / 'spike.wasm')
    # Emscripten's launcher records the companion file's basename.
    js = (source / 'startup-spill.js').read_text().replace('startup-spill.wasm', 'spike.wasm')
    (wasm / 'spike.js').write_text("var Module = typeof Module !== 'undefined' ? Module : {};\n"
                                 "Module.arguments ??= ['continuous', '20'];\n" + js)
    shutil.copyfile(ROOT / 'scripts/app-index.html', wasm / 'index.html')
    print('Built artifacts/app/native/spike\nBuilt artifacts/app/wasm/{spike.js,spike.wasm,index.html}')


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


@contextlib.contextmanager
def server(port=0, bind='127.0.0.1'):
    def handler(*args, **kwargs):
        return QuietHandler(*args, directory=str(OUT / 'wasm'), **kwargs)
    with http.server.ThreadingHTTPServer((bind, port), handler) as httpd:
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            yield f'http://127.0.0.1:{httpd.server_port}/'
        finally:
            httpd.shutdown()
            thread.join()


class PageResult(html.parser.HTMLParser):
    def __init__(self):
        super().__init__()
        self.status = None
        self.in_output = False
        self.output = ''

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'html':
            self.status = attrs.get('data-status')
        if tag == 'pre' and attrs.get('id') == 'stdout':
            self.in_output = True

    def handle_endtag(self, tag):
        if tag == 'pre':
            self.in_output = False

    def handle_data(self, data):
        if self.in_output:
            self.output += data


def valid_markers(output):
    return all(marker in output.splitlines() for marker in MARKERS)


def browser_check():
    with server() as url:
        profile = ROOT / 'artifacts/app-chrome-profile'
        result = subprocess.run(['google-chrome', '--headless', '--no-sandbox', '--disable-gpu',
            '--no-first-run', '--disable-dev-shm-usage', f'--user-data-dir={profile}',
            '--virtual-time-budget=30000', '--timeout=60000', '--dump-dom', url],
            capture_output=True, text=True, timeout=90)
    (LOGS / 'browser-dom.html').write_text(result.stdout)
    (LOGS / 'browser-stderr.log').write_text(result.stderr)
    page = PageResult()
    page.feed(result.stdout)
    return result.returncode == 0 and page.status == 'pass' and valid_markers(page.output), page.output


def execute(target):
    LOGS.mkdir(parents=True, exist_ok=True)
    if target == 'browser':
        return browser_check()
    container()
    args = ([OUT / 'native/spike'] if target == 'native' else
            [NODE, OUT / 'wasm/spike.js'])
    result = subprocess.run(docker(*args), capture_output=True, text=True, timeout=120)
    output = result.stdout + result.stderr
    ok = result.returncode == 0 and valid_markers(output)
    (LOGS / f'{target}-run.log').write_text(output)
    if target == 'node':
        check = subprocess.run([sys.executable, ROOT / 'wasm-probe/startup-safepoints-check.py',
            LOGS / 'node-run.log', 'continuous', '20', str(result.returncode)],
            capture_output=True, text=True)
        output += check.stdout + check.stderr
        ok = ok and check.returncode == 0
    return ok, output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('build').add_argument('app_dir', nargs='?', default=str(ROOT))
    sub.add_parser('run').add_argument('target', choices=['native', 'node', 'browser'])
    sub.add_parser('check')
    sub.add_parser('serve').add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    if args.action == 'build':
        build(args.app_dir)
        return 0
    if not (OUT / 'wasm/index.html').is_file() or not (OUT / 'native/spike').is_file():
        raise RuntimeError('Missing app outputs; run ./jank-zig build first')
    if args.action == 'serve':
        with server(args.port) as url:
            print(f'Serving {url} (Ctrl-C to stop)', flush=True)
            threading.Event().wait()
    elif args.action == 'run' and args.target == 'browser':
        with server(8765) as url:
            print(f'Opening {url}; Ctrl-C to stop the server', flush=True)
            subprocess.Popen(['google-chrome', url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            threading.Event().wait()
    else:
        targets = ['native', 'node', 'browser'] if args.action == 'check' else [args.target]
        verdicts = []
        for target in targets:
            try:
                ok, output = execute(target)
            except (OSError, subprocess.SubprocessError, RuntimeError) as error:
                ok, output = False, str(error)
            if args.action == 'run' or not ok:
                print(output, flush=True)
            verdicts.append((target, ok))
        print('TARGET   VERDICT')
        for target, ok in verdicts:
            print(f'{target:<8} {"PASS" if ok else "FAIL"}')
        return 0 if all(ok for _, ok in verdicts) else 1


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        print(f'jank-zig: {error}', file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
