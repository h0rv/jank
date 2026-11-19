"""AI-assisted bounded ABI and spill-store verification for bench-cljc mode 2."""
import json
from pathlib import Path
import re
import subprocess
import sys

IDENT = r'\$(?:"(?:\\.|[^"\\])*"|[^\s()]+)'


def signature(header):
    return [re.findall(r'\b(?:i32|i64|f32|f64|funcref|externref|v128)\b', values)
            for kind in ('param', 'result')
            for values in [' '.join(re.findall(r'\(' + kind + r' ([^)]*)\)', header))]]


def inspect_wat(path):
    declarations = {}
    imports = {}
    exports = {}
    counts = dict(i64_stores=0, memory_fills=0, stack_sets=0)
    memory64 = False
    with path.open() as stream:
        for line in stream:
            if line.startswith(' (data '):
                continue
            declaration = re.match(r' \((func|memory|table|global|tag) (' + IDENT + r')(.*)', line)
            if declaration:
                kind, name, tail = declaration.groups()
                if kind == 'func':
                    value = signature(tail)
                elif kind == 'global':
                    match = re.match(r' (\(mut \w+\)|\w+)', tail)
                    if not match:
                        raise ValueError('Unsupported global declaration')
                    value = match[1]
                else:
                    value = tail.strip().removesuffix(')')
                declarations[kind, name] = value
                if kind == 'memory':
                    memory64 |= bool(re.search(r'\bi64\b', tail))
            imported = re.match(r' \(import ("[^"]*") ("[^"]*") \(func (' + IDENT + r')(.*)', line)
            if line.startswith(' (import '):
                if not imported:
                    raise ValueError('Unsupported non-function import')
                module, field, name, tail = imported.groups()
                declarations['func', name] = signature(tail)
                imports[module, field] = signature(tail)
            exported = re.match(r' \(export ("[^"]*") \((\w+) (' + IDENT + r')\)\)', line)
            if exported:
                field, kind, name = exported.groups()
                exports[field] = (kind, name)
            counts['i64_stores'] += len(re.findall(r'\(i64\.store(?:8|16|32)?\b', line))
            counts['memory_fills'] += line.count('(memory.fill')
            counts['stack_sets'] += line.count('(global.set $__stack_pointer')
    if not imports or not exports:
        raise ValueError('Empty module interface')
    return dict(imports=imports, exports={field: (kind, declarations[kind, name])
                for field, (kind, name) in exports.items()}, counts=counts, memory64=memory64)


def verify(reference, final, source, unsafe, variant):
    if final['memory64'] or not source['memory64']:
        raise ValueError('Expected memory32 final and memory64 source')
    if final['imports'] != reference['imports'] or final['exports'] != reference['exports']:
        differences = {kind: {str(key): (reference[kind].get(key), final[kind].get(key))
                       for key in reference[kind].keys() | final[kind].keys()
                       if reference[kind].get(key) != final[kind].get(key)}
                       for kind in ('imports', 'exports')}
        raise ValueError(f'Mode-2 reference and replacement import/export signatures differ: {differences}')
    if variant == 'spill':
        for key in ('i64_stores', 'memory_fills', 'stack_sets'):
            if final['counts'][key] != source['counts'][key]:
                raise ValueError(f'Lowering changed spill evidence: {key}')
            if final['counts'][key] <= unsafe['counts'][key]:
                raise ValueError(f'Missing spill evidence: {key}')
    return dict(abi='PASS', memory32=True, variant=variant,
                final=final['counts'], unlowered=source['counts'], unsafe=unsafe['counts'],
                imports=len(final['imports']), exports=len(final['exports']))


def main():
    root, *files, variant = sys.argv[1:]
    disassembler = Path(root) / '.tools/gc-wasm/emsdk/upstream/bin/wasm-dis'
    modules = []
    for filename in files:
        path = Path(filename)
        wat = path.with_suffix('.verify.wat')
        subprocess.run([str(disassembler), str(path), '-o', str(wat)], check=True)
        modules.append(inspect_wat(wat))
    result = verify(*modules, variant)
    output = Path(files[1]).with_suffix('.verification.json')
    output.write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))


if __name__ == '__main__':
    main()
