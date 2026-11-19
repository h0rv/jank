# AI-assisted marker-based comparisons of the same linked module before/after spill.
import pathlib
import re
import statistics
import subprocess
import sys
import time

root = pathlib.Path(sys.argv[1])
iterations = int(sys.argv[2])
bits = sys.argv[3] if len(sys.argv) > 3 else '64'
if bits not in ('32', '64'):
    sys.exit('Wasm width must be 32 or 64')
out = root / f'artifacts/wasm{bits}-spike'
logs = root / 'artifacts/logs'
node = root / '.tools/node-v26.13.1-linux-x64/bin/node'
exe = out / 'startup-spill.js'
wasm = exe.with_suffix('.wasm')
scalar = 'jank -> Zig: scalar and wide result checks passed'
buffer = 'jank -> Zig: borrowed-buffer checks passed'
summary = []
timings = {}
correct = {}

for variant in ['baseline', 'spill']:
    if variant == 'spill':
        subprocess.run([sys.executable, str(root / 'wasm-probe/spill-pointers.py'),
                        str(root), str(wasm)], check=True)
    summary.append(f'STARTUP SIZE: variant={variant} wasm-bytes={wasm.stat().st_size}')
    for mode in ['static-roots', 'continuous', 'no-gc-reentry']:
        for sample in range(1, 4 if mode == 'no-gc-reentry' else 2):
            path = logs / f'wasm{bits}-startup-spill-{variant}-{mode}-{sample}.log'
            start = time.monotonic()
            try:
                result = subprocess.run([str(node), str(exe), mode, str(iterations)],
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        text=True, timeout=240)
                code, output = result.returncode, result.stdout
            except subprocess.TimeoutExpired as error:
                code, output = 124, (error.stdout or b'').decode(errors='replace')
            elapsed = time.monotonic() - start
            path.write_text(output)
            counts = (output.splitlines().count(scalar), output.splitlines().count(buffer))
            if mode == 'static-roots':
                ok = (code == 0 and counts == (1, 1)
                      and re.search(r'^startup diagnostic: exit=0 collections=[1-9]\d* gc-disabled=0$',
                                    output, re.M) is not None)
            else:
                check = subprocess.run([sys.executable, str(root / 'wasm-probe/startup-safepoints-check.py'),
                                        str(path), mode, str(iterations), str(code)],
                                       capture_output=True, text=True)
                summary.extend(check.stdout.splitlines())
                ok = check.returncode == 0
            correct[variant, mode, sample] = ok
            summary.append(f'STARTUP SPILL: variant={variant} mode={mode} sample={sample} '
                           f'{"PASS" if ok else "FAIL"} exit={code} scalar={counts[0]} buffer={counts[1]} '
                           f'elapsed-seconds={elapsed:.6f}')
            if mode == 'no-gc-reentry':
                timings.setdefault(variant, []).append(elapsed)
            first_error = next((line for line in output.splitlines()
                                if re.match(r'(RuntimeError:|Aborted\(|The `|Error:)', line)), None)
            if first_error:
                summary.append(f'FIRST ERROR: variant={variant} mode={mode}: {first_error}')

for variant, samples in timings.items():
    summary.append(f'STARTUP TIME: variant={variant} mode=no-gc-reentry iterations={iterations} '
                   f'samples={len(samples)} median-seconds={statistics.median(samples):.6f}')
passed = (all(correct['spill', mode, 1] for mode in ['static-roots', 'continuous'])
          and all(correct[variant, 'no-gc-reentry', sample]
                  for variant in ['baseline', 'spill'] for sample in range(1, 4)))
summary.append(f'STARTUP SPILL VERDICT: {"PASS" if passed else "FAIL"}')
path = logs / f'wasm{bits}-startup-spill.results'
path.write_text('\n'.join(summary) + '\n')
print(path.read_text(), end='')
sys.exit(0 if passed else 1)
