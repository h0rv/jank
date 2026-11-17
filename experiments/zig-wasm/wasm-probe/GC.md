# Boehm GC on wasm64

This is a standalone allocation and rooting experiment. It does not build jank.
All downloads stay in `.tools/gc-wasm`. Build outputs and logs stay in
`artifacts/gc-wasm`. No global packages or GC source patches are needed.

## Reproduce

Run these commands from `experiments/zig-wasm`, not the repository root.
The first command downloads the official prebuilt Emscripten SDK and upstream
Boehm sources when they are missing.
It does not build LLVM.

```sh
BOOTSTRAP=1 bash scripts/check-gc-wasm.sh all
bash scripts/check-gc-wasm.sh asyncify
bash scripts/check-gc-wasm.sh explicit
```

`all` intentionally returns 1 on the tested tools because the spill pass fails.
The other two commands return 0 with the current source. Each mode has its own
log. The script also requires a final success message, rather than trusting only
Node's exit code. An earlier Asyncify build printed a failure but returned 0
when C++ main returned 1 after an asynchronous collection.

The script pins these versions:

* Boehm commit `91f30f37b0457566e9823b8360da59f1798f65fc`.
* Emscripten SDK 7.0.0, release hash `6afbd83493d647051772d491124187d4e9a0cda9`.
* SDK installer commit `708dcbcc9ee23bc7d2dad44fc90db377e38b771c` for fresh downloads.

The tests ran on macOS arm64 with Node v26.13.1. Set `NODE_BIN` to choose another
Node executable. The SDK also downloads its own tools locally, including Node,
but the script runs the smoke with the Node selected before any SDK activation.

## What was tested

The C collector is built from upstream's `extra/gc.c`, its supported single
object build. The client is C++17. Both use `-O2 -m64`. Neither uses pthreads or
`GC_THREADS`. There is no Asyncify dependency in the explicit-root control.

The client retains a raw pointer to a chain of 128 GC allocations. Each node
contains a raw pointer to the next node. It allocates another 4096 blocks per
round and calls `GC_gcollect()` 32 times. After every call it checks every node's
value and link. It checks that at least 32 collections actually occurred.
The compile-time assertion requires 64-bit pointers.

| Root strategy | Observed result |
| --- | --- |
| Binaryen `--spill-pointers` | Link fails before Node runs. |
| Boehm `EMSCRIPTEN_ASYNCIFY` with `-sASYNCIFY -sASYNCIFY_STACK_SIZE=128000` | Current source passes. Five further runs of the same binary pass. See caution below. |
| Explicit `GC_add_roots` slot, without either transformation | Passes. Two further runs pass. |

Both passing builds print:

```text
PASS: wasm64, 128 nodes, 32 forced collections; collections=608 allocated=35655680 heap=65536 pointer_bits=64
```

The exact spill diagnostic is:

```text
Fatal: getStackSpace: failed to find the stack pointer
```

This happened at both `-O2` and `-O0`. Emscripten invokes its bundled `wasm-opt`
with `--spill-pointers` and `--enable-memory64`, then exits 1. The script preserves
the complete invocation in `artifacts/gc-wasm/spill.log`. No Binaryen patch or
source build was attempted.

## Rooting caution

The current Asyncify smoke is not proof of reliable conservative root discovery.
Earlier versions of this same small test failed with:

```text
FAIL: lost raw-pointer chain at round 0 node 126
FAIL: lost raw-pointer chain at round 1 node 126
```

The exact earlier failed source variants were not retained in this bundle.
Only the current smoke source is included. Reconstructing and minimizing the
older failure is still necessary; the quoted diagnostics record an observation,
not a separately reproducible regression test.

Those versions used `return 1` on a failed check. The final source uses
`std::abort()` so a failed asynchronous test cannot silently return success.
That source change also changed the generated code, and the final binary passes.
The cause of the earlier lost chain was not diagnosed. Treat the result as a
passing smoke with an unresolved root-discovery concern, not a runtime ready for
jank. An extra raw pointer copy or a changed compiler layout can affect a
conservative collector test.

The explicit-root build stores the chain head in a static slot and registers
that slot with `GC_add_roots`. It updates that slot during construction too.
That test demonstrates allocation and collection with a known root in memory.
It does not demonstrate that arbitrary Wasm local variables are visible to GC.
Neither result proves reclamation of every unreachable allocation, although the
heap stays at 65536 bytes during roughly 35 MB of allocations.

No tagged-pointer test was run. In particular, these results do not test jank's
NaN tags or pointer-mask configuration. No jank runtime, exceptions, browser
host, or multithreaded collector was tested. This GC revision is newer than
jank's pinned collector. It includes the November 6 wasm64 configuration change
`3f4e077edb2496bfd14e625f3a440f38caac458a`.

No Zig compiler substitution was attempted here. Zig's separate wasm64 libc
limitation is not evidence about this Emscripten build, and this Emscripten result
is not a Zig-built GC result.

## Upstream basis

The primary instructions are the pinned
[README.emscripten](https://github.com/bdwgc/bdwgc/blob/91f30f37b0457566e9823b8360da59f1798f65fc/docs/platforms/README.emscripten).
They require cooperation from client code to expose Wasm locals, recommend
`--spill-pointers`, and state that multithreading is unsupported.

The Asyncify fallback is implemented in the same revision's `os_dep.c` through
`emscripten_scan_registers`. Its CMake option adds `EMSCRIPTEN_ASYNCIFY`,
`-sASYNCIFY`, and `-sASYNCIFY_STACK_SIZE=128000`. The script uses those same options.
