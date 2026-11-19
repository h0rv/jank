#!/usr/bin/env python3
"""AI-assisted offline experimental wasm64 project driver."""
import argparse
import importlib.util
import json
import os
import pathlib
import shutil
import subprocess
import sys
import threading
from dataclasses import dataclass

sys.dont_write_bytecode = True

ROOT = pathlib.Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location('jank_build', ROOT / 'scripts/jank-build.py')
common = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = common
SPEC.loader.exec_module(common)


@dataclass(frozen=True)
class Project(common.Project):
    @property
    def out(self):
        return self.root / 'dist'


def expand(value):
    return value.replace('@SDK@', str(ROOT))


def configure():
    if any(char.isspace() for char in str(ROOT)):
        raise RuntimeError('Extract the SDK to a path without whitespace (host JIT flag parser limit)')
    config = ROOT / 'host/lib/target_config.json'
    config.write_text(expand((ROOT / 'host/target_config.template.json').read_text()))
    database = ROOT / 'artifacts/build-wasm64/compile_commands.json'
    database.write_text(expand(database.with_suffix('.template.json').read_text()))
    emsdk = ROOT / '.tools/gc-wasm/emsdk'
    emconfig = emsdk / '.emscripten'
    emconfig.write_text(f'LLVM_ROOT = {str(emsdk / "upstream/bin")!r}\n'
                        f'BINARYEN_ROOT = {str(emsdk / "upstream")!r}\n'
                        f'NODE_JS = [{str(common.NODE)!r}]\n'
                        f'CACHE = {str(emsdk / "upstream/emscripten/cache")!r}\n'
                        'FROZEN_CACHE = True\n')
    os.environ.update(EM_CONFIG=str(emconfig), SPILL_WASM_OPT=str(ROOT / 'bin/wasm-opt'),
                     JANK_RUNTIME_DIR=str(ROOT / 'artifacts/host-resources'),
                     CXX=str(ROOT / 'artifacts/host-resources/bin/clang++'),
                     PATH=f'{ROOT / "bin"}:{os.environ.get("PATH", "")}',
                     LANG='C.UTF-8', LC_ALL='C.UTF-8')
    for name, directory in [('TMPDIR', ROOT / 'artifacts/tmp'),
                            ('XDG_CACHE_HOME', ROOT / 'artifacts/cache')]:
        directory.mkdir(parents=True, exist_ok=True)
        os.environ[name] = str(directory)


def build(project):
    if project.wasm_check != 'single':
        raise RuntimeError('Diagnostic workloads use the research build wrapper, not this SDK')
    stage = project.out / 'stage-wasm'
    stage.parent.mkdir(parents=True, exist_ok=True)
    if stage.exists():
        shutil.rmtree(stage)
    shutil.copytree(project.root, stage, ignore=shutil.ignore_patterns(
        'dist', '.git', 'target', 'artifacts', '.tools', '__pycache__'))
    common.LOGS = project.out / 'logs'

    def run(label, args, **kwargs):
        if label == 'launcher':
            index = args.index('compile')
            args[index:index] = ['--output-target', 'cpp']
        common.logged(f'{project.name}-wasm-{label}', args, cwd=kwargs.pop('cwd', stage), **kwargs)

    modules, launcher = common.generate_sources(project, stage, 'wasm', stage, run)
    common.build_wasm(project, stage, modules, launcher, run)
    print(f'Built {project.out / "wasm" / (project.name + ".js")}')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    for action in ('build', 'run', 'serve'):
        command = sub.add_parser(action)
        command.add_argument('project', nargs='?', default='.')
        if action == 'serve':
            command.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    configure()
    project = Project(**vars(common.load_project(args.project, require_expect=False)))
    if args.action == 'build':
        build(project)
    elif args.action == 'run':
        return subprocess.run([common.NODE, project.out / 'wasm' / f'{project.name}.js']).returncode
    else:
        with common.server(args.port, project=project) as url:
            print(f'Serving {url} (Ctrl-C to stop)', flush=True)
            threading.Event().wait()
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        print(f'jank-wasm: {error}', file=sys.stderr)
        sys.exit(1)
    except KeyboardInterrupt:
        sys.exit(130)
