# Wasm GC versus jank's current collector

AI-assisted research for h0rv/jank-wasm only; no upstream submission. Inspected `main`
at `0573e30c02f19cba9db406876d76ee1fadf02dc9`; remote
`research/zig-wasm` is `a2f9916517d67860bce2978bd5d97914d80d7d44`.
Stayed on main as requested. No commits or pushes. Read AGENTS.md,
CONTRIBUTING.md, JANK_WASM_PROMPT.md and experiments/jank-wasm/README.md.

## Current wasm64 collector in ten lines (source/docs, not rerun here)

1. Runtime objects still occupy linear memory and are collected by conservative bdwgc, not Wasm GC.
2. bdwgc remains pinned to `327ef1f8c80a611b2f8b915850c8b2fd38e6595e`; an Emscripten-only private copy receives the credited wasm64 word-size backport.
3. `cmake/dependency/bdwgc.cmake` masks candidate words with `0x0000FFFFFFFFFFFF` to recognize NaN-boxed addresses.
4. The target is non-threaded; GC_THREADS is conditional and futures explicitly reject unsupported use.
5. Codegen registers lifted static words with GC_add_roots; the diagnostic driver also registers `[__global_base,__data_end)`.
6. Wasm locals/operand-stack values are not ordinary linear-memory stack words for Boehm to scan; static roots alone do not fix them.
7. The boundary-safepoint experiment disables GC inside jank calls and collects only after returning, bounding neither peak allocation nor arbitrary reentrancy.
8. The continuous-GC experiment flattens operand expressions then spills live pointer-width i64 locals across calls into the linear stack.
9. Its private Binaryen patch adds memory64 stack arithmetic, exception cleanup and zeroed spill slots; names must preserve __stack_pointer, and startup uses a 4 MiB stack.
10. All eleven lifetime tests need an additional test-only exception-storage root shim; ordinary unspilled startup still fails, so this is not general Wasm support.

The README records 142% startup module growth and 22.704x matched GC-disabled
whole-process time for its diagnostic flatten/spill comparison, not an isolated
GC cost. No previous full-runtime result was remeasured in this investigation.

## Object model: verified source evidence

Paths in this section are relative to `compiler+runtime/`.

| Area | Evidence and implication |
| --- | --- |
| Allocation | `include/cpp/jank/runtime/oref.hpp:3031–3106`, `make_box`: GC_malloc_explicitly_typed(sizeof(T), descriptor), placement new, new(UseGC), or new(PointerFreeGC). Arrays use new(UseGC) T[length]. These allocate byte-addressable C++ layouts, not struct.new objects. `include/cpp/jank/gc.hpp` includes gc_cpp.h, gc_allocator.h and gc_typed.h. |
| Reference representation | `runtime/oref.hpp:54–108,145,202–207`: pointers carry tag 0xFFFa in the top 16 bits, lower 48 bits are addresses; real and i32 values can be inline. Pointer/integer bit_cast/reinterpret_cast and masked T* recovery assume numeric addresses. make_box asserts sizeof(oref<T>) == sizeof(T*). An engine GC reference is not a numeric address for this scheme. |
| Headers/dispatch | `runtime/object.hpp:411–428,614–615`: object inherits gc, has virtual destructor and methods, plus object_type and object_behavior fields. `runtime/obj/cons.hpp:47–48` holds head/tail object_ref fields. `runtime/obj/jit_function.hpp:85+` also holds native function pointers. C++ virtual calls use the compiler ABI/vtables; enabling GC does not replace that layout/dispatch with typed GC references. |
| Arithmetic/FFI | `runtime/obj/array.hpp:156` clones with std::copy(data.data, data.data + size, ...); indexed reads/writes use data[i]. `runtime/obj/native_pointer_wrapper.hpp` stores void* and reinterpret_casts it to T*. Such interior addresses/borrowed buffers remain linear-memory concepts. |
| Containers | `include/cpp/jank/type.hpp:25–40`: native_allocator = gc_allocator<T>, Immer gc_heap/no_refcount/gc_transience policy, Folly fbvector with GC allocator. `runtime/detail/type.hpp:41–57`: Immer vector/set/map store object_ref keys/values. These C++ container nodes and backing buffers cannot simply contain raw engine references as ordinary sized fields. |
| Destruction | `src/cpp/jank/codegen/cpp_processor.cpp:1871–1918`: cpp/new intentionally does not register finalizers (cycle concern); cpp/delete explicitly calls a nontrivial destructor then GC_free. `object : gc` has a virtual destructor, but is not evidence that GC invokes every destructor. Search found no GC_register_finalizer/gc_cleanup integration in compiler+runtime. Engine GC is not a substitute for explicit C++ resource destruction. |
| Static roots | `src/cpp/jank/codegen/cpp_processor.cpp:2130,2166` emits GC_add_roots for lifted globals; `experiments/jank-wasm/wasm-probe/startup-driver.cpp:83` registers the entire diagnostic static range. |

## Tool survey (executed locally)

Tools were initially absent; checked PATH, home and /opt rather than assuming
the old experiment environment existed. Installed SDKs only under
`/home/ubuntu/tools`, no global package installs or shell startup edits.
Emsdk latest resolved to the same **7.0.0** discussed in the existing docs.
It ships Clang **24.0.0git**, LLVM revision
`84ba7b37f02df5a5567e31a1bcfa0f607e578f12`, Emscripten revision
`777e6e5db7b4990bcaeb1b9998ed642cc84e6629`, and Binaryen
**133 (version_133-159-ga9141c8cc)**. Also downloaded official Binaryen 125;
`wasm-opt --version` printed `wasm-opt version 125 (version_125)`; the probes
use SDK 133. Node selected from the original PATH is **v24.22.2**, not SDK Node.

`bash tool-checks.sh` captures reproducible commands. Relevant printed output:

```text
Available CPUs for this target:
    bleeding-edge
    generic
    lime1
    mvp
#define __wasm_gc__ 1
#define __wasm_reference_types__ 1
wasm-opt version 133 (version_133-159-ga9141c8cc)
  --gsi                                         globally optimize struct values
  --gto                                         globally optimize GC types
  --gufa                                        Grand Unified Flow Analysis:
  --heap2local                                  replace GC allocations with
  --remove-unused-types                         remove unused private GC types
  --enable-gc                                   Enable garbage collection
Binaryen GC passes: exit=0
0.17.1
clang version 22.1.8
Zig cc externref table/funcref object: exit=0
llc not shipped by emsdk; used clang feature macros and real codegen instead
```

Clang `-###` explicitly emitted `-target-feature +gc` and
`-target-feature +reference-types`. Thus **-mgc is accepted**, not an unknown
flag. But compiling ordinary C++ `Cell { int value; Cell *next; }` with
`-mgc -mreference-types -O2` disassembled to:

```wat
(type $0 (func (param i32) (result i32)))
(memory $0 1)
(func $0 (type $0) (param $0 i32) (result i32)
  (i32.load (local.get $0)))
;; features section includes reference-types and gc
```

Feature recognition/metadata is **not** automatic C++ struct-to-GC lowering.
The verified Clang interfaces expose externref and funcref/table operations;
no C++ managed struct/array allocation interface was demonstrated. This does
not assert LLVM has no GC instruction support anywhere internally. A custom
frontend/backend or separate WAT/GC-producing compiler can emit those types.
Emscripten's C++ path remains linear memory in these checks; Binaryen consumes,
assembles and optimizes actual GC structs successfully. The initial GC pass
command failed `Fatal: GTO requires --closed-world`; adding that required
flag fixed it. An attempted `--print-supported-extensions` was unsupported
on wasm32, and `-target-feature +help` was rejected, so neither was used as
evidence of absent GC support.

Official Zig **0.17.1** was available and downloaded unchanged. `zig targets`
lists `gc` and `reference_types` for wasm32/wasm64. Its bundled clang is 22.1.8
and successfully compiled the externref table/funcref probe with both flags.
That is Zig's C/C++ frontend, **not proof of a native Zig managed-object model**.
No native Zig struct.new emitter or jank Zig-based GC migration was tested.
An initial Zig syntax-only command hit a temporary object rename failure;
actual `-c ... -o` compilation succeeded without changing the installation.

## Probe output

`bash run.sh` exited 0 after expected rejection checks, producing:

```text
=== expected rejection: BAD_FIELD ===
refs.cpp:8:28: error: field has sizeless type '__externref_t'
    8 | struct Bad { __externref_t value; };
      |                            ^
1 error generated.
=== expected rejection: BAD_HEAP ===
refs.cpp:11:19: error: allocation of sizeless type '__externref_t'
   11 | void heap() { new __externref_t; }
      |                   ^~~~~~~~~~~~~
1 error generated.
=== expected rejection: BAD_ARRAY ===
refs.cpp:14:15: error: WebAssembly table must be static
   14 | __externref_t values[2];
      |               ^
1 error generated.
=== expected rejection: BAD_ADDRESS ===
refs.cpp:17:42: error: cannot take address of WebAssembly reference
   17 | void address(__externref_t x) { auto p = &x; }
      |                                          ^~
1 error generated.
=== funcref syntax ===
node v24.22.2
GC: 16000000 cons + 16000000 boxes; result=1999999; RSS MiB=56,56,56,56,56,56,56,56
externref: identity/table retain/clear PASS
hybrid: result=42, zero-result=0, null cast traps PASS; 1000000 JS->C->GC calls ms=33.15
```

Static zero-length externref arrays are Clang's **special Wasm table
declarations**, not ordinary C arrays in linear memory. The first probe draft
used length 1 and correctly failed `only zero-length WebAssembly tables are
currently supported`; the working version uses length 0 plus table.grow.

The WAT has no linear memory, allocates actual box/cons structs without an
optimizer, and returns the last payload to prevent a vacuous result. A second
run with `node --trace-gc run.mjs ../artifacts/wasm-gc-probe` also exited 0,
same eight RSS samples, and counted **878 Scavenge/Mark-Compact log lines**:

```text
[9822:0x28316000]       28 ms: Scavenge 5.3 (6.8) -> 4.6 (7.8) MB, pooled: 0 MB, 0.49 / 0.00 ms  (average mu = 1.000, current mu = 1.000) allocation failure;
hybrid: result=42, zero-result=0, null cast traps PASS; 1000000 JS->C->GC calls ms=20.39
```

Full trace is ignored `../artifacts/wasm-gc-probe/gc-trace.log`. No forced JS GC
was used. RSS and trace support bounded observed reclamation, not a formal
proof or an exact engine heap-size measurement.

The hybrid actually imports the GC module's Wasm functions (not JS allocator
wrappers), stores an integer handle and bias in a C linear-memory struct,
uses table.set/table.get, and clears the slot. Disassembly confirms i32.store
at offsets 65536/65540, calls alloc/read, and the table operations. Cost per
cycle is two module calls, one table.get and two table.set operations plus
linear-memory access, allocation, and JS entry. The elapsed times above are
whole loops, **not a measured slowdown versus a matched all-GC baseline**.
One slot suffices for the demo; a real root table needs free-slot management,
exception-safe release, stale-handle prevention and explicit lifetime rules.
An integer stored in C memory by itself does not root the engine object.

## Background knowledge (not toolchain-verified here)

Kotlin/Wasm, Dart dart2wasm, Google's Java J2Wasm toolchain in the J2CL project,
OCaml wasm_of_ocaml, and Scheme Hoot are examples targeting engine-managed
Wasm GC. Ordinary J2CL JavaScript output is distinct from J2Wasm output.
Go's standard wasm ports use linear memory and Go's own GC, not Wasm GC.
These projects/versions were not installed or benchmarked in this task.

## Conclusion and limits

Wasm GC works in the installed Node today, and a handle-table boundary is
feasible. It is **not a drop-in bdwgc replacement** for jank's current C++
object graph. A serious migration must redesign oref representation, object
allocation/access/dispatch, collections, FFI ownership and resource cleanup,
or keep a hybrid with explicit table-root lifetimes. A separate GC-aware
codegen path/runtime would be a substantial project; just setting -mgc or
--enable-gc is not it. The small probes are wasm32 (independent of the current
wasm64 Boehm experiment). No browser, wasm64 GC hybrid, full jank build, native
regression suite, or production finalization/exception design was tested.
