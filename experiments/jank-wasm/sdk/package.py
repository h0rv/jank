#!/usr/bin/env python3
"""AI-assisted Linux x86_64 offline SDK assembly from completed research builds."""
import importlib.util
import json
import os
import pathlib
import re
import shlex
import shutil
import subprocess
import sys
import tarfile

sys.dont_write_bytecode = True

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location('jank_build', ROOT / 'scripts/jank-build.py')
common = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = common
SPEC.loader.exec_module(common)
SDK = ROOT / 'artifacts/sdk/jank-wasm-sdk-linux-x86_64'


def copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if source.is_dir():
        shutil.copytree(source, destination, dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc'))
    else:
        shutil.copy2(source, destination)


def container_copy(source, destination):
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.is_dir():
        shutil.rmtree(destination)
    elif destination.exists():
        destination.unlink()
    subprocess.run(['docker', 'cp', '-L', f'{common.CONTAINER}:{source}', destination], check=True)


def executable(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    path.chmod(0o755)


def bundle_executable(source, name, *, directory='bin'):
    binary = SDK / 'host' / directory / name
    container_copy(source, binary)
    output = subprocess.check_output(common.docker('ldd', source), text=True)
    if 'not found' in output:
        raise RuntimeError(f'Unresolved shared-library closure for {source}: {output}')
    for library in set(re.findall(r'(?:=>\s+)?(/[^\s()]+)', output)):
        destination = SDK / 'host/lib' / pathlib.Path(library).name
        if not destination.exists():
            container_copy(library, destination)
    return binary


def wrapper(binary, relative_root):
    preload = '--preload "$root/host/lib/libjank-sdk-host.so" ' if binary == 'jank' else ''
    prefix = ('#!/bin/sh\nset -eu\n'
              f'root=$(CDPATH= cd -- "$(dirname -- "$0")/{relative_root}" && pwd)\n')
    if binary == 'clang':
        return (prefix + 'case "${1-}" in -cc1*)\n'
                'exec "$root/host/lib/ld-linux-x86-64.so.2" --library-path "$root/host/lib" '
                '"$root/host/bin/clang" "$@" ;; esac\n'
                'exec "$root/host/lib/ld-linux-x86-64.so.2" --library-path "$root/host/lib" '
                '--argv0 "$root/artifacts/host-resources/bin/clang++" '
                '"$root/host/bin/clang" -no-canonical-prefixes '
                '-resource-dir "$root/host/lib/clang/23" "$@"\n')
    return (prefix +
            'exec "$root/host/lib/ld-linux-x86-64.so.2" '
            '--library-path "$root/host/lib" '
            f'{preload}"$root/host/bin/{binary}" "$@"\n')


def include_flags(flags, label):
    rewritten = []
    args = iter(flags)
    index = 0
    copied = {}
    for flag in args:
        if flag.startswith(('-DJANK_RESOURCE_DIR=', '-DJANK_CLANG_PATH=',
                            '-DJANK_CLANG_RESOURCE_DIR=', '-DJANK_CLANG_PREFIX=')):
            continue
        kind = None
        value = None
        if flag in ('-I', '-isystem'):
            kind, value = flag, next(args)
        elif flag.startswith('-isystem'):
            kind, value = '-isystem', flag[len('-isystem'):]
        elif flag.startswith('-I'):
            kind, value = '-I', flag[2:]
        if kind is None:
            rewritten.append(flag)
            continue
        source = pathlib.Path(os.path.normpath(value))
        if not source.is_absolute():
            raise RuntimeError(f'Unresolved relative include in {label}: {source}')
        local = source.is_relative_to(common.REPO)
        if not local or not source.exists():
            # The original compiler may name optional system include directories.
            exists = subprocess.run(common.docker('test', '-d', source)).returncode == 0
            if not exists:
                continue
        if source not in copied:
            destination = SDK / 'include' / label / str(index)
            index += 1
            if local:
                copy(source, destination)
            else:
                container_copy(source, destination)
            copied[source] = destination
        destination = copied[source]
        rewritten.append(f'{kind}@SDK@/{destination.relative_to(SDK)}')
    return rewritten


def package_host():
    bundle_executable(ROOT / 'artifacts/build-host/jank', 'jank')
    bundle_executable('/usr/lib/llvm-23/bin/clang++', 'clang')
    copy(common.REPO / '.clang-format', SDK / 'host/lib/.clang-format')
    common.command(common.docker('/usr/lib/llvm-23/bin/clang', '-shared', '-fPIC',
                   ROOT / 'sdk/host-resource-shim.c', '-ldl',
                   '-o', SDK / 'host/lib/libjank-sdk-host.so'))
    for name, soname in [('GL', 'libGL.so.1'), ('X11', 'libX11.so.6'), ('m', 'libm.so.6'),
                         ('pthread', 'libpthread.so.0'), ('dl', 'libdl.so.2'), ('rt', 'librt.so.1')]:
        bundle_executable(f'/usr/lib/x86_64-linux-gnu/{soname}', f'lib{name}.so', directory='lib')
    executable(SDK / 'artifacts/build-host/jank', wrapper('jank', '../..'))
    resources = SDK / 'artifacts/host-resources'
    copy(common.REPO / 'compiler+runtime/src/jank', resources / 'src/jank')
    copy(ROOT / '.tools/host-install/lib/jank/0.1/include', resources / 'include')
    container_copy('/usr/lib/llvm-23/lib/clang/23', SDK / 'host/lib/clang/23')
    executable(resources / 'bin/clang++', wrapper('clang', '../../..'))
    config = json.loads((ROOT / 'artifacts/build-host/target_config.json').read_text())
    flags = include_flags(config['jit_flags'].split(), 'host')
    config['jit_flags'] = ' '.join([*flags, '-L@SDK@/host/lib'])
    config['clang_bin'] = '@SDK@/artifacts/host-resources/bin/clang++'
    config['aot_flags'] = '-fsyntax-only'
    (SDK / 'host/target_config.template.json').write_text(json.dumps(config, indent=2))
    executable(SDK / 'host/bin/clang++', wrapper('clang', '../..'))


def main():
    required = ['artifacts/build-host/jank', 'artifacts/build-wasm64/libjank-static-runtime.a',
                'artifacts/build-binaryen/bin/wasm-opt']
    for path in required:
        if not (ROOT / path).is_file():
            raise RuntimeError(f'Missing {path}; wait for the existing bootstrap to finish first')
    for platform in ('native', 'wasm64'):
        common.command(['bash', ROOT / 'scripts/build-raylib.sh', platform])
    if SDK.exists():
        shutil.rmtree(SDK)
    SDK.mkdir(parents=True)
    for path in ['scripts/jank-build.py', 'scripts/app-index.html',
                 'scripts/raylib-loop-driver.cpp', 'scripts/jspi-suspend-guard.js',
                 'scripts/exception-roots.cpp', 'sdk/wasm-entry.cpp',
                 'wasm-probe/spill-pointers.py']:
        copy(ROOT / path, SDK / path)
    copy(ROOT / 'sdk/jank-wasm.py', SDK / 'scripts/jank-wasm.py')
    executable(SDK / 'bin/jank-wasm', '#!/bin/sh\nset -eu\n'
               'root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\n'
               'exec python3 "$root/scripts/jank-wasm.py" "$@"\n')
    package_host()
    bundle_executable(ROOT / 'artifacts/build-binaryen/bin/wasm-opt', 'wasm-opt')
    executable(SDK / 'bin/wasm-opt', wrapper('wasm-opt', '..'))
    database = json.loads((ROOT / 'artifacts/build-wasm64/compile_commands.json').read_text())
    wasm_flags, _ = common.wasm_compile_flags(database)
    wasm_flags = ['@SDK@/.tools/gc-wasm/emsdk/upstream/emscripten/em++',
                  *include_flags(wasm_flags[1:], 'wasm')]
    target = SDK / 'artifacts/build-wasm64'
    target.mkdir(parents=True, exist_ok=True)
    (target / 'compile_commands.template.json').write_text(json.dumps([{
        'file': '/src/cpp/jank/runtime/context.cpp', 'directory': '@SDK@',
        'command': shlex.join([*wasm_flags, '-c', '/src/cpp/jank/runtime/context.cpp'])}]))
    copy(ROOT / 'artifacts/build-wasm64/libjank-static-runtime.a', target / 'libjank-static-runtime.a')
    emsdk = ROOT / '.tools/gc-wasm/emsdk'
    for link_flags in (['-sJSPI=1'], ['-Oz', '-sEXIT_RUNTIME=0']):
        common.command(common.docker('env', f'EM_CONFIG={emsdk / ".emscripten"}',
                       emsdk / 'upstream/emscripten/em++', '-x', 'c++', '/dev/null', '--no-entry',
                       '-sMEMORY64=1', '-fwasm-exceptions', '-sUSE_GLFW=3', '-sMAX_WEBGL_VERSION=2',
                       '-sALLOW_MEMORY_GROWTH=1', *link_flags, '-o', target / 'cache-warm.js'))
    for directory in ('upstream/bin', 'upstream/lib/clang', 'upstream/share', 'upstream/emscripten'):
        source = emsdk / directory
        if source.exists():
            destination = SDK / '.tools/gc-wasm/emsdk' / directory
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(source, destination, symlinks=True,
                            ignore=shutil.ignore_patterns('.git', '__pycache__', '*.pyc',
                                                         'test', 'tests', 'docs', 'media'))
    tools = SDK / '.tools/gc-wasm/emsdk/upstream/bin'
    needed = {'clang', 'clang++', 'clang-24', 'lld', 'wasm-ld', 'llvm-ar', 'llvm-ranlib',
              'llvm-nm', 'llvm-objcopy', 'llvm-objdump', 'llvm-readobj', 'llvm-size', 'llvm-strip',
              'wasm-opt', 'wasm-emscripten-finalize', 'wasm-metadce', 'wasm2js', 'wasm-as'}
    for path in tools.iterdir():
        if path.is_file() or path.is_symlink():
            if path.name not in needed:
                path.unlink()
    cache = SDK / '.tools/gc-wasm/emsdk/upstream/emscripten/cache'
    for directory in (cache / 'sysroot/lib/wasm32-emscripten', cache / 'ports'):
        if directory.exists():
            shutil.rmtree(directory)
    for path in target.glob('cache-warm.*'):
        path.unlink()
    copy(common.NODE.parent.parent, SDK / '.tools' / common.NODE.parent.parent.name)
    for platform in ('native', 'wasm64'):
        source = ROOT / 'artifacts/raylib' / platform
        if source.exists():
            for item in ('include', 'lib', 'raylib-LICENSE', 'raygui-LICENSE'):
                copy(source / item, SDK / 'artifacts/raylib' / platform / item)
    copy(ROOT / 'SDK.md', SDK / 'README.md')
    copy(common.REPO / 'LICENSE', SDK / 'licenses/jank-LICENSE')
    copy(ROOT / '.tools/binaryen-a9141c8cc/LICENSE', SDK / 'licenses/Binaryen-LICENSE')
    copyrights = subprocess.check_output(common.docker('find', '/usr/share/doc', '-name', 'copyright'),
                                        text=True).splitlines()
    for source in copyrights:
        path = pathlib.Path(source)
        container_copy(path, SDK / 'licenses/system' / path.parent.name / 'copyright')
    # Freeze the prebuilt entry variants using the same compiler options as applications.
    flags = [flag.replace('@SDK@', str(SDK)) for flag in wasm_flags]
    for name, source in [('entry', 'sdk/wasm-entry.cpp'), ('raylib-entry', 'scripts/raylib-loop-driver.cpp')]:
        obj = target / f'libjank-wasm-{name}.o'
        common.command(common.docker('env', f'EM_CONFIG={emsdk / ".emscripten"}',
                       *flags, '-O2', '-g', '-c', SDK / source, '-o', obj))
        common.command(common.docker('env', f'EM_CONFIG={emsdk / ".emscripten"}',
                       emsdk / 'upstream/emscripten/emar', 'rcs', obj.with_suffix('.a'), obj))
        obj.unlink()
    archive = SDK.with_suffix('.tar.gz')
    with tarfile.open(archive, 'w:gz') as tar:
        tar.add(SDK, arcname=SDK.name)
    print(f'SDK: {SDK}\nTARBALL: {archive}\nBYTES: {archive.stat().st_size}')


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        sys.exit(f'jank-build sdk: {error}')
