#!/usr/bin/env python3
"""AI-assisted native + experimental memory64 application driver."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import html.parser
import http.server
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass

ROOT = pathlib.Path(__file__).resolve().parent.parent
REPO = ROOT.parent.parent
OUT = ROOT / 'artifacts/app'
LOGS = ROOT / 'artifacts/logs/app'
TOOLS = ROOT / '.tools'
CONTAINER = 'jank-host-build'
NODE = TOOLS / 'node-v26.13.1-linux-x64/bin/node'
MARKERS = ('weighted buffer: 30', 'hello: checks passed')
PLAYWRIGHT_VERSION = '1.58.2'


def preflight():
    if sys.version_info < (3, 10):
        raise RuntimeError('Python 3.10+ is required')
    missing = [tool for tool in ('docker', 'git', 'curl') if not shutil.which(tool)]
    if missing:
        raise RuntimeError('Missing host prerequisites: ' + ', '.join(missing))
    result = subprocess.run(['docker', 'info'], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError('Docker daemon unreachable; start Docker and check your permissions')


def resolve_chrome():
    override = os.environ.get('CHROME')
    if override:
        found = shutil.which(override)
        if found:
            return found
        raise RuntimeError(f'CHROME is not executable: {override}')
    for name in ('google-chrome', 'chromium'):
        found = shutil.which(name)
        if found:
            return found
    for path in sorted((TOOLS / 'playwright').glob('chromium-*/chrome-linux*/chrome'), reverse=True):
        if os.access(path, os.X_OK):
            return str(path)
    raise RuntimeError('Chrome not found; run ./jank-build setup --browser')


def submodule_status():
    status = subprocess.check_output(['git', '-C', REPO, 'submodule', 'status', '--recursive'], text=True)
    return hashlib.sha256(status.encode()).hexdigest(), all(
        line.startswith(' ') for line in status.splitlines())


def ensure_submodules():
    stamp = ROOT / 'artifacts/submodules.sha256'
    digest, ready = submodule_status()
    if ready and stamp.is_file() and stamp.read_text() == digest:
        return
    logged('submodules', ['git', '-C', REPO, 'submodule', 'update', '--init', '--recursive'])
    digest, ready = submodule_status()
    if not ready:
        raise RuntimeError('Submodules are not at their pinned revisions')
    stamp.write_text(digest)


@dataclass(frozen=True)
class Project:
    root: pathlib.Path
    name: str
    main: str
    jank: pathlib.Path
    expectations: dict[str, tuple[str, ...]]
    wasm_check: str
    libraries: tuple[str, ...] = ()
    include_dirs: tuple[pathlib.Path, ...] = ()
    native_link_flags: tuple[str, ...] = ()
    wasm_link_flags: tuple[str, ...] = ()
    frame: str | None = None
    between_frame_gc: bool = False

    @property
    def out(self):
        return OUT / self.name

    def expected(self, target):
        return self.expectations[target]


def load_project(directory=ROOT, *, require_expect=True):
    root = pathlib.Path(directory).resolve()
    try:
        config = root / 'jank-build.json'
        data = json.loads(config.read_text())
    except (OSError, ValueError) as error:
        raise RuntimeError(f'Cannot read project config in {root}: {error}') from error
    if not isinstance(data, dict):
        raise RuntimeError('Project config must be an object')
    name = data.get('name', root.name)
    main = data.get('main')
    if not isinstance(name, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]*', name):
        raise RuntimeError('Project name must be a safe filename/library name')
    if not isinstance(main, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]*', main):
        raise RuntimeError('Project main must be an entry namespace')

    def source(key, default, directory):
        value = data.get(key, default)
        if not isinstance(value, str) or not value or pathlib.Path(value).is_absolute():
            raise RuntimeError(f'{key} must be a project-relative path')
        path = (root / value).resolve()
        if not path.is_relative_to(root) or not (path.is_dir() if directory else path.is_file()):
            raise RuntimeError(f'Invalid {key} source path: {value}')
        return path

    jank = source('jank', 'src', True)
    if 'zig' in data:
        raise RuntimeError('Zig projects have moved to the zig-addon branch')
    raw_expect = data.get('expect', None if require_expect else [])
    if not require_expect and raw_expect == []:
        raw_expect = {target: [] for target in ('native', 'node', 'browser')}
    if isinstance(raw_expect, list):
        raw_expect = {target: raw_expect for target in ('native', 'node', 'browser')}
    if not isinstance(raw_expect, dict) or set(raw_expect) != {'native', 'node', 'browser'}:
        raise RuntimeError('expect must be a line list or native/node/browser line lists')
    expectations = {}
    for target, lines in raw_expect.items():
        if not isinstance(lines, list) or (require_expect and not lines) or any(
                not isinstance(line, str) or not line or '\n' in line or '\r' in line for line in lines):
            raise RuntimeError(f'expect.{target} must contain nonempty exact stdout lines')
        expectations[target] = tuple(lines)
    mode = data.get('wasm_check', 'single')
    if mode not in ('single', 'spike-continuous'):
        raise RuntimeError('wasm_check must be single or spike-continuous')
    def strings(value, label):
        if not isinstance(value, list) or any(not isinstance(x, str) or not x or '\x00' in x for x in value):
            raise RuntimeError(f'{label} must be a list of nonempty strings')
        return tuple(value)

    libraries = strings(data.get('libraries', []), 'libraries')
    if any(library != 'raylib' for library in libraries) or len(set(libraries)) != len(libraries):
        raise RuntimeError('libraries supports raylib once only')
    includes = []
    for value in strings(data.get('include_dirs', []), 'include_dirs'):
        path = (root / value).resolve()
        if not path.is_dir():
            raise RuntimeError(f'Invalid include directory: {value}')
        includes.append(path)
    link_flags = {}
    for target in ('native', 'wasm'):
        options = data.get(target, {})
        if not isinstance(options, dict):
            raise RuntimeError(f'{target} must be an object')
        link_flags[target] = strings(options.get('link_flags', []), f'{target}.link_flags')
    frame = data.get('frame')
    if 'frame' in data and (not isinstance(frame, str) or not re.fullmatch(
            r'[A-Za-z_][A-Za-z0-9_.-]*/[A-Za-z_][A-Za-z0-9_!?+.*-]*', frame)):
        raise RuntimeError('frame must be a qualified ns/fn var')
    if frame and mode != 'single':
        raise RuntimeError('frame cannot be combined with spike-continuous')
    gc = data.get('wasm', {}).get('gc', 'spill')
    if gc not in ('spill', 'between-frames'):
        raise RuntimeError('wasm.gc must be spill or between-frames')
    if gc == 'between-frames' and not frame:
        raise RuntimeError('wasm.gc=between-frames requires a returning frame callback')
    if gc == 'between-frames' and any(
            flag in ('-pthread', '-pthreads') or re.fullmatch(r'(?:-s)?USE_PTHREADS(?:=.*)?', flag)
            for flag in link_flags['wasm']):
        raise RuntimeError('wasm.gc=between-frames does not support pthreads')
    return Project(root, name, main, jank, expectations, mode, libraries,
                   tuple(includes), link_flags['native'], link_flags['wasm'], frame,
                   between_frame_gc=gc == 'between-frames')


@dataclass(frozen=True)
class CDependencies:
    include_dirs: tuple[pathlib.Path, ...] = ()
    archives: tuple[pathlib.Path, ...] = ()
    link_flags: tuple[str, ...] = ()

    def include_flags(self):
        return [flag for directory in self.include_dirs for flag in ('-I', directory)]


def c_dependencies(project, platform):
    includes = list(project.include_dirs)
    archives = []
    flags = list(project.native_link_flags if platform == 'native' else project.wasm_link_flags)
    if 'raylib' in project.libraries:
        output = ROOT / 'artifacts/raylib' / ('native' if platform == 'native' else 'wasm64')
        includes.append(output / 'include')
        archives.extend(output / 'lib' / f'lib{library}.a' for library in ('raygui', 'raylib'))
        flags[:0] = (['-lGL', '-lm', '-lpthread', '-ldl', '-lrt', '-lX11'] if platform == 'native'
                     else ['-sUSE_GLFW=3', '-sMAX_WEBGL_VERSION=2'])
    return CDependencies(tuple(includes), tuple(archives), tuple(flags))


def command(args, **kwargs):
    return subprocess.run([str(x) for x in args], check=True, **kwargs)


def docker(*args, root=False, workdir=None):
    user = [] if root else ['--user', f'{os.getuid()}:{os.getgid()}']
    directory = ['--workdir', str(workdir)] if workdir else []
    return ['docker', 'exec', *user, *directory, CONTAINER, *map(str, args)]


def logged(name, args, **kwargs):
    LOGS.mkdir(parents=True, exist_ok=True)
    path = LOGS / f'{name}.log'
    display = path.relative_to(ROOT) if path.is_relative_to(ROOT) else path
    print(f'Building {name} (log: {display})', flush=True)
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


def prerequisites(project):
    preflight()
    (ROOT / 'artifacts/tmp').mkdir(parents=True, exist_ok=True)
    TOOLS.mkdir(exist_ok=True)
    container()
    probe = subprocess.run(docker('bash', '-c',
        'test -x /usr/lib/llvm-23/bin/clang && command -v g++-14 cmake ninja >/dev/null'),
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if probe.returncode:
        logged('container', docker('bash', ROOT / 'scripts/setup-app-container.sh', root=True))
    ensure_submodules()
    for tool, url, archive in [
        (NODE, 'https://nodejs.org/dist/v26.13.1/node-v26.13.1-linux-x64.tar.xz', 'node.tar.xz'),
    ]:
        if not tool.is_file():
            logged(archive, ['curl', '-fL', '--retry', '2', url, '-o', TOOLS / archive])
            command(docker('tar', '-xJf', TOOLS / archive, '-C', TOOLS))
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
    if not project.between_frame_gc and (
            not optimizer.is_file() or not stamp.is_file() or stamp.read_text() != digest):
        archive = TOOLS / 'binaryen.tar.gz'
        source = TOOLS / 'binaryen-a9141c8cc'
        if not archive.is_file():
            logged('binaryen-download', ['curl', '-fL', '--retry', '2',
                   'https://codeload.github.com/WebAssembly/binaryen/tar.gz/a9141c8cc', '-o', archive])
        if hashlib.sha256(archive.read_bytes()).hexdigest() != 'e67fe7ca3eaf0ff562ff1fb0a4aa682857de16cc61ede27ff8ca4792cf2084ad':
            raise RuntimeError('Binaryen archive checksum mismatch')
        env = {**os.environ, 'GIT_CEILING_DIRECTORIES': str(TOOLS)}
        if source.is_dir():
            checks = [subprocess.run(['git', '-C', str(source), 'apply', *flags,
                                     '--check', str(patch)], env=env, capture_output=True)
                      for flags in (['--reverse'], [])]
            if all(check.returncode for check in checks):
                backup = source.with_name(f'{source.name}-previous-{time.time_ns()}')
                print(f'Preserving obsolete private Binaryen source at {backup}', flush=True)
                source.rename(backup)
        if not source.is_dir():
            command(docker('tar', '-xzf', archive, '-C', TOOLS))
        reverse = subprocess.run(['git', '-C', str(source), 'apply', '--reverse', '--check', str(patch)],
                                 env=env, capture_output=True)
        if reverse.returncode:
            command(['git', '-C', source, 'apply', '--check', patch], env=env)
            command(['git', '-C', source, 'apply', patch], env=env)
        logged('binaryen-configure', docker('cmake', '-S', source, '-B', optimizer.parent.parent,
               '-GNinja', '-DCMAKE_BUILD_TYPE=Release', '-DBUILD_TESTS=OFF', '-DBUILD_SHARED_LIBS=OFF'))
        logged('binaryen', docker('cmake', '--build', optimizer.parent.parent, '--target', 'wasm-opt', '-j6'))
        stamp.write_text(digest)
    ensure_entries(project)
    for platform in ('native', 'wasm64'):
        if 'raylib' in project.libraries and not raylib_cached(platform):
            build_raylib(platform)


def build_raylib(platform):
    probe = subprocess.run(docker('bash', '-c', 'command -v unzip >/dev/null && command -v patch >/dev/null'),
                           capture_output=True)
    if probe.returncode:
        logged('raylib-packages', docker('bash', '-c',
               'apt-get update && apt-get install -y unzip patch', root=True))
    wrappers = TOOLS / 'app-bin'
    wrappers.mkdir(exist_ok=True)
    for tool in ('unzip', 'patch', 'make', 'emcc', 'emar'):
        path = wrappers / tool
        args = docker('env', f'EM_CONFIG={TOOLS / "gc-wasm/emsdk/.emscripten"}',
                      f'PATH={TOOLS / "gc-wasm/emsdk/upstream/emscripten"}:/usr/bin:/bin', tool)
        args.insert(2, '-i')
        path.write_text('#!/bin/sh\nexec ' + shlex.join(args) + ' "$@"\n')
        path.chmod(0o755)
    logged(f'raylib-{platform}', ['bash', ROOT / 'scripts/build-raylib.sh', platform],
           env={**os.environ, 'PATH': f'{wrappers}:{os.environ.get("PATH", "")}'})


def raylib_cached(platform):
    output = ROOT / 'artifacts/raylib' / platform
    inputs = [ROOT / 'scripts/build-raylib.sh', *sorted((ROOT / 'raylib/patches').glob('*.patch'))]
    hashes = ''.join(hashlib.sha256(path.read_bytes()).hexdigest() + '\n' for path in inputs)
    digest = hashlib.sha256(hashes.encode()).hexdigest()
    stamp = output / 'stamp'
    return (stamp.is_file() and stamp.read_text().strip() == digest and all(
        (output / 'lib' / f'lib{name}.a').is_file() for name in ('raylib', 'raygui')))


def ensure_entries(project):
    target = ROOT / 'artifacts/build-wasm64'
    flags, cwd = wasm_compile_flags(json.loads((target / 'compile_commands.json').read_text()))
    entries = [('sdk/wasm-entry.cpp', 'libjank-wasm-entry.a')]
    if 'raylib' in project.libraries:
        entries.append(('scripts/raylib-loop-driver.cpp', 'libjank-wasm-raylib-entry.a'))
    for source, name in entries:
        source = ROOT / source
        archive = target / name
        if not archive.is_file() or source.stat().st_mtime > archive.stat().st_mtime:
            obj = archive.with_suffix('.o')
            logged(name, docker('env', f'EM_CONFIG={TOOLS / "gc-wasm/emsdk/.emscripten"}',
                                *flags, '-O2', '-g', '-c', source, '-o', obj, workdir=cwd))
            logged(name + '-archive', docker(pathlib.Path(flags[0]).with_name('emar'), 'rcs', archive, obj))


def setup_components(project, browser=False):
    result = subprocess.run(docker('bash', '-c',
        'test -x /usr/lib/llvm-23/bin/clang && command -v g++-14 cmake ninja >/dev/null'),
        capture_output=True)
    digest, ready = submodule_status()
    stamp = ROOT / 'artifacts/submodules.sha256'
    rows = [('container', 'Ubuntu 24.04 / LLVM 23.1.6', pathlib.Path(CONTAINER), result.returncode == 0),
            ('submodules', 'gitlinks', stamp, ready and stamp.is_file() and stamp.read_text() == digest),
            ('Node', '26.13.1', NODE, NODE.is_file()),
            ('emsdk', '7.0.0', TOOLS / 'gc-wasm/emsdk', all(
                (TOOLS / 'gc-wasm/emsdk' / name).is_file() for name in
                ('upstream/emscripten/em++', '.emscripten')))]
    for name, path in [('host jank', 'artifacts/build-host/jank'),
                       ('host phase 1', 'artifacts/build-host/jank-phase-1'),
                       ('native runtime', 'artifacts/build-target/libjank-static-runtime.a'),
                       ('host headers', '.tools/host-install/lib/jank/0.1/include/jank/c_api.h'),
                       ('wasm64 runtime', 'artifacts/build-wasm64/libjank-static-runtime.a'),
                       ('wasm64 flags', 'artifacts/build-wasm64/compile_commands.json'),
                       ('wasm entry', 'artifacts/build-wasm64/libjank-wasm-entry.a')]:
        rows.append((name, 'fork checkout', ROOT / path, (ROOT / path).is_file()))
    optimizer = ROOT / 'artifacts/build-binaryen/bin/wasm-opt'
    stamp = optimizer.parent / 'jank-memory64-patch.sha256'
    digest = hashlib.sha256((ROOT / 'wasm-probe/binaryen-memory64-stack.patch').read_bytes()).hexdigest()
    if not project.between_frame_gc:
        rows.append(('Binaryen', 'a9141c8cc + private patch', optimizer,
                     optimizer.is_file() and stamp.is_file() and stamp.read_text() == digest))
    if 'raylib' in project.libraries:
        for platform in ('native', 'wasm64'):
            rows.append((f'raylib {platform}', '6.0 / raygui 2026.09-5',
                         ROOT / 'artifacts/raylib' / platform, raylib_cached(platform)))
        path = ROOT / 'artifacts/build-wasm64/libjank-wasm-raylib-entry.a'
        rows.append(('raylib entry', 'fork checkout', path, path.is_file()))
    if browser:
        try:
            chrome = resolve_chrome()
        except RuntimeError:
            chrome = None
        rows.append(('Chrome', f'Playwright {PLAYWRIGHT_VERSION} or host',
                     pathlib.Path(chrome) if chrome else TOOLS / 'playwright', chrome is not None))
    return rows


def setup(app=ROOT, *, check=False, browser=False):
    preflight()
    project = load_project(app)
    before = setup_components(project, browser)
    if not check:
        prerequisites(project)
        if browser:
            try:
                resolve_chrome()
            except RuntimeError:
                logged('playwright', [NODE.with_name('npx'), '--yes', f'playwright@{PLAYWRIGHT_VERSION}',
                       'install', 'chromium'], env={**os.environ,
                       'PATH': f'{NODE.parent}:{os.environ.get("PATH", "")}',
                       'npm_config_cache': str(TOOLS / 'npm-cache'),
                       'PLAYWRIGHT_BROWSERS_PATH': str(TOOLS / 'playwright')})
    rows = before if check else setup_components(project, browser)
    print('COMPONENT          PINNED VERSION                       CACHED PATH  STATE')
    for (name, version, path, ready), old in zip(rows, before):
        state = ('cached' if old[3] or check else 'built') if ready else 'missing'
        print(f'{name:<18} {version:<36} {path}  {state}')
    return 0 if all(row[3] for row in rows) else 1


def build(app):
    project = load_project(app)
    prerequisites(project)
    if project.root.is_relative_to(OUT):
        raise RuntimeError('Project sources must be outside artifacts/app')
    digest = build_digest(project)
    stamp = project.out / 'build.sha256'
    outputs = [project.out / 'native' / project.name, project.out / 'wasm/index.html',
               project.out / 'wasm' / f'{project.name}.js', project.out / 'wasm' / f'{project.name}.wasm']
    if stamp.is_file() and stamp.read_text() == digest and all(path.is_file() for path in outputs):
        print(f'CACHED: {project.out}')
        return
    for platform in ('native', 'wasm'):
        stage = project.out / f'stage-{platform}'
        if stage.exists():
            shutil.rmtree(stage)
        shutil.copytree(project.root, stage, ignore=shutil.ignore_patterns(
            'artifacts', '.tools', '.git', 'target', '__pycache__'))
        prefix = stage
        def run(label, args, **kwargs):
            cwd = kwargs.pop('cwd', stage)
            logged(f'{project.name}-{platform}-{label}', docker('env',
                f'EM_CONFIG={TOOLS / "gc-wasm/emsdk/.emscripten"}',
                *args, workdir=cwd), **kwargs)
        modules, launcher = generate_sources(project, stage, platform, prefix, run)
        if platform == 'native':
            build_native(project, stage, prefix, modules, launcher, run)
        else:
            build_wasm(project, stage, modules, launcher, run)
    if all(path.is_file() for path in outputs):
        stamp.write_text(digest)
    print(f'Built {project.out / "native" / project.name}\nBuilt {project.out / "wasm"}')


def build_digest(project):
    digest = hashlib.sha256()
    excluded = {'artifacts', '.tools', '.git', 'target', '__pycache__'}
    for base in dict.fromkeys([project.root, *project.include_dirs, ROOT / 'scripts', ROOT / 'sdk', ROOT / 'wasm-probe']):
        for directory, dirs, files in os.walk(base):
            dirs[:] = sorted(name for name in dirs if name not in excluded)
            for name in sorted(files):
                path = pathlib.Path(directory) / name
                digest.update(str(path).encode())
                digest.update(path.read_bytes())
    for path in [ROOT / 'artifacts/build-target/libjank-static-runtime.a',
                 ROOT / 'artifacts/build-wasm64/libjank-static-runtime.a',
                 ROOT / 'artifacts/build-host/jank',
                 ROOT / 'artifacts/build-binaryen/bin/wasm-opt',
                 *c_dependencies(project, 'native').archives, *c_dependencies(project, 'wasm').archives]:
        if path.is_file():
            stat = path.stat()
            digest.update(f'{path}:{stat.st_size}:{stat.st_mtime_ns}'.encode())
    digest.update(json.dumps(sorted((key, value) for key, value in os.environ.items()
                                   if key.startswith(('JANK_', 'SPILL_')))).encode())
    return digest.hexdigest()


def generate_sources(project, stage, platform, prefix, run):
    host = ROOT / 'artifacts/build-host/jank'
    flags = ['env', 'LANG=C.UTF-8', 'LC_ALL=C.UTF-8',
             f'JANK_RUNTIME_DIR={ROOT / "artifacts/host-resources"}',
             host,
             '--module-path', stage / project.jank.relative_to(project.root),
             '--target-dir', stage / 'target']
    flags.extend(c_dependencies(project, platform).include_flags())
    host_deps = c_dependencies(project, 'native')
    flags.extend(f'-l{archive}' for archive in host_deps.archives)
    if 'raylib' in project.libraries:
        flags.extend(['-lGL', '-lm', '-lpthread', '-ldl', '-lrt', '-lX11'])
    run('modules', [*flags, '--output-target', 'cpp', 'compile-module', project.main], cwd=stage)
    # compile-module emits the transitive source dependencies while loading the entry.
    # This cache belongs to a freshly created stage, never another build or platform.
    modules = sorted((stage / 'target/_cache').rglob('*.cpp'))
    if not modules:
        raise RuntimeError('compile-module produced no C++ modules')
    run('launcher', ['env', 'JANK_PRINT_CODEGEN=1', *flags, 'compile', project.main,
                     '--name', 'host-launcher'], cwd=stage)
    log = (LOGS / f'{project.name}-{platform}-launcher.log').read_text()
    marker = '/* DO NOT MODIFY: Autogenerated by jank. */'
    if marker not in log:
        raise RuntimeError('Missing generated launcher')
    launcher = stage / 'main.cpp'
    launcher.write_text(log[log.index(marker):])
    return modules, launcher


def container_output(*args):
    return subprocess.check_output(docker(*args), text=True).strip()


def build_native(project, stage, prefix, modules, launcher, run):
    deps = c_dependencies(project, 'native')
    runtime = ROOT / '.tools/host-install/lib/jank/0.1'
    stdlib = pathlib.Path(container_output('g++-14', '-print-file-name=libstdc++.so'))
    include = stdlib.parent / '../../../../include'
    triple = container_output('g++-14', '-dumpmachine')
    cpp = ['-nostdinc++', '-I', include / 'c++/14', '-I', include / triple / 'c++/14',
           '-I', include / 'c++/14/backward']
    compiler = ['/usr/lib/llvm-23/bin/clang++']
    flags = [*compiler, '-std=c++20', '-O2', '-fPIC', '-fwrapv', '-femulated-tls', *cpp,
             '-DGC_THREADS', '-DPOINTER_MASK=0x0000FFFFFFFFFFFF', '-DIMMER_HAS_LIBGC=1',
             '-DIMMER_TAGGED_NODE=0', '-DBOOST_MP_STANDALONE=1', '-DFOLLY_HAVE_JEMALLOC=0',
             '-DFOLLY_HAVE_TCMALLOC=0', '-DFOLLY_ASSUME_NO_JEMALLOC=1',
             '-DFOLLY_ASSUME_NO_TCMALLOC=1', '-DJANK_VERSION="jank-0.1-alpha"',
             '-I', runtime / 'include', '-Wno-deprecated-literal-operator',
             '-Wno-return-type-c-linkage', *deps.include_flags()]
    objects = []
    for index, source in enumerate(modules):
        obj = stage / f'module-{index}.o'
        run(f'cpp-{index}', [*flags, '-c', source, '-o', obj])
        objects.append(obj)
    output = project.out / 'native' / project.name
    output.parent.mkdir(parents=True, exist_ok=True)
    gcc = pathlib.Path(container_output('g++-14', '-print-libgcc-file-name')).parent
    run('link', [*flags, '-nostdlib++', launcher, *objects,
                ROOT / 'artifacts/build-target/libjank-static-runtime.a',
                *deps.archives, *deps.link_flags,
                f'-L{gcc}', stdlib, container_output('g++-14', '-print-file-name=libgcc_s.so'),
                '-o', output])


def wasm_compile_flags(database):
    entry = next(row for row in database if row['file'].endswith('/src/cpp/jank/runtime/context.cpp'))
    args = iter(shlex.split(entry['command']))
    flags = [next(args)]
    for arg in args:
        if arg in ('-o', '-MF', '-MT', '-MQ'):
            next(args)
        elif arg not in ('-c', '-MD', '-MMD', entry['file']):
            flags.append(arg)
    return flags, entry['directory']


def wasm_page_settings(flags):
    settings = {'MODULARIZE': '0', 'EXPORT_NAME': 'Module'}
    args = iter(flags)
    for arg in args:
        if arg == '-s':
            setting = next(args, '')
        elif arg.startswith('-s'):
            setting = arg[2:]
        else:
            continue
        name, separator, value = setting.partition('=')
        if name in settings:
            settings[name] = (value if separator else '1').strip('\'"')
    return {'modularize': settings['MODULARIZE'] not in ('0', 'false', ''),
            'exportName': settings['EXPORT_NAME']}


def build_wasm(project, stage, modules, launcher, run):
    mode = os.environ.get('JANK_WASM_BUILD_MODE', 'Oz')
    if mode not in ('baseline', 'strip', 'Os', 'Oz', 'O3'):
        raise ValueError('JANK_WASM_BUILD_MODE must be baseline, strip, Os, Oz or O3')
    optimization = os.environ.get('JANK_WASM_APP_OPT', '-O2' if mode == 'baseline' else '-Os')
    if optimization not in ('-O2', '-Os'):
        raise ValueError('JANK_WASM_APP_OPT must be -O2 or -Os')
    lto = ['-flto'] if os.environ.get('JANK_WASM_LTO') == '1' else []
    deps = c_dependencies(project, 'wasm')
    synchronous_raylib = 'raylib' in project.libraries and not project.frame
    target = ROOT / 'artifacts/build-wasm64'
    flags, cwd = wasm_compile_flags(json.loads((target / 'compile_commands.json').read_text()))
    flags.extend(deps.include_flags())
    sources = [(launcher, ['-Dmain=jank_project_main']), *[(module, []) for module in modules]]
    entry = target / 'libjank-wasm-entry.a'
    if project.wasm_check == 'spike-continuous':
        sources.append((ROOT / 'wasm-probe/startup-driver.cpp', ['-DJANK_STARTUP_SPIKE_ONLY',
                 '-DJANK_ENTRY_LAUNCHER=jank_project_main',
                 f'-DJANK_ENTRY_NS="{project.main}"', '-DJANK_ENTRY_FN="-main"']))
        entry = None
    elif synchronous_raylib:
        entry = target / 'libjank-wasm-raylib-entry.a'
    if entry is not None:
        source = ROOT / ('scripts/raylib-loop-driver.cpp' if synchronous_raylib else 'sdk/wasm-entry.cpp')
        if not entry.exists() or source.stat().st_mtime > entry.stat().st_mtime:
            obj = entry.with_suffix('.o')
            run('entry', [*flags, '-O2', '-g', '-c', source, '-o', obj], cwd=cwd)
            run('entry-archive', [pathlib.Path(flags[0]).with_name('emar'), 'rcs', entry, obj])
    if project.frame:
        namespace, function = project.frame.split('/')
        config = stage / 'wasm-config.cpp'
        config.write_text('extern "C" {\n'
                          f'char const *jank_wasm_frame_ns = {json.dumps(namespace)};\n'
                          f'char const *jank_wasm_frame_var = {json.dumps(function)};\n'
                          f'int jank_wasm_between_frame_gc = {int(project.between_frame_gc)};\n}}\n')
        sources.append((config, []))
    if entry is not None:
        roots = stage / 'wasm-roots.cpp'
        roots.write_text('#include <jank/gc.hpp>\n'
                         'extern "C" {\nextern char __global_base, __data_end;\n'
                         'void jank_wasm_register_roots() {\n'
                         'GC_add_roots(&__global_base, &__data_end);\n}\n}\n')
        sources.append((roots, []))
    libcxxabi = pathlib.Path(flags[0]).resolve().parent / 'system/lib/libcxxabi/src'
    sources.append((ROOT / 'scripts/exception-roots.cpp', ['-isystem', libcxxabi]))
    objects = []
    for index, (source, extra) in enumerate(sources):
        obj = stage / f'module-{index}.o'
        run(f'cpp-{index}', [*flags, optimization, *(['-g'] if mode == 'baseline' else []),
                            *lto, *extra, '-c', source, '-o', obj], cwd=cwd)
        objects.append(obj)
    output = project.out / 'wasm'
    output.mkdir(parents=True, exist_ok=True)
    js = output / f'{project.name}.js'
    # Only the spill transform needs __stack_pointer's global name after link.
    if mode == 'baseline':
        link_optimization = ['-O2', '-g', '--profiling-funcs']
    elif project.between_frame_gc:
        link_optimization = [f'-{mode}' if mode != 'strip' else '-O2']
    else:
        link_optimization = ['-O2', '-g2']
    run('link', [flags[0], *link_optimization,
                *lto, '-sMEMORY64=1',
                '-fwasm-exceptions', '-sALLOW_MEMORY_GROWTH=1',
                f'-sEXIT_RUNTIME={0 if project.frame else 1}',
                '-sSTACK_SIZE=4194304',
                *objects, *([entry] if entry is not None else []),
                target / 'libjank-static-runtime.a', *deps.archives, *deps.link_flags,
                *(['-sJSPI=1', '-Wl,--wrap=EndDrawing', '-Wl,--wrap=emscripten_sleep',
                    '--js-library', ROOT / 'scripts/jspi-suspend-guard.js']
                  if synchronous_raylib else []),
                *(['-sASYNCIFY=0', '-sJSPI=0', '-sSHARED_MEMORY=0', '-sWASM_WORKERS=0']
                  if project.between_frame_gc else []),
                 '-Wl,--wrap=__cxa_allocate_exception,--wrap=__cxa_free_exception',
                '-Wl,--error-limit=0', '-o', js])
    if not project.between_frame_gc:
        run('spill', ['python3', ROOT / 'wasm-probe/spill-pointers.py', ROOT, js.with_suffix('.wasm'), mode])
    arguments = ['continuous', '20'] if project.wasm_check == 'spike-continuous' else ['static-roots']
    js.write_text("var Module = typeof Module !== 'undefined' ? Module : {};\n"
                  f'Module.arguments ??= {json.dumps(arguments)};\n' + js.read_text())
    config = json.dumps({'expect': project.expected('browser'), 'arguments': arguments,
                         **wasm_page_settings(project.wasm_link_flags),
                         'continuous': project.wasm_check == 'spike-continuous',
                         'frame': project.frame,
                         'interactive': bool(project.frame or 'raylib' in project.libraries),
                         'script': js.name}).replace('<', '\\u003c')
    page = (ROOT / 'scripts/app-index.html').read_text().replace('__PROJECT_CONFIG__', config)
    (output / 'index.html').write_text(page)


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args):
        pass


@contextlib.contextmanager
def server(port=0, bind='127.0.0.1', project=None):
    project = project or load_project()
    def handler(*args, **kwargs):
        return QuietHandler(*args, directory=str(project.out / 'wasm'), **kwargs)
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
        if attrs.get('id') in ('stdout', 'app'):
            self.in_output = True

    def handle_endtag(self, tag):
        if tag in ('pre', 'div'):
            self.in_output = False

    def handle_data(self, data):
        if self.in_output:
            self.output += data


def valid_markers(output, expected=MARKERS):
    return all(marker in output.splitlines() for marker in expected)


def browser_check(project=None):
    project = project or load_project()
    chrome = resolve_chrome()
    with server(project=project) as url:
        profile = ROOT / 'artifacts/app-chrome-profile'
        result = subprocess.run([chrome, '--headless', '--no-sandbox', '--disable-gpu',
            '--no-first-run', '--disable-dev-shm-usage', f'--user-data-dir={profile}',
            '--virtual-time-budget=30000', '--timeout=60000', '--dump-dom', url],
            capture_output=True, text=True, timeout=90)
    (LOGS / f'{project.name}-browser-dom.html').write_text(result.stdout)
    (LOGS / f'{project.name}-browser-stderr.log').write_text(result.stderr)
    page = PageResult()
    page.feed(result.stdout)
    ok = result.returncode == 0 and page.status == 'pass' and valid_markers(
        page.output, project.expected('browser'))
    if project.wasm_check == 'spike-continuous':
        ok = validate_continuous(project, 'browser', page.output, result.returncode) and ok
    return ok, page.output


def validate_continuous(project, target, output, status):
    path = LOGS / f'{project.name}-{target}-run.log'
    path.write_text(output)
    check = subprocess.run([sys.executable, ROOT / 'wasm-probe/startup-safepoints-check.py',
        path, 'continuous', '20', str(status)], capture_output=True, text=True)
    return check.returncode == 0


def execute(target, project=None):
    project = project or load_project()
    LOGS.mkdir(parents=True, exist_ok=True)
    if target == 'browser':
        return browser_check(project)
    container()
    args = ([project.out / 'native' / project.name] if target == 'native' else
            [NODE, project.out / 'wasm' / f'{project.name}.js'])
    result = subprocess.run(docker(*args), capture_output=True, text=True, timeout=120)
    output = result.stdout + result.stderr
    ok = result.returncode == 0 and valid_markers(result.stdout, project.expected(target))
    (LOGS / f'{project.name}-{target}-run.log').write_text(output)
    if target == 'node' and project.wasm_check == 'spike-continuous':
        ok = validate_continuous(project, target, output, result.returncode) and ok
    return ok, output


def new_project(directory, name=None):
    root = pathlib.Path(directory).resolve()
    name = root.name if name is None else name
    if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]*', name):
        raise RuntimeError('New project name must start with a letter and contain letters, digits, _ or -')
    namespace = name.replace('_', '-') + '.core'
    source = root / 'src' / name.replace('-', '_') / 'core.jank'
    config = root / 'jank-build.json'
    if config.exists() or config.is_symlink() or source.exists() or source.is_symlink():
        raise RuntimeError('Refusing to overwrite existing project files')
    expected = f'Hello from {name}!'
    source.parent.mkdir(parents=True, exist_ok=True)
    with config.open('x') as stream:
        json.dump({'name': name, 'main': namespace, 'jank': 'src', 'expect': [expected]}, stream, indent=2)
        stream.write('\n')
    with source.open('x') as stream:
        stream.write(f';; AI-assisted pure-jank scaffold.\n(ns {namespace})\n\n'
                     f'(defn -main [& _]\n  (println {json.dumps(expected)}))\n')
    print(f'Created {root}; run ./jank-build check {root}')


def main():
    if sys.version_info < (3, 10):
        raise RuntimeError('Python 3.10+ is required')
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('sdk')
    setup_parser = sub.add_parser('setup')
    setup_parser.add_argument('--check', action='store_true')
    setup_parser.add_argument('--browser', action='store_true')
    setup_parser.add_argument('app_dir', nargs='?', default=str(ROOT))
    new_parser = sub.add_parser('new')
    new_parser.add_argument('app_dir')
    new_parser.add_argument('--name')
    for action in ('build', 'run', 'check', 'serve'):
        action_parser = sub.add_parser(action)
        if action == 'run':
            action_parser.add_argument('target', choices=['native', 'node', 'browser'])
        if action == 'serve':
            action_parser.add_argument('--port', type=int, default=8765)
        action_parser.add_argument('app_dir', nargs='?', default=str(ROOT))
    args = parser.parse_args()
    if args.action == 'setup':
        return setup(args.app_dir, check=args.check, browser=args.browser)
    if args.action == 'new':
        new_project(args.app_dir, args.name)
        return 0
    if args.action == 'sdk':
        command([sys.executable, ROOT / 'sdk/package.py'])
        return 0
    if args.action == 'build':
        build(args.app_dir)
        return 0
    project = load_project(args.app_dir)
    if args.action == 'check':
        build(args.app_dir)
    if not (project.out / 'wasm/index.html').is_file() or not (project.out / 'native' / project.name).is_file():
        raise RuntimeError('Missing app outputs; run ./jank-build build first')
    if args.action == 'serve':
        with server(args.port, project=project) as url:
            print(f'Serving {url} (Ctrl-C to stop)', flush=True)
            threading.Event().wait()
    elif args.action == 'run' and args.target == 'browser':
        with server(8765, project=project) as url:
            print(f'Opening {url}; Ctrl-C to stop the server', flush=True)
            subprocess.Popen([resolve_chrome(), url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            threading.Event().wait()
    else:
        targets = ['native', 'node', 'browser'] if args.action == 'check' else [args.target]
        verdicts = []
        for target in targets:
            try:
                ok, output = execute(target, project)
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
        print(f'jank-build: {error}', file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
