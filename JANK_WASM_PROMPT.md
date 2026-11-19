# Handoff prompt for jank-wasm

Work in this jank research fork. Continue an existing experiment rather than starting a new language implementation. Read this file and `experiments/jank-wasm/README.md` before changing code.

## Contribution boundary

Read `CONTRIBUTING.md` first. Upstream jank rejects AI-generated external contributions, including code and copy. This branch contains AI-assisted research and examples. Work in this fork only. Do not submit these artifacts upstream, claim they were human-created, remove their provenance to bypass the policy, or post upstream discussions on the user's behalf. Any eventual upstream contribution must comply with the maintainers' policy and receive separate user authorization.

## Branch scope

The optional Zig add-on is preserved on [zig-addon](https://github.com/h0rv/jank-wasm/tree/zig-addon/experiments/jank-wasm).
The Zig-specific goals, commands and file paths in this historical handoff refer
to that branch. Main now defaults to the pure-jank `hello-cljc` project and rejects
Zig project configs. Keep the non-Zig compiler/runtime and mixed research fixtures.

## Historical goal

Make jank a useful native Clojure environment whose application code can call low-level libraries written in Zig. Improve the build process so Zig's compiler tools can compile and link generated C++ and target runtime components. Then establish whether the same application and Zig implementation can run as a WebAssembly module.

The user prefers jank's Clojure-to-C++ architecture over adding Scheme or another language between Clojure and the final compiler. They want to write Clojure for application logic and Zig for low-level code. They do not want to write C/C++ application implementations. Changes to jank's existing C++ runtime may still be necessary.

Native execution must not require a Wasm engine. Wasm is an alternative deployment target, not a mandatory native FFI format. The target application must not need a JVM. Do not confuse Java-based optional project tooling with jank's native runtime.

This is compiler/runtime research, not a production-ready web framework project. jank is alpha. Do not claim that a passing example makes it suitable for a business-critical production service.

## Repository and starting revision

- The fork is `https://github.com/h0rv/jank-wasm`.
- The original research branch was `research/zig-wasm`.
- `origin` is the user's fork. `upstream` is `jank-lang/jank`.
- The branch starts from upstream PR #1107, `https://github.com/jank-lang/jank/pull/1107`.
- The inspected PR head is `43ffa8d0a6bce1c17c552c6d46f4d6486dc304ed` from `kylc/jank`, branch `cross`.
- That head contains three commits for static-runtime cross compilation, target JSON configuration, and external compiler invocation.
- Preserve that history and credit. Do not force-push or silently rebase the branch.

At handoff, the PR is open and draft. Recheck its state and diff before relying on this snapshot. Read the current source and build requirements rather than assuming an installed package matches this branch. The checked-in build guide mentions LLVM 22, while the installed package used by our probes contains LLVM 23. Resolve the exact requirement from the checked-out build configuration and scripts before building the host compiler.

Submodules were initialized at the research base. Keep their pins unchanged until a specific change is justified. Source preparation is not evidence that the fork's compiler or runtime has been built.

## What PR #1107 provides

The useful separation is:

```text
Host jank compiler
    -> generated C++ for application and core modules
    -> target C++ compiler
    -> target static runtime and application
```

The patch adds `jank_cross_compile`, `jank_host_compiler`, optional emulated TLS, and the `jank_standalone_static_lib_phase_2` build target. Cross mode uses a host compiler to generate C++ that the target compiler can compile. Its static artifact excludes compiler/JIT implementations and LLVM. The static runtime's lack of runtime eval already existed; this PR does not newly remove eval from jank.

The overall CMake project still discovers LLVM/Clang and defines other targets. A separately buildable static artifact is not yet a fully independent runtime-only SDK configuration.

The patch generates `target_config.json` with `triple`, `clang_bin`, `jit_flags` and `aot_flags`. The CLI option is `--target-config`. At the inspected head, the recorded triple is not automatically applied as a target flag. The JSON compiler path does not select the executable actually launched. Some target library/resource paths still come from the host installation. JSON installation and default discovery disagree about its location.

External compiler invocation replaces the embedded Clang driver path. This is useful for wrappers around `zig cc` and `zig c++`, because lowered Clang `-cc1` arguments are not generally accepted by those wrappers. The PR does not include Zig wrappers or a complete Zig target SDK.

The author reports a C++ test executable using an ARM64 Linux musl runtime running on a Raspberry Pi 5. That is useful evidence, but is not our reproduction or a complete one-command pure-jank cross build.

At handoff, macOS and Ubuntu release checks pass, but the PR is not fully green. Observed failures include const-correctness in the JSON loader, missing installed JSON in Nix, and Windows path construction. Recheck current logs before treating those as unchanged or complete diagnoses.

## Existing experiment and actual results

All reproduction sources are under `experiments/jank-wasm`. Downloads, generated files and logs belong in its ignored `.tools`, `.zig-cache`, `zig-out` and `artifacts` directories. Do not commit those directories or generated compiler output containing process-local addresses.

The original environment was macOS arm64, Zig 0.17.1, Node 26.13.1, and an installed jank 0.1-alpha package. The installed binary identifier and exact collector/SDK pins are recorded in the experiment README and `wasm-probe/GC.md`.

The following passed:

1. Native jank calls a Zig static archive through both JIT execution and an AOT executable. The caller tests scalar arguments and a result wider than a signed 32-bit integer.
2. Zig C++ compiles and links the generated native application's C++ against the prebuilt jank static runtime. The final executable runs outside the source directory.
3. The same small C++ caller and Zig source run as freestanding wasm32 and wasm64 modules in Node. These are not Clojure execution tests.
4. C++ vector allocation and destruction work in a wasm32-WASI reactor through 10,000 calls. This test disables exceptions and RTTI; do not generalize that restriction to the whole jank runtime.
5. An isolated form of jank's tagged-pointer representation round-trips on wasm64. It does not involve a collector or the full `oref` type.
6. Emscripten 7.0.0 compiles the actual generated jank application module to a wasm64 object with Wasm exceptions enabled. It has not been linked with a target jank runtime or executed.
7. Newer upstream Boehm allocates and collects on wasm64 with an explicitly registered root. The smoke preserves a chain of 128 allocations through 32 forced collections.

The native Zig C++ test reuses the prebuilt jank runtime and its matching LLVM 23 libc++, libunwind and compiler runtime. It is not a rebuild of all jank dependencies using Zig. The helper also invokes the installed jank compiler to obtain generated source and its launcher before final Zig compilation.

The Zig implementation includes a borrowed-buffer function with explicit status values and unit tests. A jank-side buffer FFI test still needs to be added. Do not claim that its existence proves that path was exercised by jank.

The following failed or remain unresolved:

- Zig 0.17.1 cannot supply libc for the tested wasm64-WASI standard-library build.
- Attempts to compile the jank module with Zig and Emscripten's target headers stopped in C++ header compatibility. This is not proof that such a configuration is impossible, and is not a successful build.
- Actual generated jank C++ fails for wasm32-WASI on pointer widths, pointer bit casts, platform guards, and missing threading types used by Immer and Folly.
- The pinned Boehm collector explicitly rejects wasm64.
- Binaryen's documented `--spill-pointers` route fails during linking with `getStackSpace: failed to find the stack pointer` in our Emscripten memory64 collector test.
- The current Asyncify collector smoke passes, but earlier source variants lost live objects. Their exact source was not retained in this bundle, so reconstructing and minimizing that failure remains necessary. The cause is not diagnosed. Do not call this a reliable solution.
- No full jank Wasm runtime, core library, complete application, browser deployment or jank tagged-reference collector test has passed.

## Memory and platform facts

`compiler+runtime/include/cpp/jtl/primitive.hpp` defines pointer-sized aliases as 64-bit and asserts they equal the pointer size. Ordinary wasm32 fails these assumptions. `jank/runtime/oref.hpp` also packs numbers and tagged pointers into a 64-bit representation. Removing an assertion or changing one typedef is not a wasm32 port.

At the inspected revision, jank pins Boehm `327ef1f8c80a611b2f8b915850c8b2fd38e6595e`. Upstream commit `3f4e077edb2496bfd14e625f3a440f38caac458a`, dated 2026-11-06, adds a wasm64 configuration. Our collector experiment uses later upstream revision `91f30f37b0457566e9823b8360da59f1798f65fc`. The latest release checked during research predates that fix. Do not assume that updating to a released package includes it.

Compare the jank fork's changes before updating its collector pin. Prefer a small justified backport or an explained update. Do not silently discard fork-specific behavior.

A collector inside Wasm cannot assume it can inspect the engine's private execution locals. Every live managed reference must remain visible through compiler instrumentation, explicit roots, an accessible managed stack, or another correctly enforced protocol. A registered global root proves less than a local root, and a raw pointer proves less than jank's tagged representation. Test all relevant cases.

WASI supplies host interfaces, not garbage collection. WasmGC uses engine-managed structs and arrays, not arbitrary C++ objects in linear memory. Allocators such as Zig allocators or mimalloc are not replacements for a tracing collector.

## Work sequence

### 1. Reproduce and define the first milestone

Read the experiment files. Run the native and minimal Wasm checks. Report which results reproduce with the current environment. Inspect the PR's build configuration and agree on the target before making broad changes.

The preferred first full-runtime target is single-threaded wasm64 under Node through Emscripten, with static AOT and no runtime eval. It preserves jank's current pointer width and uses the target environment that already compiles our application module. This is an initial research target, not a decision to abandon WASI or Zig's toolchain.

### 2. Improve native Zig support

Treat Zig function interoperability as already possible through the C ABI. The missing work is repeatable building, packaging and testing, not necessarily a new interop language feature.

Add a source example that builds one Zig library and calls it from jank without a handwritten C++ implementation. Keep boundary types C-compatible. Use pointer/length pairs and explicit status values for buffers. Document ownership and lifetimes. Zig slices, generic types and error unions must stay behind the boundary unless deliberately converted.

Make target compiler selection and flags explicit. Keep host JIT/analysis settings separate from target AOT settings. Do not feed target paths or ABI assumptions into the host JIT accidentally. Preserve the existing compiler path as a supported option.

Check target-config schema, installation, quoting, library discovery and cache identity. Do not treat a recorded triple as if it were applied. Build the target runtime and its dependencies consistently rather than mixing incompatible C++ runtimes. Reproduce native Linux cross compilation before claiming general cross compilation.

### 3. Establish collector correctness

Minimize the Binaryen memory64 failure and the earlier Asyncify failures. Preserve failing reproducers. Do not modify a smoke until it passes without explaining what changed and why. A failure-path source change can alter optimization and hide a rooting bug.

Test live local roots, registered roots, globals, nested calls and tagged references under forced collection. Include temporary values held across calls that allocate. Avoid accidental extra roots or stale untagged copies that make an unsafe test pass. Verify that collections really occurred. Consider native differential tests for value correctness.

If existing transformations cannot be made reliable, investigate explicit root frames or a shadow stack. That means compiler/runtime-maintained reference slots in accessible memory. Cover handwritten C++ runtime locals as well as generated Clojure code. Do not assume instrumenting only application functions is sufficient.

Do not replace the entire collector first. Do not disable collection and call the resulting program a supported general runtime.

### 4. Build and link the target static runtime

Use PR #1107's host/target separation. Generate target core-library C++ using a host compiler. Compile runtime sources, core libraries and dependencies for the same target with compatible libc++, exception handling and compiler support libraries.

Address the platform layer deliberately. Include process paths, filesystem and terminal calls, stack traces, synchronization and thread-related headers. Disabling thread creation alone does not remove Folly/Immer compile-time dependencies. Unsupported features should produce clear failures, not fake results.

Do not copy host archives into a Wasm link. Do not treat defining a Unix macro as a platform implementation. Inspect target-dependent interop type layouts, macros and compile-time evaluation so host facts are not silently baked into target code.

### 5. Run the same application and Zig implementation

Produce a small Clojure application and one Zig kernel with native and Wasm builds. Link the target Zig object into the same Wasm module initially. Native FFI library loading does not automatically work inside Wasm. Separate modules would need deliberate imports, shared-memory rules or data copying.

Require the application to call Zig, manipulate persistent collections, preserve local values through collection, and throw/catch an exception. State any excluded language features.

Only then investigate a WASI deployment or browser packaging. WASI and Emscripten are different host environments. Do not advertise WASI merely because a Wasm module runs in Node with Emscripten's JavaScript support.

## Acceptance criteria

- Native jank calls the Zig library through both JIT and AOT execution.
- The borrowed-buffer interface has jank-side tests for ownership, empty input and error outcomes.
- Target compiler configuration survives installation and uses the selected compiler without host paths leaking into target compilation.
- A target static runtime and its core libraries are built from source using documented pinned dependencies.
- A complete linked Wasm application executes Clojure code and calls the same Zig implementation.
- Forced collection preserves raw and tagged references held through the actual generated application and runtime code.
- A caught exception behaves correctly under the selected Wasm exception model.
- Native tests continue to pass. CI names experimental or expected-failure tests honestly.
- Claims about Wasm width, WASI, browser execution and Zig-built components match the tests actually run.

These are milestones, not statements that the current branch satisfies them.

## Alternatives if the first path stalls

1. Keep native support as the useful deliverable while GC/root-discovery work continues separately.
2. Use explicit root tracking with the existing collector rather than depending entirely on automatic spilling.
3. Investigate wasm32 as a separate representation/portability change. It better matches Zig's supplied WASI libraries but still needs GC integration.
4. Treat WasmGC as a different backend/runtime design with substantially different object representation. It is not the first choice for preserving jank's current C++ interop architecture.

Other Clojure dialects already run on both native and Wasm. ClojureWasm is implemented in Zig and has a WASI interpreter build. let-go has native and browser bytecode-VM builds. clojurust has native compilation and a browser tree-walk interpreter. Those are useful references, not evidence that jank already works or that their FFI carries across targets. Their existence also means this project should be chosen for jank's architecture, not because no alternatives exist.

## Key source locations

Read the complete relevant files before editing:

- `compiler+runtime/CMakeLists.txt`
- `compiler+runtime/cmake/target_json.cmake`
- `compiler+runtime/cmake/install.cmake`
- `compiler+runtime/cmake/dependency/bdwgc.cmake`
- `compiler+runtime/include/cpp/jank/aot/target_config.hpp`
- `compiler+runtime/src/cpp/jank/aot/target_config.cpp`
- `compiler+runtime/src/cpp/jank/aot/processor.cpp`
- `compiler+runtime/src/cpp/jank/util/clang.cpp`
- `compiler+runtime/src/cpp/jank/util/environment.cpp`
- `compiler+runtime/src/cpp/jank/util/environment_dynamic.cpp`
- `compiler+runtime/src/cpp/jank/jit/processor_dynamic.cpp`
- `compiler+runtime/src/cpp/jank/runtime/context_static.cpp`
- `compiler+runtime/include/cpp/jtl/primitive.hpp`
- `compiler+runtime/include/cpp/jank/runtime/oref.hpp`
- The pinned collector's Wasm configuration and Emscripten instructions.

## Reproduction commands

Run these from `experiments/jank-wasm` after reading its environment notes:

```sh
bash scripts/check-jank.sh
bash scripts/check-jank-zig-cpp.sh
bash scripts/check-cpp-zig-wasm.sh
bash scripts/check-cpp-stdlib-wasm.sh
bash scripts/check-wasm-compat.sh
BOOTSTRAP=1 bash scripts/check-gc-wasm.sh all
bash scripts/check-jank-wasm-object.sh
```

The collector `all` suite currently exits 1. That is an unresolved result, not a script problem to suppress. Its bootstrap downloads roughly gigabytes of local SDK files. Do not replace the user's global compiler or install system packages without asking.

## Reporting and scope

Start by reporting the checked-out revision, reproduced results and the next testable milestone. Keep changes small and reviewable. For each claim, distinguish source inspection, successful compilation, successful linking, actual execution and correctness testing.

When blocked, report the exact command and diagnostic. List what remains unknown. Do not produce a polished success summary from a partial object file or a convenient smoke test. Do not promise a schedule without evidence.

Do not open upstream pull requests or contact maintainers automatically. Preserve the fork's AI-assisted provenance and upstream contribution boundary throughout the work.
