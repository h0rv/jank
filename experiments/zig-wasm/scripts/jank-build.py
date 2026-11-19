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
ZIG = TOOLS / 'zig-x86_64-linux-0.17.1/zig'
NODE = TOOLS / 'node-v26.13.1-linux-x64/bin/node'
MARKERS = ('jank -> Zig: scalar and wide result checks passed',
           'jank -> Zig: borrowed-buffer checks passed')


@dataclass(frozen=True)
class Project:
    root: pathlib.Path
    name: str
    main: str
    jank: pathlib.Path
    zig: pathlib.Path | None
    expectations: dict[str, tuple[str, ...]]
    wasm_check: str
    libraries: tuple[str, ...] = ()
    include_dirs: tuple[pathlib.Path, ...] = ()
    native_link_flags: tuple[str, ...] = ()
    wasm_link_flags: tuple[str, ...] = ()
    frame: str | None = None

    @property
    def out(self):
        return OUT / self.name

    def expected(self, target):
        return self.expectations[target]


def load_project(directory=ROOT):
    root = pathlib.Path(directory).resolve()
    try:
        config = root / 'jank-build.json'
        if not config.exists():
            config = root / 'jank-zig.json'
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
    zig = source('zig', 'native.zig', False) if 'zig' in data else None
    raw_expect = data.get('expect')
    if isinstance(raw_expect, list):
        raw_expect = {target: raw_expect for target in ('native', 'node', 'browser')}
    if not isinstance(raw_expect, dict) or set(raw_expect) != {'native', 'node', 'browser'}:
        raise RuntimeError('expect must be a line list or native/node/browser line lists')
    expectations = {}
    for target, lines in raw_expect.items():
        if not isinstance(lines, list) or not lines or any(
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
    return Project(root, name, main, jank, zig, expectations, mode, libraries,
                   tuple(includes), link_flags['native'], link_flags['wasm'], frame)


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


def prerequisites(project):
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
        *([(ZIG, 'https://ziglang.org/download/0.17.1/zig-x86_64-linux-0.17.1.tar.xz', 'zig.tar.xz')]
          if project.zig is not None else []),
        (NODE, 'https://nodejs.org/dist/v26.13.1/node-v26.13.1-linux-x64.tar.xz', 'node.tar.xz'),
    ]:
        if not tool.is_file():
            logged(archive, ['curl', '-fL', '--retry', '2', url, '-o', TOOLS / archive])
            command(['tar', '-xJf', TOOLS / archive, '-C', TOOLS])
    if project.zig is not None and subprocess.check_output([ZIG, 'version'], text=True).strip() != '0.17.1':
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
            command(['tar', '-xzf', archive, '-C', TOOLS])
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
    project = load_project(app)
    prerequisites(project)
    if project.root.is_relative_to(OUT):
        raise RuntimeError('Project sources must be outside artifacts/app')
    for platform in ('native', 'wasm'):
        for library in project.libraries:
            logged(f'{project.name}-{platform}-{library}', ['bash', ROOT / 'scripts' / f'build-{library}.sh',
                   'native' if platform == 'native' else 'wasm64'])
        stage = project.out / f'stage-{platform}'
        if stage.exists():
            shutil.rmtree(stage)
        shutil.copytree(project.root, stage, ignore=shutil.ignore_patterns(
            'artifacts', '.tools', '.git', 'target', 'zig-out', '.zig-cache', '__pycache__'))
        if project.zig is not None and not (stage / 'build.zig').is_file():
            template = (ROOT / 'scripts/project-build.zig').read_text()
            (stage / 'build.zig').write_text(template.replace('__ZIG_ROOT__',
                json.dumps(str(project.zig.relative_to(project.root)))).replace('__LIBRARY_NAME__',
                json.dumps(project.name)))
        prefix = stage / 'zig-out'
        def run(label, args, **kwargs):
            cwd = kwargs.pop('cwd', stage)
            logged(f'{project.name}-{platform}-{label}', docker('env',
                f'EM_CONFIG={TOOLS / "gc-wasm/emsdk/.emscripten"}',
                f'ZIG_GLOBAL_CACHE_DIR={ROOT / ".zig-cache/global"}',
                *args, workdir=cwd), **kwargs)
        if project.zig is not None:
            run('zig', [ZIG, 'build', '--build-file', stage / 'build.zig', '-Doptimize=ReleaseSafe',
                        '--prefix', prefix, '--cache-dir', stage / '.zig-cache'])
        modules, launcher = generate_sources(project, stage, platform, prefix, run)
        if platform == 'native':
            build_native(project, stage, prefix, modules, launcher, run)
        else:
            build_wasm(project, stage, modules, launcher, run)
    print(f'Built {project.out / "native" / project.name}\nBuilt {project.out / "wasm"}')


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
    if project.zig is not None:
        flags.extend(['-L', prefix / 'lib', f'-l:{project.name}'])
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
    compiler = [ZIG, 'c++'] if project.zig is not None else ['/usr/lib/llvm-23/bin/clang++']
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
    libraries = [prefix / 'lib' / f'lib{project.name}.a'] if project.zig is not None else []
    run('link', [*flags, '-nostdlib++', launcher, *objects, *libraries,
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
    sources = [(launcher, ['-Dmain=jank_project_main']), *[(module, []) for module in modules],
               (ROOT / 'wasm-probe/startup-driver.cpp', ['-DJANK_STARTUP_SPIKE_ONLY',
                 '-DJANK_ENTRY_LAUNCHER=jank_project_main',
                 f'-DJANK_ENTRY_NS="{project.main}"', '-DJANK_ENTRY_FN="-main"'])]
    if project.frame:
        namespace, function = project.frame.split('/')
        sources[-1] = (ROOT / 'scripts/frame-driver.cpp',
                       [f'-DJANK_FRAME_NS="{namespace}"', f'-DJANK_FRAME_FN="{function}"'])
    elif synchronous_raylib:
        sources[-1] = (ROOT / 'scripts/raylib-loop-driver.cpp', [])
    objects = []
    for index, (source, extra) in enumerate(sources):
        obj = stage / f'module-{index}.o'
        run(f'cpp-{index}', [*flags, optimization, *(['-g'] if mode == 'baseline' else []),
                            *lto, *extra, '-c', source, '-o', obj], cwd=cwd)
        objects.append(obj)
    if project.zig is not None:
        zig = stage / 'kernel.o'
        run('kernel', [ZIG, 'build-obj', stage / project.zig.relative_to(project.root),
                      '-target', 'wasm64-freestanding', '-O', 'ReleaseSafe', f'-femit-bin={zig}',
                      '--cache-dir', stage / '.zig-cache'])
        objects.append(zig)
    output = project.out / 'wasm'
    output.mkdir(parents=True, exist_ok=True)
    js = output / f'{project.name}.js'
    # The spill transform needs __stack_pointer's global name until post-link.
    run('link', [flags[0], '-O2', *(['-g', '--profiling-funcs'] if mode == 'baseline' else ['-g2']),
                *lto, '-sMEMORY64=1',
                '-fwasm-exceptions', '-sALLOW_MEMORY_GROWTH=1',
                f'-sEXIT_RUNTIME={0 if project.frame else 1}',
                '-sSTACK_SIZE=4194304',
                *objects, target / 'libjank-static-runtime.a', *deps.archives, *deps.link_flags,
                *(['-sJSPI=1', '-Wl,--wrap=EndDrawing'] if synchronous_raylib else []),
                '-Wl,--error-limit=0', '-o', js])
    run('spill', ['python3', ROOT / 'wasm-probe/spill-pointers.py', ROOT, js.with_suffix('.wasm'), mode])
    arguments = ['continuous', '20'] if project.wasm_check == 'spike-continuous' else ['static-roots']
    js.write_text("var Module = typeof Module !== 'undefined' ? Module : {};\n"
                  f'Module.arguments ??= {json.dumps(arguments)};\n' + js.read_text())
    config = json.dumps({'expect': project.expected('browser'), 'arguments': arguments,
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
    with server(project=project) as url:
        profile = ROOT / 'artifacts/app-chrome-profile'
        result = subprocess.run(['google-chrome', '--headless', '--no-sandbox', '--disable-gpu',
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


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('build', 'run', 'check', 'serve'):
        action_parser = sub.add_parser(action)
        if action == 'run':
            action_parser.add_argument('target', choices=['native', 'node', 'browser'])
        if action == 'serve':
            action_parser.add_argument('--port', type=int, default=8765)
        action_parser.add_argument('app_dir', nargs='?', default=str(ROOT))
    args = parser.parse_args()
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
            subprocess.Popen(['google-chrome', url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
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
