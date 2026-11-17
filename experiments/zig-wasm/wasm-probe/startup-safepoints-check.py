# AI-assisted output validation: caught language errors need not change Node's exit code.
import pathlib
import re
import sys

path, mode, count, exit_code = sys.argv[1:]
count, exit_code = int(count), int(exit_code)
output = pathlib.Path(path).read_text()
scalar = 'jank -> Zig: scalar and wide result checks passed'
buffer = 'jank -> Zig: borrowed-buffer checks passed'
normal_gc = mode == 'continuous'
no_gc = mode == 'no-gc-reentry'
prefix = 'STARTUP' if normal_gc or no_gc else 'SAFEPOINT'
blocks = re.findall(r'^' + prefix + r' BEGIN: iteration=(\d+)/(\d+)\n(.*?)'
                    r'^' + prefix + r' ITERATION (\d+)/(\d+): collections=(\d+) '
                    r'used-bytes=(\d+) heap-bytes=(\d+) status=(\d+)\n', output, re.M | re.S)
initial = re.search(r'^startup memory: phase=before-spike collections=(\d+) ', output, re.M)
previous = int(initial[1]) if initial else -1
passed = 0
used = []
for expected, block in enumerate(blocks, 1):
    begin, total, body, end, end_total, collections, memory, heap, status = block
    collections = int(collections)
    delta = collections - previous
    collections_ok = (delta >= 0 if normal_gc else delta == 0 if no_gc
                      else delta == (2 if mode == 'safepoint-churn' else 1))
    ok = (int(begin) == int(end) == expected and int(total) == int(end_total) == count
          and body.splitlines().count(scalar) == body.splitlines().count(buffer) == 1
          and status == '0' and collections_ok)
    passed += ok
    previous = collections
    used.append(int(memory))
valid = (mode in ('safepoint', 'safepoint-churn', 'continuous', 'no-gc-reentry')
         and count > 0 and exit_code == 0 and initial is not None
         and (not normal_gc or previous > int(initial[1]))
         and len(blocks) == count and passed == count
         and len(re.findall(r'^' + prefix + r' BEGIN:', output, re.M)) == count
         and output.splitlines().count(scalar) == output.splitlines().count(buffer) == count
         and f'startup diagnostic: exit=0 collections={previous} gc-disabled={0 if normal_gc else 1}'
         in output.splitlines())
if used:
    print(f'{prefix} MEMORY: mode={mode} first-used={used[0]} last-used={used[-1]} '
          f'min-used={min(used)} max-used={max(used)}')
print(f'{prefix} VERDICT: mode={mode} {"PASS" if valid else "FAIL"} '
      f'iterations={count} passed={passed} failed={max(count - passed, 0)} exit={exit_code}')
sys.exit(0 if valid else 1)
